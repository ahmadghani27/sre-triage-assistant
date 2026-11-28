# SRE Incident Triage & Runbook Assistant

Aplikasi web pendukung keputusan untuk mempercepat analisis akar masalah (Root Cause Analysis) dan standarisasi mitigasi insiden SRE. Menerima raw error log, menyensor data sensitif secara otomatis, mengklasifikasikan kategori & severitas insiden, menemukan Top-3 referensi runbook relevan via pencarian hybrid (SQLite FTS5 BM25 + LLM re-ranking), serta menyediakan asisten tanya jawab terkunci (Strict-RAG) dan visualisasi analitik.

## Fitur utama

- **Sanitasi log otomatis**: Regex filter sisi server menyensor Bearer token, API key, connection string DB, email menjadi `<REDACTED>` sebelum log diproses atau dikirim ke LLM.
- **Klasifikasi & severitas**: Output terstruktur JSON: kategori (`network`, `database`, `deployment`, `resource`), severitas (`SEV1`–`SEV4`), dan alasan teknis.
- **Pencarian hybrid + explicit re-triage**: FTS5 BM25 Top-10 → LLM re-ranking Top-3. Tombol *Refine* memperbarui panel referensi tanpa reload halaman (HTMX OOB swap).
- **Strict-RAG chat**: Asisten mitigasi terkunci pada 3 runbook aktif; anti-halusinasi, quick prompts (checklist, perbandingan, draf status).
- **Dashboard analitik**: Distribusi kategori, proporsi severitas, dan tren insiden (Chart.js).
- **Graceful degradation**: Saat LLM API mati/timeout, aplikasi tetap menampilkan Top-3 hasil FTS5 lokal tanpa crash.
- **Seeding**: `scripts/seed.py` inisialisasi `data/app.db` dari `data/schema.sql` dan memuat `data/seed_runbooks.json` (idempotent via `content_hash`).

## Struktur direktori

```
sre-triage-assistant/
├── .github/
│   └── workflows/
│       └── ci.yml      # CI: test + security (bandit, pip-audit)
├── app/                # Flask application factory, blueprints, services, repositories
├── data/               # app.db, schema.sql, seed_runbooks.json
├── scripts/
│   ├── fetch/          # Pengambilan runbook dari sumber publik (5 skrip)
│   ├── processing/     # Normalisasi hasil fetch → seed_runbooks.json
│   └── seed.py         # Seeder database (idempotent)
├── tests/              # Suite pengujian endpoints & layanan
├── Dockerfile          # Image Python slim, non-root user, gunicorn
├── .dockerignore       # Exclude .venv, __pycache__, .git, data/app.db, .env*, tests/, other/
├── docker-compose.yml  # Service app, port 5000:5000, volume data/, env_file .env.docker
├── entrypoint.sh       # Runtime seed (idempoten) lalu gunicorn bind 0.0.0.0:5000
├── .env.docker         # Contoh env vars untuk container (secrets tidak dikomit)
├── requirements.txt
└── run.py              # Titik masuk aplikasi
```

## Memulai

### 1. Clone & siapkan environment

```bash
git clone <repo-url>
cd sre-triage-assistant
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> Catatan: environment ini dielola secara lokal; `requirements.txt` mencakup semua dependensi runtime.

### 2. Konfigurasi variabel environment

```bash
cp .env.example .env
```

Isi `.env` dengan minimal:

```ini
GEMINI_API_KEY=<GEMINI_API_KEY>
CUSTOM_API_KEY=<CUSTOM_API_KEY_second_llm_api>
STACKEXCHANGE_API_KEY=<STACKEXCHANGE_API_KEY>
```

> `GEMINI_API_KEY` opsional: jika tidak diisi, aplikasi tetap berjalan dengan graceful degradation (fallback ke hasil FTS5 lokal).

### 3. Siapkan database dengan seed data

```bash
python scripts/seed.py
```

Seeder membaca `data/schema.sql` dan `data/seed_runbooks.json`, lalu menghasilkan `data/app.db` dengan FTS5 index dan trigger sinkronisasi. Idempotent: dapat dijalankan ulang aman.

### 4. Jalankan aplikasi

**Development:**

```bash
flask --app "app:create_app()" --debug run
```

Buka `http://localhost:5000`. Tidak perlu login untuk triase (sesi anonim).

**Produksi (Docker):**

```bash
docker compose up --build
```

Aplikasi akan tersedia di `http://localhost:5000` dengan `gunicorn` sebagai WSGI server production. Detail konfigurasi lihat `deploy_docker.md` dan `Dockerfile`.

## Endpoint ringkasan

| Metode | Route | Deskripsi |
|--------|-------|-----------|
| `GET` | `/` | Workspace triase (2 kolom) |
| `POST` | `/triage` | Redaksi → FTS5 + LLM triage → simpan log analitik |
| `POST` | `/triage/refine` | Explicit re-triage dengan konteks baru |
| `POST` | `/chat` | Strict-RAG chat terkunci pada runbook aktif |
| `GET` | `/dashboard` | Halaman analitik operasi |
| `GET` | `/api/analytics/charts` | Agregasi kategori, severitas, tren harian (JSON) |
| `GET` | `/runbook` | Daftar semua runbook (read-only) |
| `GET` | `/triage/history` | Daftar riwayat triase yang disimpan user |
| `POST` | `/triage/save-report` | Simpan hasil triase ke riwayat |
| `POST` | `/triage/history/<id>/delete` | Hapus satu riwayat |
| `POST` | `/triage/history/<id>/load` | Muat ulang riwayat ke workspace |

## CI (GitHub Actions)

Workflow ada di `.github/workflows/ci.yml`. Dijalankan pada:

- `push` ke `main` / `master`
- `pull_request` ke `main` / `master`
- `workflow_dispatch` (manual)

Terdapat dua job:

1. **test** — install dependensi dari `requirements.txt`, jalankan `pytest` pada matrix Python `3.12` dan `3.13`.
2. **security** (butuh `test` lulus) — `pip-audit` untuk kerentanan dependensi dan `bandit` untuk static security scan pada `app/`. Laporan diunggah sebagai artifact (30 hari).

Keamanan: `permissions` read-only, `concurrency` dengan `cancel-in-progress`, `checkout` tanpa credentials, dan tidak ada secret yang dibaked ke image.

## Pengujian

```bash
pytest
```
