import gzip
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Tentukan root directory proyek (naik 2 level dari ./scripts/fetch/fetch_stackexchange.py)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Load file .env yang ada di root dengan override=True agar selalu membaca nilai terbaru di .env
load_dotenv(ROOT_DIR / ".env", override=True)


def clean_html(raw_html: str) -> str:
    """Membersihkan tag HTML sambil mempertahankan struktur baris pada blok kode/log."""
    text = re.sub(
        r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
        r"\n[CODE_BLOCK]\n\1\n[/CODE_BLOCK]\n",
        raw_html,
        flags=re.DOTALL,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_description(cleaned_text: str, max_len: int = 1000) -> str:
    """Menggabungkan ringkasan gejala dan potongan log error dari pertanyaan."""
    code_blocks = re.findall(r"\[CODE_BLOCK\]\n(.*?)\n\[/CODE_BLOCK\]", cleaned_text, flags=re.DOTALL)
    plain_text = re.sub(r"\[CODE_BLOCK\].*?\[/CODE_BLOCK\]", "", cleaned_text, flags=re.DOTALL).strip()
    plain_text = re.sub(r"\n{2,}", "\n", plain_text)

    if code_blocks:
        log_part = "\n".join(code_blocks)[:500]
        combined = f"{plain_text[:450]}\n\nLog/Config:\n{log_part}"
        return combined[:max_len]
    return plain_text[:max_len]


def extract_error_code(text: str) -> str:
    """Mendeteksi kode status HTTP atau kode error sistem umum menggunakan Regex."""
    patterns = [
        r"\b(400|401|403|404|405|408|429|500|502|503|504)\b",
        r"\b(OOMKilled|CrashLoopBackOff|ImagePullBackOff|ENOSPC|EADDRINUSE|EMFILE|NXDOMAIN|Deadlock|Timeout|Connection refused)\b",
    ]
    found = []
    for pat in patterns:
        matches = re.findall(pat, text, flags=re.IGNORECASE)
        for m in matches:
            normalized = m.upper() if len(m) <= 6 else m
            if normalized not in found:
                found.append(normalized)
    return ", ".join(found[:3]) if found else "General Error"


def detect_location(text: str, default_tag: str) -> str:
    """Mengidentifikasi komponen/service terdampak dari teks judul & isi."""
    components = [
        "Nginx", "Apache", "PostgreSQL", "MySQL", "Redis", "Docker",
        "Kubernetes", "Gunicorn", "Flask", "FastAPI", "API Gateway", "Ingress", "Linux", "Systemd"
    ]
    detected = [comp for comp in components if re.search(rf"\b{comp}\b", text, flags=re.IGNORECASE)]
    if detected:
        return " / ".join(detected[:3])
    return default_tag.capitalize()


def infer_severity(text: str) -> str:
    """Menentukan tingkat keparahan awal (SEV1-SEV4) berdasarkan kata kunci dampak."""
    lower = text.lower()
    if any(k in lower for k in ["production down", "outage", "data loss", "500", "502", "503", "oomkilled", "crashloopbackoff", "enospc"]):
        return "SEV1" if any(k in lower for k in ["down", "outage", "data loss", "oomkilled", "enospc"]) else "SEV2"
    if any(k in lower for k in ["timeout", "slow", "high latency", "404", "403", "deadlock", "connection refused"]):
        return "SEV3"
    return "SEV4"


def parse_root_cause_and_resolution(cleaned_answer: str) -> tuple[str, str]:
    """Memisahkan paragraf pertama sebagai ringkasan root_cause dan keseluruhan sebagai resolution."""
    plain_ans = re.sub(r"\[/?CODE_BLOCK\]", "", cleaned_answer).strip()
    paragraphs = [p.strip() for p in plain_ans.split("\n") if len(p.strip()) > 25]

    root_cause = paragraphs[0][:350] if paragraphs else "Konfigurasi atau resource service tidak sesuai dengan beban/aturan sistem."
    resolution = plain_ans[:1200]
    return root_cause, resolution


def generate_content_hash(title: str, description: str) -> str:
    """Menghasilkan hash SHA-256 untuk validasi anti-duplikasi."""
    raw = f"{title.strip().lower()}|{description.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _http_get_json(url: str) -> dict[str, Any]:
    """Helper HTTP GET yang aman terhadap kompresi GZIP maupun plain JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sre-triage-assistant/1.0",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        raw_bytes = response.read()
        if response.info().get("Content-Encoding") == "gzip":
            raw_bytes = gzip.decompress(raw_bytes)
        return json.loads(raw_bytes.decode("utf-8"))


def fetch_incident_candidates(
    site: str,
    tagged: str,
    category: str,
    query_text: str = "",
    limit: int = 15,
    min_score: int = 5,
    api_key: str | None = None,
    seen_hashes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Mengambil pasangan pertanyaan error + jawaban tervalidasi dari Stack Exchange API."""
    if seen_hashes is None:
        seen_hashes = set()

    search_params: dict[str, Any] = {
        "order": "desc",
        "sort": "votes",
        "accepted": "True",
        "min": min_score,
        "tagged": tagged,
        "site": site,
        "filter": "withbody",
        "pagesize": limit,
    }
    if query_text:
        search_params["q"] = query_text
    if api_key:
        search_params["key"] = api_key

    search_url = f"https://api.stackexchange.com/2.3/search/advanced?{urllib.parse.urlencode(search_params)}"
    q_data = _http_get_json(search_url)

    quota_rem = q_data.get("quota_remaining", "unknown")
    print(f"    -> Ditemukan {len(q_data.get('items', []))} item (Sisa kuota API: {quota_rem})")

    if "backoff" in q_data:
        time.sleep(int(q_data["backoff"]) + 1)

    questions = q_data.get("items", [])
    answer_ids = [str(q["accepted_answer_id"]) for q in questions if "accepted_answer_id" in q]
    answers_map: dict[int, str] = {}

    if answer_ids:
        ans_params: dict[str, Any] = {
            "site": site,
            "filter": "withbody",
        }
        if api_key:
            ans_params["key"] = api_key

        ids_str = ";".join(answer_ids)
        ans_url = f"https://api.stackexchange.com/2.3/answers/{ids_str}?{urllib.parse.urlencode(ans_params)}"
        a_data = _http_get_json(ans_url)
        for ans in a_data.get("items", []):
            answers_map[ans["answer_id"]] = clean_html(ans.get("body", ""))

    candidates = []

    for q in questions:
        acc_id = q.get("accepted_answer_id")
        if not acc_id or acc_id not in answers_map:
            continue

        title = unescape(q["title"]).strip()
        cleaned_q = clean_html(q.get("body", ""))
        description = extract_description(cleaned_q)
        content_hash = generate_content_hash(title, description)

        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)

        full_text = f"{title} {description}"
        root_cause, resolution = parse_root_cause_and_resolution(answers_map[acc_id])

        candidates.append({
            "title": title,
            "error_code": extract_error_code(full_text),
            "location": detect_location(full_text, tagged.split(";")[0]),
            "description": description,
            "root_cause": root_cause,
            "resolution": resolution,
            "category": category,
            "severity": infer_severity(full_text),
            "source_url": q["link"],
            "content_hash": content_hash,
            "is_synced": 1,
        })

    return candidates


