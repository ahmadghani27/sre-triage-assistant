import hashlib
import json
import os
import re
from html import unescape
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
FALLBACK_DATA_DIR = os.path.join(BASE_DIR, "scripts", "data")

INPUT_FILES = [
    "raw_prometheus_candidates.json",
    "raw_stackexchange_candidates.json",
]

OUTPUT_FILE = os.path.join(DATA_DIR, "seed_runbooks.json")

# Hanya saring alert meta/dummy atau pertanyaan konseptual murni tanpa troubleshooting insiden
NON_INCIDENT_TITLE_PATTERNS = [
    r"\bwatchdog\b",
    r"\binfoinhibitor\b",
    r"^why do i need\b",
    r"^why disable\b",
    r"^what is the purpose\b",
    r"^feasible to\b",
    r"^how to understand\b",
    r"\barchitecture$",
    r"^how do i list\b",
    r"^list all columns\b",
    r"^how to insert values into\b",
    r"^return http status code\b",
    r"^in flask, what is\b",
    r"^return a record with\b",
    r"^postgresql:\s*set-ing\b",
    r"^when installing docker\b",
    r"^how do i pass environment\b",
    r"^get environment variable\b",
    r"^arg or env\b",
    r"^how to remove an image tag\b",
    r"^is it possible to rerun\b",
    r"^rsync files to\b",
    r"^csrf protection with\b",
    r"without server_name and using only static ip",
]

INCIDENT_SIGNAL_PATTERN = re.compile(
    r"("
    r"\berror\w*\b|\berr\b|\bfail\w*\b|\bfatal\b|\bexception\b|\btraceback\b|"
    r"\btimeout\b|\btimed out\b|\brefused\b|\breset\b|\bdenied\b|\bblocked\b|\bforbidden\b|"
    r"\bstuck\b|\bdown\b|\bcrash\b|\brestarts?\b|\bslow\b|\blatency\b|"
    r"\bfull\b|\bno space\b|\benospc\b|\boom\b|\bout of memory\b|overcommit|throttl\w*|"
    r"\bdeadlock\b|\block\w*\b|\bdisconnect\w*\b|\bclosed unexpectedly\b|\bprematurely closed\b|"
    r"\bexpir\w*\b|\bnot found\b|\bnot working\b|\bdoesn't work\b|\bdoes not work\b|\bwon't\b|\bunable\b|\bcannot\b|\bcan't\b|"
    r"\bdebug\b|\bemerg\b|\bwarning\b|\bflapping\b|\bredirection cycle\b|\bkill\b|\bhang\b|"
    r"\b(401|403|404|405|408|429|444|500|502|503|504)\b"
    r")",
    flags=re.IGNORECASE,
)


