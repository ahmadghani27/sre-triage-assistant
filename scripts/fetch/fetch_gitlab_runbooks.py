import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Root directory proyek (naik 2 level dari ./scripts/fetch/fetch_gitlab_runbooks.py)
ROOT_DIR = Path(__file__).resolve().parents[2]

GITLAB_PROJECT_ID = "gitlab-com%2Frunbooks"
GITLAB_TREE_API = f"https://gitlab.com/api/v4/projects/{GITLAB_PROJECT_ID}/repository/tree"
GITLAB_RAW_API = f"https://gitlab.com/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files"

# Langsung targetkan folder layanan utama agar tidak terpotong urutan alfabetis
TARGET_SUBDIRS: list[tuple[str, str]] = [
    # --- DATABASE ---
    ("docs/patroni", "database"),
    ("docs/pgbouncer", "database"),
    ("docs/postgresql", "database"),
    ("docs/database", "database"),
    ("docs/redis", "database"),
    ("docs/praefect", "database"),
    # --- NETWORK ---
    ("docs/haproxy", "network"),
    ("docs/cloudflare", "network"),
    ("docs/frontend", "network"),
    ("docs/dns", "network"),
    ("docs/nginx", "network"),
    ("docs/rate-limiting", "network"),
    # --- DEPLOYMENT ---
    ("docs/kube", "deployment"),
    ("docs/sidekiq", "deployment"),
    ("docs/gitaly", "deployment"),
    ("docs/registry", "deployment"),
    ("docs/ci-runners", "deployment"),
    ("docs/web", "deployment"),
    # --- RESOURCE ---
    ("docs/monitoring", "resource"),
    ("docs/alerts", "resource"),
    ("docs/uncategorized", "resource"),
]

EXCLUDED_FILENAMES = {
    "readme.md",
    "index.md",
    "_index.md",
    "architecture.md",
    "onboarding.md",
    "contributing.md",
    "style-guide.md",
}


