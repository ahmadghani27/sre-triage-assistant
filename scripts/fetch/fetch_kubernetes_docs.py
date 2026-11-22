import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

# Root directory proyek (naik 2 level dari ./scripts/fetch/fetch_kubernetes_docs.py)
ROOT_DIR = Path(__file__).resolve().parents[2]

K8S_DEBUG_API_ROOT = "https://api.github.com/repos/kubernetes/website/contents/content/en/docs/tasks/debug"

# Heading boilerplate dokumentasi tutorial Kubernetes yang bukan langkah troubleshooting
IGNORED_HEADINGS = {
    "prerequisites",
    "before you begin",
    "whatsnext",
    "what's next",
    "objectives",
    "cleanup",
    "clean up",
    "feedback",
    "see also",
}


def _get_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sre-triage-seeder/1.0",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "sre-triage-seeder/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def list_debug_markdown_files(api_url: str) -> list[dict[str, str]]:
    """Menelusuri direktori content/en/docs/tasks/debug secara rekursif."""
    entries = _get_json(api_url)
    md_files: list[dict[str, str]] = []

    if not isinstance(entries, list):
        return md_files

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        name = entry.get("name", "")

        if entry_type == "dir":
            time.sleep(0.2)
            md_files.extend(list_debug_markdown_files(entry["url"]))
        elif entry_type == "file" and name.endswith(".md") and name != "_index.md":
            md_files.append({
                "name": name,
                "path": entry["path"],
                "download_url": entry["download_url"],
            })

    return md_files


def _clean_hugo_markdown(md_text: str) -> tuple[str, str]:
    """Memisahkan frontmatter title dan membersihkan Hugo shortcodes."""
    doc_title = ""
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", md_text, flags=re.DOTALL)
    if fm_match:
        title_match = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", fm_match.group(1), flags=re.MULTILINE)
        if title_match:
            doc_title = title_match.group(1).strip()
        body = md_text[fm_match.end():]
    else:
        body = md_text

    # Ubah {{% heading "prerequisites" %}} menjadi teks biasa agar bisa difilter
    body = re.sub(r"\{\{[<%]\s*heading\s+\"([^\"]+)\"\s*[>%]\}\}", r"\1", body)
    # Hapus komentar HTML dan shortcode Hugo lainnya ({{< note >}}, {{< codenew >}}, dll.)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    body = re.sub(r"\{\{[<%].*?[>%]\}\}", "", body, flags=re.DOTALL)
    # Rapikan spasi berlebih
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return doc_title, body


def _classify_k8s_topic(text: str) -> str:
    """Menentukan kategori domain (resource, network, atau deployment)."""
    low = text.lower()
    if any(k in low for k in ("oom", "memory", "cpu", "resource", "ephemeral-storage", "disk", "evict", "quota", "pressure")):
        return "resource"
    if any(k in low for k in ("service", "dns", "coredns", "kube-proxy", "endpoint", "network", "ingress", "port-forward")):
        return "network"
    return "deployment"


def _infer_k8s_severity(text: str) -> str:
    """Menentukan tingkat keparahan awal untuk kasus Kubernetes."""
    low = text.lower()
    if any(k in low for k in ("oomkilled", "notready", "node failure", "apiserver", "data loss")):
        return "SEV1"
    if any(k in low for k in ("crashloopbackoff", "imagepullbackoff", "errimagepull", "pending", "evict", "failed", "error")):
        return "SEV2"
    return "SEV3"


def _build_source_url(repo_path: str) -> str:
    """Mengubah path repo content/en/docs/tasks/debug/x.md menjadi URL resmi kubernetes.io."""
    rel = repo_path.replace("content/en/", "").removesuffix(".md")
    return f"https://kubernetes.io/{rel}/"


def _extract_root_cause(text: str, fallback_topic: str) -> str:
    """Mengambil kalimat penjelas pertama yang bukan perintah CLI atau blok kode."""
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for line in cleaned.splitlines():
        s = line.strip(" -#*>`")
        if (
            len(s) >= 25
            and not s.startswith(("kubectl ", "crictl ", "$", "http", "{", "["))
            and not s.endswith(":")
        ):
            return s[:400]
    return f"Kegagalan konfigurasi, resource, atau runtime pada komponen Kubernetes ({fallback_topic})."


