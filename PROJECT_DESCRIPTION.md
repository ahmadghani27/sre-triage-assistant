# SRE Triage Assistant — Deskripsi Proyek

Singkatnya: aplikasi Flask untuk mengklasifikasi log insiden SRE, mencocokkan runbook relevan, dan membantu mitigasi via chat berbasis runbook. Semua log di-redact sebelum disimpan atau dikirim ke LLM. Tersedia mode degradation ketika LLM mati.

## 1. Tech Stack

| Komponen | Teknologi |
|---|---|
| Backend / web framework | Flask 3.x (Application Factory + Blueprints) |
| Form & CSRF | Flask-WTF |
| Validasi data | pydantic |
| Env config | python-dotenv |
| LLM provider 1 | google-genai (Gemini, native) |
| LLM provider 2 | openai (OpenAI-compatible, custom base URL) |
| Database | SQLite (`data/app.db`) + FTS5 (porter unicode61) |
| Templating | Jinja2 + HTMX (partial HTML, OOB swap) |
| Pengolahan data | Python stdlib saja (json, re, sqlite3, hashlib, urllib) |
| Dev command | `flask --app "app:create_app()" --debug run` |

## 2. Alur Pengolahan Data

### A. Inisialisasi knowledge base (sekali / berkala)

1. **Scrap** — lima skrip di `scripts/fetch/` ambil sumber publik:
   - `fetch_gitlab_runbooks.py` → GitLab `gitlab-com/runbooks`
   - `fetch_kubernetes_docs.py` → Kubernetes website (`tasks/debug`)
   - `fetch_postmortems.py` → Dan Luu post-mortems
   - `fetch_prometheus_runbooks.py` → Prometheus Operator runbooks
   - `fetch_stackexchange.py` → Stack Exchange API (ServerFault/StackOverflow/DBA)
   Hasil: `data/raw_*_candidates.json`.

2. **Filtering & normalisasi** — `scripts/processing/normalize_runbooks.py`:
   - Bersihkan markup HTML/Markdown (`clean_markup`).
   - Buang topik non-insiden (pertanyaan konseptual, watchdog, dll.).
   - Terima hanya yang mengandung sinyal insiden (error, fail, timeout, OOM, HTTP 5xx, dll.).
   - Klasifikasi kategori (`network`, `database`, `deployment`, `resource`) dan severity (`SEV1`–`SEV4`) secara aturan.
   - Hitung `content_hash` (SHA-256 dari title + symptoms) untuk anti-duplikasi lintas batch.
   Hasil: `data/seed_runbooks.json`.

3. **Masukkan ke DB** — `scripts/seed.py`:
   - Buat schema (`data/schema.sql`) jika belum ada.
   - `INSERT OR IGNORE` ke tabel `runbooks` berdasarkan `content_hash`.
   - Rebuild indeks FTS5 jika tidak sinkron.
   Data akhir tersimpan di `data/app.db`.

### B. Alur runtime (tiada user mengajukan triase)

1. Menerima log mentah via form (`/triage`).
2. **Redaksi** (`redactor.py`): sensor bearer token, URI DB, API key, email, IPv4, dll. → `sanitized_log`. Ini wajib sebelum disimpan, dicari, atau dikirim ke LLM.
3. **Stage 1 — Lexical retrieval** (`SearchService.lexical_search`): FTS5 BM25 Top-10 dengan tokenisasi aman. Jika nol hasil, coba ulang dengan token yang dilonggarkan (camelCase/snake_case dipisah). Masih nol → ambil runbook terbaru sebagai fallback deterministik.
4. **Stage 2 — Klasifikasi + re-ranking** (`SearchService.classify_and_rerank`): LLM diberi kandidat + log, mengembalikan verdict JSON (category, severity, reasoning, ranked_runbook_ids max 3).
5. **Persistensi** (`LogRepository.save`): simpan ke `triage_logs` (query sudah di-sanitasi, redaction_count, category, severity, ID runbook, flag fallback).
6. **Render**: kirim Top-3 runbook + workspace state ke frontend via HTMX partial (satu respons, OOB swap).

Refine (`/triage/refine`) menggabungkan log awal + catatan baru, lalu menjalankan ulang pipeline di atas.

## 3. Fitur & Implementasi