if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("STACKEXCHANGE_API_KEY")
    if api_key:
        api_key = api_key.strip()
        print(f"[OK] API Key terbaca dari .env ({api_key[:5]}***)\n")
    else:
        print(f"[PERINGATAN] STACKEXCHANGE_API_KEY kosong/tidak ditemukan di {ROOT_DIR / '.env'}!\n")

    # Format: (site, tagged, query_text, category, limit)
    # Catatan: Stack Exchange API tidak memakai operator OR pada parameter 'q'
    queries = [
        # --- NETWORK ---
        ("serverfault", "nginx", "502 bad gateway", "network", 15),
        ("serverfault", "nginx", "504 gateway timeout", "network", 15),
        ("serverfault", "dns", "NXDOMAIN", "network", 10),
        ("serverfault", "dns", "SERVFAIL", "network", 10),
        ("serverfault", "ssl;nginx", "certificate", "network", 12),
        ("stackoverflow", "cors", "Access-Control-Allow-Origin", "network", 12),

        # --- DATABASE ---
        ("dba", "postgresql", "too many connections", "database", 15),
        ("dba", "postgresql", "deadlock", "database", 12),
        ("dba", "mysql", "deadlock", "database", 15),
        ("stackoverflow", "redis", "Connection refused", "database", 12),

        # --- DEPLOYMENT ---
        ("stackoverflow", "kubernetes", "CrashLoopBackOff", "deployment", 15),
        ("stackoverflow", "kubernetes", "ImagePullBackOff", "deployment", 12),
        ("stackoverflow", "docker", "exit code 137", "deployment", 12),
        ("serverfault", "systemd", "exit-code", "deployment", 12),

        # --- RESOURCE ---
        ("serverfault", "linux;memory", "Out of memory", "resource", 15),
        ("serverfault", "docker", "no space left on device", "resource", 15),
        ("serverfault", "linux", "Too many open files", "resource", 12),
    ]

    all_candidates = []
    global_seen_hashes: set[str] = set()

    for site, tagged, q_text, cat, lim in queries:
        print(f"Fetching [{cat}] from {site} (tagged='{tagged}', q='{q_text}')...")
        try:
            items = fetch_incident_candidates(
                site=site,
                tagged=tagged,
                category=cat,
                query_text=q_text,
                limit=lim,
                min_score=5,
                api_key=api_key,
                seen_hashes=global_seen_hashes,
            )
            all_candidates.extend(items)
        except Exception as e:
            print(f"  [!] Gagal fetch {site} ({tagged}): {e}")
        time.sleep(1.0)

    output_path = data_dir / "raw_stackexchange_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_candidates, f, indent=2, ensure_ascii=False)

    print(f"\nSelesai! Total {len(all_candidates)} kandidat unik disimpan ke {output_path}")