# SRE Incident Triage & Runbook Assistant

Aplikasi web pendukung keputusan untuk mempercepat analisis akar masalah (Root Cause Analysis) dan standarisasi mitigasi insiden SRE. Menerima raw error log, menyensor data sensitif secara otomatis, mengklasifikasikan kategori & severitas insiden, menemukan Top-3 referensi runbook relevan via pencarian hybrid (SQLite FTS5 BM25 + LLM re-ranking), serta menyediakan asisten tanya jawab terkunci (Strict-RAG) dan visualisasi analitik.

> **Stack:** Flask (Application Factory + Blueprints), SQLite FTS5/BM25, Gemini 2.5-flash (dengan OpenAI-compatible fallback), HTMX, Chart.js, python-dotenv, Flask-WTF CSRF.

## Fitur utama

- **Sanitasi log otomatis**: Regex filter sisi server menyensor Bearer token, API key, connection string DB, email menjadi `<REDACTED>` sebelum log diproses atau dikirim ke LLM.
- **Klasifikasi & severitas**: Output terstruktur JSON: kategori (`network`, `database`, `deployment`, `resource`), severitas (`SEV1`–`SEV4`), dan alasan teknis.
- **Pencarian hybrid + explicit re-triage**: FTS5 BM25 Top-10 → LLM re-ranking Top-3. Tombol *Refine* memperbarui panel referensi tanpa reload halaman (HTMX OOB swap).
- **Strict-RAG chat**: Asisten mitigasi terkunci pada 3 runbook aktif; anti-halusinasi, quick prompts (checklist, perbandingan, draf status).
- **Dashboard analitik**: Distribusi kategori, proporsi severitas, dan tren insiden (Chart.js).
- **Graceful degradation**: Saat LLM API mati/timeout, aplikasi tetap menampilkan Top-3 hasil FTS5 lokal tanpa crash.
- **Seeding**: `scripts/seed.py` inisialisasi `data/app.db` dari `data/schema.sql` dan memuat `data/seed_runbooks.json`.

## Struktur direktori

```
sre-triage-assistant/
├── app/                # Flask application factory, blueprints, services, repositories
├── data/               # app.db, schema.sql, seed_runbooks.json (gitignored)
├── docs/               # PRD, MVP, DESIGN, ARCHI, DATA_FLOW, STRUKTUR_DIREKTORI
├── scripts/
│   ├── fetch/          # Pengambilan runbook dari Prometheus & Stack Exchange
│   ├── processing/     # Normalisasi hasil fetch → seed_runbooks.json
│   └── seed.py         # Seeder database (idempotent)
├── tests/              # Suite pengujian endpoints & layanan
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

```bash
flask --app "app:create_app()" --debug run
```

Buka `http://localhost:5000`. Tidak perlu login untuk triase (sesi anonim).

## Endpoint ringkasan

| Metode | Route | Deskripsi |
|--------|-------|-----------|
| `GET` | `/` | Workspace triase (2 kolom) |
| `POST` | `/triage` | Redaksi → FTS5 + LLM triage → simpan log analitik |
| `POST` | `/triage/refine` | Explicit re-triage dengan konteks baru |
| `POST` | `/chat` | Strict-RAG chat terkunci pada runbook aktif |
| `GET` | `/dashboard` | Halaman analitik operasi |
| `GET` | `/api/analytics/charts` | Agregasi kategori, severitas, tren harian (JSON) |

## Pengujian

```bash
pytest
```