def _get_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sre-triage-seeder/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_raw_markdown(file_path: str, ref: str = "master") -> str:
    encoded_path = urllib.parse.quote(file_path, safe="")
    url = f"{GITLAB_RAW_API}/{encoded_path}/raw?ref={ref}"
    req = urllib.request.Request(url, headers={"User-Agent": "sre-triage-seeder/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_section(md_text: str, heading_keywords: tuple[str, ...]) -> str:
    """Mengekstrak isi di bawah heading Markdown (## atau ###) yang cocok dengan kata kunci."""
    pattern = re.compile(
        r"^(#{2,3})\s+([^\n]+)\n(.*?)(?=\n#{2,3}\s+|\Z)",
        flags=re.DOTALL | re.MULTILINE,
    )
    collected: list[str] = []
    for _, heading_title, body in pattern.findall(md_text):
        h_low = heading_title.strip().lower()
        if any(kw in h_low for kw in heading_keywords):
            cleaned_body = body.strip()
            if cleaned_body:
                collected.append(f"{heading_title.strip()}:\n{cleaned_body}")
    return "\n\n".join(collected).strip()


def parse_gitlab_runbook(md_text: str, file_path: str, category: str) -> dict[str, Any] | None:
    """Mem-parsing file Markdown runbook GitLab menjadi kandidat terstruktur."""
    clean_md = re.sub(r"^---.*?---\s*", "", md_text, flags=re.DOTALL).strip()
    if len(clean_md) < 120:
        return None

    h1_match = re.search(r"^#\s+(.+)$", clean_md, flags=re.MULTILINE)
    raw_title = (
        h1_match.group(1).strip()
        if h1_match
        else Path(file_path).stem.replace("-", " ").replace("_", " ").title()
    )
    raw_title = re.sub(r"[`\*\#]", "", raw_title).strip()

    service_group = Path(file_path).parent.name.replace("-", " ").title()
    title = f"GitLab Runbook ({service_group}): {raw_title}"

    symptoms_sec = _extract_section(
        clean_md,
        ("symptom", "overview", "summary", "problem", "impact", "alert", "context", "description"),
    )
    mitigation_sec = _extract_section(
        clean_md,
        ("mitigat", "resolut", "remediat", "troubleshoot", "diagnos", "debug", "action", "recover", "fix", "check"),
    )

    paragraphs = [
        p.strip()
        for p in re.split(r"\n{2,}", clean_md)
        if p.strip() and not p.strip().startswith(("#", "[[_TOC_]]", "<!--"))
    ]

    if not symptoms_sec:
        symptoms_sec = "\n\n".join(paragraphs[:2])[:700]

    if not mitigation_sec:
        mitigation_sec = "\n\n".join(paragraphs[1:5])[:1300]

    if len(mitigation_sec) < 45:
        return None

    # Sertakan frasa sinyal insiden agar lolos validasi normalize_runbooks.py
    symptoms_log = (
        f"Service Component: {service_group}\n"
        f"Incident Troubleshooting & Failure Recovery: {raw_title}\n"
        f"{symptoms_sec}"
    ).strip()[:950]

    first_line = next(
        (
            line.strip(" -#*")
            for line in symptoms_sec.splitlines()
            if len(line.strip(" -#*")) >= 25 and not line.strip().startswith("```")
        ),
        f"Gangguan operasional atau saturasi pada layanan {service_group}.",
    )

    source_ref = f"[https://gitlab.com/gitlab-com/runbooks/-/blob/master/](https://gitlab.com/gitlab-com/runbooks/-/blob/master/){file_path}"
    content_hash = hashlib.sha256(f"{title.lower()}::{symptoms_log.lower()}".encode("utf-8")).hexdigest()

    return {
        "title": title,
        "category": category,
        "severity": "SEV2",
        "symptoms_log": symptoms_log,
        "root_cause": first_line[:400],
        "resolution_steps": mitigation_sec[:1500],
        "source_ref": source_ref,
        "content_hash": content_hash,
    }


def fetch_gitlab_runbooks(max_per_category: int = 15) -> list[dict[str, Any]]:
    """Mengambil runbook dari subdirektori layanan utama gitlab-com/runbooks."""
    candidates: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    cat_counts: dict[str, int] = {"database": 0, "network": 0, "deployment": 0, "resource": 0}

    for subdir, category in TARGET_SUBDIRS:
        if cat_counts[category] >= max_per_category:
            continue

        params = urllib.parse.urlencode({
            "path": subdir,
            "recursive": "true",
            "per_page": 100,
        })
        try:
            entries = _get_json(f"{GITLAB_TREE_API}?{params}")
        except Exception as e:
            print(f"  ! Lewati {subdir}: {e}")
            continue

        if not isinstance(entries, list) or not entries:
            continue

        md_paths = [
            e["path"]
            for e in entries
            if e.get("type") == "blob"
            and e.get("path", "").lower().endswith(".md")
            and Path(e["path"].lower()).name not in EXCLUDED_FILENAMES
        ]

        # Untuk folder resource yang luas, prioritaskan file terkait saturasi/disk/memory/cpu/oom
        if category == "resource" and subdir in ("docs/alerts", "docs/uncategorized"):
            md_paths = [
                p for p in md_paths
                if any(k in p.lower() for k in ("saturation", "disk", "memory", "cpu", "oom", "inode", "space", "quota"))
            ]

        print(f"Memindai {subdir} [{category}] -> ditemukan {len(md_paths)} file kandidat...")

        for file_path in md_paths:
            if cat_counts[category] >= max_per_category:
                break
            if file_path in seen_paths:
                continue
            seen_paths.add(file_path)

            try:
                md_content = _get_raw_markdown(file_path)
                item = parse_gitlab_runbook(md_content, file_path, category)
                if item:
                    candidates.append(item)
                    cat_counts[category] += 1
                    print(f"  + [{category}] {item['title']}")
                time.sleep(0.25)
            except Exception as e:
                print(f"  ! Gagal unduh {file_path}: {e}")

    print(f"\nDistribusi kategori tertarik: {cat_counts}")
    return candidates


if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Target 15 runbook per kategori (total maksimal ~60 runbook)
    items = fetch_gitlab_runbooks(max_per_category=15)

    output_path = data_dir / "raw_gitlab_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    print(f"Selesai! {len(items)} runbook GitLab disimpan ke {output_path}")