def clean_markup(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"</?(details|summary|br|p|div|span|code|pre)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def classify_category(title: str, description: str, fallback: str) -> str:
    t_low = title.lower()
    full_low = f"{title} {description}".lower()

    # Prioritas pengecekan judul agar lebih akurat
    if any(k in t_low for k in [
        "cors", "cross-origin", "access-control-allow", "502", "connection refused",
        "connection reset", "iptables", "network", "flapping", "certificate", "redirection cycle"
    ]):
        return "network"
    if any(k in t_low for k in [
        "postgresql", "postgres", "mysql", "innodb", "pgbouncer", "pg_hba",
        "deadlock", "metadata lock", "alter table", "statement_timeout", "too many clients", "idle connections"
    ]):
        return "database"
    if any(k in t_low for k in [
        "cpu", "throttl", "overcommit", "memory", "no space left", "100% full", "xfs filesystem", "oom"
    ]):
        return "resource"
    if any(k in t_low for k in [
        "nginx", "docker", "dockerfile", "kubernetes", "kube", "container", "pod",
        "404", "500", "403", "template not found", "apidown", "controllermanagerdown",
        "targetdown", "errorbudgetburn", "environment variable", "tzdata", "timezone"
    ]):
        return "deployment"

    # Pengecekan full-text jika judul kurang spesifik
    if any(k in full_low for k in ["postgresql", "postgres", "mysql", "innodb", "pgbouncer", "deadlock", "metadata lock"]):
        return "database"
    if any(k in full_low for k in ["502", "504", "connection refused", "connection reset", "cors", "iptables", "network interface"]):
        return "network"
    if any(k in full_low for k in ["cpu", "throttl", "overcommit", "oom", "no space left", "inode", "xfs"]):
        return "resource"
    if any(k in full_low for k in ["docker", "kubernetes", "nginx", "flask", "404", "500"]):
        return "deployment"

    return fallback if fallback in {"network", "database", "deployment", "resource"} else "deployment"


def calibrate_severity(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    if any(k in text for k in [
        "apidown", "controllermanagerdown", "100% full", "no space left",
        "too many clients", "closed the connection unexpectedly", "oomkilled", "outage",
        "cluster isn't guaranteed", "non-functional"
    ]):
        return "SEV1"
    if any(k in text for k in [
        "502", "500", "503", "connection refused", "connection reset",
        "deadlock", "throttl", "overcommit", "errorbudgetburn", "containercreating",
        "waiting", "metadata lock", "certificate"
    ]):
        return "SEV2"
    if any(k in text for k in [
        "404", "403", "timeout", "slow", "disconnect", "cors", "flapping", "targetdown", "444"
    ]):
        return "SEV3"
    return "SEV4"


def extract_clean_root_cause(raw_rc: str, description: str, resolution: str) -> str:
    rc = clean_markup(raw_rc)
    # Tolak jika masih berupa placeholder TODO atau terlalu pendek
    if rc and not rc.upper().startswith("TODO") and len(rc) >= 20:
        return rc[:400]

    # Ambil kalimat penjelas pertama dari deskripsi atau resolusi yang bukan potongan kode/URL
    for source_text in (description, resolution):
        for line in source_text.splitlines():
            line_clean = line.strip(" -#*")
            if (
                len(line_clean) >= 25
                and not line_clean.lower().startswith(("alert:", "http", "select ", "insert ", "update ", "run ", "from ", "server ", "location ", "var ", "$.ajax"))
            ):
                return line_clean[:400]

    return "Gangguan konfigurasi, konektivitas, atau keterbatasan resource pada layanan."


def compute_hash(title: str, symptoms_log: str) -> str:
    raw = f"{title.strip().lower()}::{symptoms_log.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_valid_incident(title: str, description: str, raw_resolution: str) -> tuple[bool, str]:
    t_lower = title.strip().lower()
    res_clean = clean_markup(raw_resolution)

    if not res_clean or res_clean.upper().startswith("TODO") or len(res_clean) < 35:
        return False, "Solusi kosong / masih TODO"

    for pat in NON_INCIDENT_TITLE_PATTERNS:
        if re.search(pat, t_lower):
            return False, f"Topik non-insiden ({pat})"

    # Normalisasi tanda baca sebelum cek regex sinyal insiden (misal "404's" -> "404 s")
    searchable = re.sub(r"[^\w\s]", " ", f"{title} {description}")
    if not INCIDENT_SIGNAL_PATTERN.search(searchable):
        return False, "Tidak mengandung gejala error/insiden"

    return True, "OK"


def normalize_prometheus(record: dict[str, Any]) -> dict[str, Any] | None:
    title = record.get("title", "").strip()
    description = clean_markup(record.get("symptoms_log", ""))
    raw_resolution = record.get("resolution_steps", "")
    raw_root_cause = record.get("root_cause", "")

    ok, _ = is_valid_incident(title, description, raw_resolution)
    if not ok:
        return None

    symptoms_log = f"{title}\n{description}" if description else title
    resolution_steps = clean_markup(raw_resolution)
    root_cause = extract_clean_root_cause(raw_root_cause, description, resolution_steps)

    # Selalu klasifikasi ulang agar tidak terjebak default "resource" / "SEV2" dari scraper
    category = classify_category(title, description, record.get("category", "deployment"))
    severity = calibrate_severity(title, description)

    return {
        "title": title,
        "category": category,
        "severity": severity,
        "symptoms_log": symptoms_log,
        "root_cause": root_cause,
        "resolution_steps": resolution_steps,
        "source_ref": record.get("source_ref", "prometheus-operator"),
        "content_hash": compute_hash(title, symptoms_log),
    }


def normalize_stackexchange(record: dict[str, Any]) -> dict[str, Any] | None:
    title = record.get("title", "").strip()
    description = clean_markup(record.get("description", ""))
    raw_resolution = record.get("resolution", "")
    raw_root_cause = record.get("root_cause", "")

    ok, _ = is_valid_incident(title, description, raw_resolution)
    if not ok:
        return None

    meta = []
    if record.get("error_code"):
        meta.append(f"Error code: {record['error_code']}")
    if record.get("location"):
        meta.append(f"Location: {record['location']}")

    symptoms_log = f"{title}\n{description}"
    if meta:
        symptoms_log += f"\n{' | '.join(meta)}"

    resolution_steps = clean_markup(raw_resolution)
    root_cause = extract_clean_root_cause(raw_root_cause, description, resolution_steps)

    category = classify_category(title, description, record.get("category", "deployment"))
    severity = calibrate_severity(title, description)

    return {
        "title": title,
        "category": category,
        "severity": severity,
        "symptoms_log": symptoms_log,
        "root_cause": root_cause,
        "resolution_steps": resolution_steps,
        "source_ref": record.get("source_url", "stackexchange"),
        "content_hash": compute_hash(title, symptoms_log),
    }


def load_json(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [data] if isinstance(data, dict) else data


def resolve_input_path(fname: str) -> str | None:
    for directory in (DATA_DIR, FALLBACK_DATA_DIR):
        candidate = os.path.join(directory, fname)
        if os.path.exists(candidate):
            return candidate
    return None


def normalize_all() -> list[dict[str, Any]]:
    os.makedirs(DATA_DIR, exist_ok=True)
    normalized: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    stats: dict[str, dict[str, int]] = {}
    cat_counts: dict[str, int] = {"network": 0, "database": 0, "deployment": 0, "resource": 0}
    sev_counts: dict[str, int] = {"SEV1": 0, "SEV2": 0, "SEV3": 0, "SEV4": 0}

    for fname in INPUT_FILES:
        path = resolve_input_path(fname)
        if not path:
            print(f"[skip] {fname} tidak ditemukan di {DATA_DIR} maupun {FALLBACK_DATA_DIR}")
            continue

        records = load_json(path)
        accepted = 0
        rejected = 0
        for record in records:
            is_prom = "Alert:" in str(record.get("title", "")) or "symptoms_log" in record
            item = normalize_prometheus(record) if is_prom else normalize_stackexchange(record)

            if item is None or item["content_hash"] in seen_hashes:
                rejected += 1
                continue

            seen_hashes.add(item["content_hash"])
            normalized.append(item)
            accepted += 1
            cat_counts[item["category"]] = cat_counts.get(item["category"], 0) + 1
            sev_counts[item["severity"]] = sev_counts.get(item["severity"], 0) + 1

        stats[fname] = {"accepted": accepted, "rejected": rejected, "total": len(records)}

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)

    print("=== Hasil Normalisasi ===")
    for fname, s in stats.items():
        print(f"{fname}: diterima={s['accepted']}, ditolak={s['rejected']}, total={s['total']}")
    print(f"Distribusi Kategori : {cat_counts}")
    print(f"Distribusi Severitas: {sev_counts}")
    print(f"Output: {OUTPUT_FILE} ({len(normalized)} runbook)")
    return normalized


def main() -> None:
    normalize_all()


if __name__ == "__main__":
    main()