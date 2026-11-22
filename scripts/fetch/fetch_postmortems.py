import hashlib
import json
import re
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any

# Root directory proyek (naik 2 level dari ./scripts/fetch/fetch_postmortems.py)
ROOT_DIR = Path(__file__).resolve().parents[2]

DANLUU_README_URLS = [
    "https://raw.githubusercontent.com/danluu/post-mortems/master/README.md",
    "https://raw.githubusercontent.com/danluu/post-mortems/main/README.md",
]

# Format: (kata_kunci, kategori, severitas)
TARGET_INCIDENT_KEYWORDS = [
    ("gitlab", "database", "SEV1"),
    ("postgresql", "database", "SEV2"),
    ("postgres", "database", "SEV2"),
    ("mysql", "database", "SEV2"),
    ("redis", "database", "SEV2"),
    ("database", "database", "SEV1"),
    ("cloudflare", "network", "SEV1"),
    ("dns", "network", "SEV1"),
    ("bgp", "network", "SEV1"),
    ("nginx", "network", "SEV2"),
    ("load balancer", "network", "SEV1"),
    ("network", "network", "SEV2"),
    ("s3", "deployment", "SEV1"),
    ("kubernetes", "deployment", "SEV1"),
    ("deploy", "deployment", "SEV2"),
    ("github", "deployment", "SEV1"),
    ("aws", "resource", "SEV1"),
    ("memory", "resource", "SEV2"),
    ("disk", "resource", "SEV2"),
    ("capacity", "resource", "SEV2"),
]


def _get_text(urls: list[str]) -> str:
    last_err: Exception | None = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sre-triage-seeder/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            last_err = e
    raise RuntimeError(f"Gagal mengunduh README post-mortems: {last_err}")


def infer_mitigation_template(category: str, summary: str) -> str:
    """Menyediakan langkah mitigasi SRE standar yang relevan dengan pola insiden postmortem."""
    s_low = summary.lower()
    if category == "database":
        if any(k in s_low for k in ("replication", "failover", "delete", "corrupt")):
            return (
                "1. Hentikan proses automated failover atau skrip migrasi/replikasi yang bermasalah.\n"
                "2. Verifikasi integritas backup terbaru dan status replication lag antar node primary-replica.\n"
                "3. Lakukan point-in-time recovery (PITR) ke instance terisolasi sebelum promosi kembali ke produksi."
            )
        return (
            "1. Identifikasi query atau transaksi panjang yang menahan lock pada database utama.\n"
            "2. Terapkan pembatasan koneksi (connection pooling) dan turunkan beban tulis sementara.\n"
            "3. Evaluasi ulang indeks, autovacuum, atau batas kapasitas penyimpanan sebelum membuka penuh trafik."
        )
    if category == "network":
        return (
            "1. Isolasi perubahan konfigurasi routing, BGP, DNS, atau aturan reverse proxy terbaru (rollback segera).\n"
            "2. Alihkan trafik keluar dari edge/load balancer yang mengalami saturasi atau packet drop.\n"
            "3. Validasi kesehatan upstream dan TTL DNS sebelum memulihkan distribusi trafik normal."
        )
    if category == "resource":
        return (
            "1. Aktifkan rate limiting / circuit breaker untuk meredam lonjakan beban atau retry storm.\n"
            "2. Bebaskan resource kritis (disk space, memory, file descriptors) pada node terdampak.\n"
            "3. Lakukan scaling kapasitas cluster secara bertahap agar tidak memicu thundering herd."
        )
    return (
        "1. Hentikan rollout deployment yang sedang berjalan dan lakukan rollback ke rilis stabil terakhir.\n"
        "2. Cek konfigurasi environment, batas blast radius, serta health check pada orchestrator.\n"
        "3. Pulihkan layanan secara bertahap (canary) sambil memantau error rate dan latensi."
    )


