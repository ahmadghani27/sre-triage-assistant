import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

# Tentukan root directory proyek (naik 2 level dari ./scripts/fetch/fetch_prometheus_runbooks.py)
ROOT_DIR = Path(__file__).resolve().parents[2]

GITHUB_API_DIRS = [
    ("kubernetes", "https://api.github.com/repos/prometheus-operator/runbooks/contents/content/runbooks/kubernetes"),
    ("general", "https://api.github.com/repos/prometheus-operator/runbooks/contents/content/runbooks/general"),
    ("etcd", "https://api.github.com/repos/prometheus-operator/runbooks/contents/content/runbooks/etcd"),
    ("node-exporter", "https://api.github.com/repos/prometheus-operator/runbooks/contents/content/runbooks/node-exporter"),
    ("prometheus", "https://api.github.com/repos/prometheus-operator/runbooks/contents/content/runbooks/prometheus"),
    ("alertmanager", "https://api.github.com/repos/prometheus-operator/runbooks/contents/content/runbooks/alertmanager"),
]


def _get_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sre-triage-seeder/1.0",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "sre-triage-seeder/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


def parse_prometheus_markdown(md_text: str, filename: str, folder_name: str) -> dict[str, Any]:
    """Memecah file Markdown Prometheus Runbook menjadi struktur kandidat."""
    # Hapus frontmatter YAML (--- ... ---) di bagian atas file Hugo/Markdown
    clean_md = re.sub(r"^---.*?---\s*", "", md_text, flags=re.DOTALL).strip()

    # Ekstrak bagian Meaning, Impact, dan Mitigation (mendukung heading ## maupun ###)
    meaning_match = re.search(r"#{2,3}\s*Meaning\s*(.*?)(?=\n#{2,3}\s|\Z)", clean_md, flags=re.DOTALL | re.IGNORECASE)
    impact_match = re.search(r"#{2,3}\s*Impact\s*(.*?)(?=\n#{2,3}\s|\Z)", clean_md, flags=re.DOTALL | re.IGNORECASE)
    mitigation_match = re.search(r"#{2,3}\s*Mitigation\s*(.*?)(?=\n#{2,3}\s|\Z)", clean_md, flags=re.DOTALL | re.IGNORECASE)

    alert_name = filename.replace(".md", "")
    meaning_text = meaning_match.group(1).strip() if meaning_match else ""
    impact_text = impact_match.group(1).strip() if impact_match else ""
    mitigation_text = mitigation_match.group(1).strip() if mitigation_match else clean_md[:1200]

    # Jika Meaning kosong, ambil paragraf awal non-heading sebagai fallback gejala
    if not meaning_text:
        paras = [p.strip() for p in clean_md.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        meaning_text = paras[0] if paras else ""

    symptoms = f"Alert: {alert_name}\n{meaning_text}\n{impact_text}".strip()

    return {
        "title": f"Prometheus Alert: {alert_name}",
        "category": "resource",  # Akan diklasifikasi ulang oleh normalize_runbooks.py
        "severity": "SEV2",
        "symptoms_log": symptoms[:950],
        "root_cause": meaning_text[:500] if meaning_text else "TODO: Ringkas dari Meaning.",
        "resolution_steps": mitigation_text[:1500],
        "source_ref": f"https://runbooks.prometheus-operator.dev/runbooks/{folder_name}/{alert_name.lower()}",
    }


def fetch_prometheus_runbooks(limit_per_dir: int | None = 40) -> list[dict[str, Any]]:
    candidates = []

    for folder_name, dir_url in GITHUB_API_DIRS:
        print(f"Membaca daftar file dari [{folder_name}]: {dir_url}...")
        try:
            files = _get_json(dir_url)
        except Exception as e:
            print(f"  ! Gagal mengakses direktori {folder_name}: {e}")
            continue

        md_files = [
            f for f in files
            if isinstance(f, dict) and f.get("name", "").endswith(".md") and f.get("name") != "_index.md"
        ]
        target_files = md_files[:limit_per_dir] if limit_per_dir else md_files

        for file_info in target_files:
            raw_url = file_info.get("download_url")
            if not raw_url:
                continue

            try:
                md_content = _get_text(raw_url)
                item = parse_prometheus_markdown(
                    md_text=md_content,
                    filename=file_info["name"],
                    folder_name=folder_name,
                )
                candidates.append(item)
                print(f"  + Berhasil tarik: {item['title']}")
                time.sleep(0.3)
            except Exception as e:
                print(f"  ! Gagal unduh {file_info['name']}: {e}")

    return candidates


if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Set limit_per_dir=None jika ingin menarik seluruh runbook yang tersedia di 6 folder
    items = fetch_prometheus_runbooks(limit_per_dir=40)

    output_path = data_dir / "raw_prometheus_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    print(f"\nSelesai! {len(items)} runbook Prometheus disimpan ke {output_path}")