# **Data Sources & Knowledge Base Strategy (`DATA_SOURCES.md`)**

## 1. Strategi Akuisisi Data (Architectural Rule)
Untuk menjaga latensi aplikasi tetap rendah, mencegah kegagalan akibat *rate limit* pihak ketiga, dan menjamin kebersihan indeks **SQLite FTS5**, seluruh sumber data di bawah ini diproses secara **Offline Batch Ingestion** (satu kali saat fase *seeding* ke `data/seed_runbooks.json`), **bukan** melalui *live sync* saat pengguna melakukan triase.

---

## 2. Sumber Knowledge Base (Pre-Seeded Runbooks & Troubleshooting)
Digunakan sebagai korpus utama yang diindeks ke dalam database SQLite untuk pencarian *Hybrid Search* (FTS5 + LLM Re-ranking).

| Sumber Data | URL Referensi | Domain Kategori | Cara Penggunaan |
| :--- | :--- | :--- | :--- |
| **Prometheus Operator Runbooks** | `https://runbooks.prometheus-operator.dev` | `resource`, `network`, `deployment` | Ekstraksi pola *alert*, dampak sistem, dan langkah mitigasi standar Kubernetes/Prometheus. |
| **GitLab Production Runbooks** | `https://gitlab.com/gitlab-com/runbooks` | `database`, `network`, `deployment` | Referensi prosedur pemulihan layanan skala produksi (*high-availability troubleshooting*). |
| **Kubernetes Debugging Docs** | `https://kubernetes.io/docs/tasks/debug/` | `deployment`, `resource` | Rujukan diagnosis kegagalan *Pod* (`CrashLoopBackOff`, `OOMKilled`, `ImagePullBackOff`). |
| **PostgreSQL Documentation** | `https://www.postgresql.org/docs/` | `database` | Rujukan kode error SQLSTATE, *connection pool exhaustion*, dan *deadlock*. |
| **Nginx Documentation** | `https://nginx.org/en/docs/` | `network` | Rujukan error *reverse proxy* (`502 Bad Gateway`, `504 Gateway Timeout`, *upstream reset*). |
| **Docker Engine Docs** | `https://docs.docker.com/engine/` | `deployment`, `resource` | Rujukan masalah *container runtime*, jaringan *bridge*, dan *disk space exhaustion*. |

---

## 3. Sumber Data Uji (Input Evaluation & Test Suite)
Digunakan untuk menguji ketahanan *Regex Redaction* (F1), sanitasi karakter kueri FTS5 (F3), dan akurasi klasifikasi LLM (F2).

| Sumber Data | URL Referensi | Peran dalam Pengujian |
| :--- | :--- | :--- |
| **Loghub (PAI Lab)** | `https://github.com/logpai/loghub` | Menyediakan sampel *raw system logs* nyata (Linux, Apache, Nginx, OpenStack) untuk menguji pemrosesan log panjang dan *stack trace* mentah. |

---

## 4. Sumber Kurasi Kasus & Postmortem (Offline Enrichment)
Digunakan pada skrip *seeding* terpisah (`scripts/fetch_external.py`) untuk memperkaya variasi skenario dunia nyata sebelum dikurasi ke format JSON.

| Sumber Data | URL Referensi | Catatan Implementasi & Batasan |
| :--- | :--- | :--- |
| **Kurasi Postmortems (Dan Luu)** | `https://github.com/danluu/post-mortems` | Diambil 5–10 studi kasus insiden besar untuk memperkaya variasi skenario `SEV1` dan `SEV2`. |
| **Stack Exchange API** (`serverfault`, `dba`, `stackoverflow`) | `https://api.stackexchange.com/docs` | **Hanya untuk Offline Seeding.** Menggunakan filter `accepted=True` dan `min_score=10` agar hanya mengambil solusi tervalidasi. Memerlukan API Key dari `stackapps.com`. |
| **GitHub REST API (Issues)** | `https://docs.github.com/en/rest/issues` | **Ditunda ke v0.2 (Post-MVP).** Hanya menarik isu dengan parameter `state=closed&labels=bug` dan wajib melalui tahap ringkasan LLM karena format komentar tidak terstruktur. |

---

## 5. Rujukan Konseptual & Lisensi (Non-Scraped)
* **Google SRE Book (`https://sre.google/sre-book/table-of-contents/`):** Digunakan sebagai pedoman penyusunan *System Prompt* untuk definisi tingkat severitas (`SEV1`–`SEV4`) dan prinsip triase insiden. Tidak di-*scrape* ke dalam database.
* **Stack Exchange Data Dump (`https://archive.org/details/stackexchange`):** Dicatat sebagai referensi sumber data terbuka (lisensi `CC BY-SA`), namun **tidak diunduh** karena ukuran berkas tidak efisien untuk skala MVP.