def _extract_links_and_clean_text(line: str, ref_map: dict[str, str]) -> tuple[str, str]:
    """Mengekstrak URL pertama (inline, reference, atau HTML) dan membersihkan teks baris."""
    url = ""

    # 1. Cek inline markdown link: [text](https://...)
    inline_match = re.search(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", line)
    if inline_match:
        url = inline_match.group(2).strip()

    # 2. Cek reference markdown link: [text][ref_id] atau [ref_id][]
    if not url:
        ref_match = re.search(r"\[([^\]]+)\]\[([^\]]*)\]", line)
        if ref_match:
            ref_key = (ref_match.group(2) or ref_match.group(1)).strip().lower()
            url = ref_map.get(ref_key, "")

    # 3. Cek HTML anchor: <a href="https://...">text</a>
    if not url:
        html_match = re.search(r"<a[^>]+href=[\"'](https?://[^\"']+)[\"'][^>]*>", line, flags=re.IGNORECASE)
        if html_match:
            url = html_match.group(1).strip()

    # Bersihkan seluruh markup untuk menghasilkan deskripsi teks murni
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
    clean = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", clean)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"^\s*(?:[\*\-\+]|\d+\.)\s+", "", clean)
    clean = unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip(" .-\t")

    return url, clean


def parse_danluu_readme(md_text: str, max_items: int = 10) -> list[dict[str, Any]]:
    """Mem-parsing daftar postmortem dari README.md Dan Luu menjadi kandidat runbook."""
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    category_counts: dict[str, int] = {"database": 0, "network": 0, "deployment": 0, "resource": 0}
    max_per_category = max(2, (max_items + 3) // 4)

    # Kumpulkan definisi reference-style link di bagian bawah README ([id]: https://...)
    ref_map: dict[str, str] = {}
    for ref_id, ref_url in re.findall(r"^\s*\[([^\]]+)\]:\s*(https?://\S+)", md_text, flags=re.MULTILINE):
        ref_map[ref_id.strip().lower()] = ref_url.strip()

    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Abaikan baris definisi reference link itu sendiri
        if re.match(r"^\[[^\]]+\]:\s*https?://", stripped):
            continue

        url, clean_desc = _extract_links_and_clean_text(stripped, ref_map)
        if not url or len(clean_desc) < 18 or url in seen_urls:
            continue

        combined_low = clean_desc.lower()
        matched_meta = None
        for kw, cat, sev in TARGET_INCIDENT_KEYWORDS:
            if kw in combined_low and category_counts[cat] < max_per_category:
                matched_meta = (cat, sev)
                break

        if not matched_meta:
            continue

        category, severity = matched_meta
        seen_urls.add(url)
        category_counts[category] += 1

        short_subject = clean_desc.split(".")[0].strip()[:85]
        title = f"Postmortem Case: {short_subject}"

        # Sertakan sinyal insiden eksplisit agar kompatibel dengan filter INCIDENT_SIGNAL_PATTERN
        symptoms = (
            f"Incident Reference: {short_subject}\n"
            f"Summary: Major production service outage / downtime failure — {clean_desc}\n"
            f"Category: {category} | Impact Severity: {severity}"
        )
        mitigation = infer_mitigation_template(category, clean_desc)
        content_hash = hashlib.sha256(f"{title.lower()}::{symptoms.lower()}".encode("utf-8")).hexdigest()

        candidates.append({
            "title": title,
            "category": category,
            "severity": severity,
            "symptoms_log": symptoms[:950],
            "root_cause": clean_desc[:400],
            "resolution_steps": mitigation,
            "source_ref": url,
            "content_hash": content_hash,
        })

        if len(candidates) >= max_items:
            break

    return candidates


def fetch_postmortems(max_items: int = 10) -> list[dict[str, Any]]:
    print("Mengunduh kurasi postmortem Dan Luu...")
    readme_text = _get_text(DANLUU_README_URLS)
    items = parse_danluu_readme(readme_text, max_items=max_items)
    for item in items:
        print(f"  + [{item['severity']}/{item['category']}] {item['title']}")
    return items


if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Sesuai DATA_SOURCES.md: ambil 5-10 studi kasus insiden besar
    items = fetch_postmortems(max_items=10)

    output_path = data_dir / "raw_postmortems_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    print(f"\nSelesai! {len(items)} studi kasus postmortem disimpan ke {output_path}")