| Fitur | Pakai apa | Implementasi |
|---|---|---|
| Triase insiden | Flask (request/response), `TriageService` (orchestration) | `app/services/triage_service.py`; HTTP layer di `app/blueprints/triage.py` (`POST /triage`, `POST /triage/refine`). |
| Redaksi PII/rahasia | Python `re` (regex terkompilasi) | `app/services/redactor.py` — sensor bearer token, URI DB, API key, email, IPv4; prefix dipertahankan untuk bearer/URI. |
| Pencarian runbook | SQLite FTS5 (porter unicode61, BM25) | `app/repositories/runbook_repo.py` (`search_top`, `get_by_ids`, `get_any`, `build_fts_query`). |
| Klasifikasi + re-ranking LLM | `google-genai` + `openai` (dual provider) | `app/services/search_service.py` — skema JSON strict, kandidat dikirim ke LLM, dikembalikan verdict (category, severity, reasoning, ranked_runbook_ids max 3). |
| Chat strict-RAG | `google-genai` / `openai`, Jinja2 partial | `app/services/chat_service.py` — jawaban hanya dari runbook yang dikunci; 3 quick action: `checklist`, `compare`, `status_draft`. |
| Simpan / muat / hapus riwayat | SQLite (`triage_history`), Flask-WTF CSRF | `app/repositories/history_repo.py` + endpoint `/triage/save-report`, `/triage/history`, `/triage/history/<id>/delete`, `/load`. |
| Daftar runbook | SQLite, Jinja2 | Blueprint `runbook` (`app/blueprints/runbook.py`, `/runbook`, read-only). |
| Dasbor analitik | SQLite agregasi, `jsonify` | `app/services/analytics_service.py` + `GET /api/analytics/charts` (distribusi kategori, severity, tren 14 hari, summary + fallback rate). |
| Graceful degradation | Tidak ada dependensi ekstra — logika cabang di dalam service | Jika LLM mati/gagal → pakai urutan lexical murni; chat jatuh ke jawaban lokal deterministik dari isi runbook. Tidak ada HTTP 500. |

## 4. Isi Database (`data/app.db`)

Tabel `runbooks` (knowledge base seed):

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | Judul runbook |
| category | TEXT | CHECK: `network`, `database`, `deployment`, `resource` |
| severity | TEXT | CHECK: `SEV1`, `SEV2`, `SEV3`, `SEV4` |
| symptoms_log | TEXT | Gejala / konteks insiden |
| root_cause | TEXT | Akar masalah |
| resolution_steps | TEXT | Langkah mitigasi |
| source_ref | TEXT | Sumber asli (URL / internal) |
| content_hash | TEXT UNIQUE | SHA-256, anti-duplikasi |
| created_at | DATETIME | Waktu insert |

Tabel virtual `runbooks_fts` (FTS5): indeks `title`, `symptoms_log`, `root_cause` dengan trigger insert/delete/update agar sinkron dengan `runbooks`.

Tabel `triage_logs` (riwayat triase anonim, untuk analitik):

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| sanitized_query | TEXT | Log sudah di-redact |
| redaction_count | INTEGER | Jumlah pola yang disensor |
| predicted_category | TEXT | Hasil klasifikasi |
| predicted_severity | TEXT | Hasil klasifikasi |
| top_runbook_ids | TEXT | ID runbook terpilih (koma) |
| is_fallback | INTEGER | 1 jika LLM tidak digunakan |
| created_at | DATETIME | |

Tabel `triage_history` (riwayat yang disimpan user, survives refresh):

| Kolom | Tipe | Keterangan |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | Judul dari user |
| query | TEXT | Query log |
| category | TEXT | Kategori |
| severity | TEXT | Severity |
| top_runbook_ids | TEXT | ID runbook (koma) |
| created_at | DATETIME | |

## 5. Gunanya LLM & Mekanisme Fallback

**Guna LLM:**
- Klasifikasi kategori dan severity insiden dari log yang sudah di-sanitasi.
- Re-ranking Top-3 runbook dari kandidat FTS5 (urutan relevansi).
- Menghasilkan jawaban chat berdasarkan runbook yang dikunci (Strict-RAG; tidak boleh menghalau di luar referensi aktif).

**Dual provider:**
1. Utama: Gemini via `google-genai`.
2. Cadangan: OpenAI-compatible (base URL kustom, default `https://api.hcnsec.cn/v1`, model `Qwen3.8-Flash-Next`).

**Mekanisme fallback (graceful degradation):**
- Jika Gemini gagal → coba provider custom.
- Jika kedua provider mati / timeout / JSON invalid → `is_fallback=True`, sistem tetap menampilkan Top-3 berdasarkan urutan lexical FTS5 murni. `category='unclassified'`, `severity` diambil dari runbook teratas hasil pencarian (bukan selalu `SEV-PENDING`).
- Chat saat LLM offline → jawaban deterministik lokal (`_local_answer`): checklist, perbandingan, draf status, atau ringkasan runbook aktif, tanpa menambah informasi baru.
- Semua path fallback diuji di `tests/test_graceful_degradation.py` (tidak ada crash, Top-3 tetap tampil, log tetap di-redact).