def parse_k8s_debug_markdown(md_text: str, repo_path: str) -> list[dict[str, Any]]:
    """Memecah dokumen Kubernetes Debug menjadi 1 atau beberapa runbook terfokus."""
    doc_title, clean_body = _clean_hugo_markdown(md_text)
    if not doc_title:
        doc_title = Path(repo_path).stem.replace("-", " ").title()

    source_url = _build_source_url(repo_path)

    # Pisahkan intro sebelum heading ## pertama dan daftar section ##
    parts = re.split(r"^##\s+(.+)$", clean_body, flags=re.MULTILINE)
    intro_text = parts[0].strip()

    valid_sections: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        sec_heading = re.sub(r"[`\*\#]", "", parts[i]).strip()
        sec_body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if sec_heading.lower() in IGNORED_HEADINGS:
            continue
        if len(sec_body) >= 180:
            valid_sections.append((sec_heading, sec_body))

    results: list[dict[str, Any]] = []

    # Jika dokumen berisi banyak skenario troubleshooting (mis. CrashLoopBackOff, ImagePullBackOff), pecah per section
    if len(valid_sections) >= 2:
        for sec_heading, sec_body in valid_sections:
            title = f"Kubernetes Debug: {doc_title} — {sec_heading}"
            combined = f"{title} {sec_body}"
            category = _classify_k8s_topic(combined)
            severity = _infer_k8s_severity(combined)

            # Ambil 2 paragraf awal section sebagai gejala/konteks, sisanya sebagai langkah diagnosis/mitigasi
            sec_paras = [p.strip() for p in sec_body.split("\n\n") if p.strip()]
            symptom_desc = "\n\n".join(sec_paras[:2])[:650]
            symptoms_log = (
                f"Kubernetes Pod/Cluster Debugging & Failure Diagnosis: {sec_heading}\n"
                f"Context: {doc_title}\n"
                f"{symptom_desc}"
            ).strip()[:950]

            root_cause = _extract_root_cause(sec_body, sec_heading)
            resolution_steps = sec_body[:1500]
            content_hash = hashlib.sha256(f"{title.lower()}::{symptoms_log.lower()}".encode("utf-8")).hexdigest()

            results.append({
                "title": title,
                "category": category,
                "severity": severity,
                "symptoms_log": symptoms_log,
                "root_cause": root_cause,
                "resolution_steps": resolution_steps,
                "source_ref": source_url,
                "content_hash": content_hash,
            })
    else:
        # Gunakan keseluruhan dokumen sebagai 1 runbook utuh
        merged_body = "\n\n".join([intro_text] + [f"## {h}\n{b}" for h, b in valid_sections]).strip()
        if len(merged_body) < 120:
            return []

        title = f"Kubernetes Debug: {doc_title}"
        combined = f"{title} {merged_body}"
        category = _classify_k8s_topic(combined)
        severity = _infer_k8s_severity(combined)

        symptom_desc = intro_text[:650] if len(intro_text) >= 40 else merged_body[:650]
        symptoms_log = (
            f"Kubernetes Pod/Cluster Debugging & Failure Diagnosis: {doc_title}\n"
            f"{symptom_desc}"
        ).strip()[:950]

        root_cause = _extract_root_cause(merged_body, doc_title)
        resolution_steps = merged_body[:1500]
        content_hash = hashlib.sha256(f"{title.lower()}::{symptoms_log.lower()}".encode("utf-8")).hexdigest()

        results.append({
            "title": title,
            "category": category,
            "severity": severity,
            "symptoms_log": symptoms_log,
            "root_cause": root_cause,
            "resolution_steps": resolution_steps,
            "source_ref": source_url,
            "content_hash": content_hash,
        })

    return results


def fetch_kubernetes_debug_docs() -> list[dict[str, Any]]:
    print(f"Memindai file dokumentasi di: {K8S_DEBUG_API_ROOT}...")
    md_files = list_debug_markdown_files(K8S_DEBUG_API_ROOT)
    print(f"Ditemukan {len(md_files)} file Markdown Kubernetes Debug.\n")

    all_candidates: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    cat_counts: dict[str, int] = {"deployment": 0, "resource": 0, "network": 0, "database": 0}

    for f_info in md_files:
        try:
            raw_md = _get_text(f_info["download_url"])
            parsed_items = parse_k8s_debug_markdown(raw_md, f_info["path"])
            for item in parsed_items:
                if item["content_hash"] in seen_hashes:
                    continue
                seen_hashes.add(item["content_hash"])
                all_candidates.append(item)
                cat_counts[item["category"]] = cat_counts.get(item["category"], 0) + 1
                print(f"  + [{item['severity']}/{item['category']}] {item['title']}")
            time.sleep(0.25)
        except Exception as e:
            print(f"  ! Gagal memproses {f_info['path']}: {e}")

    print(f"\nDistribusi kategori tertarik: {cat_counts}")
    return all_candidates


if __name__ == "__main__":
    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    items = fetch_kubernetes_debug_docs()

    output_path = data_dir / "raw_kubernetes_candidates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

    print(f"Selesai! {len(items)} runbook Kubernetes Debug disimpan ke {output_path}")