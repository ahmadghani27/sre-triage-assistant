# **PRD2 — SRE Incident Triage & Runbook Assistant** (`sre-triage-assistant`, v0.1-mvp)

Dokumen ini adalah hasil breakdown dari `PRD.md` menjadi epic, user story, dan acceptance criteria, untuk digunakan sebagai referensi implementasi kode. Semua spesifikasi di sini konsisten dengan `DESIGN.md`, `ARCHITECTURE.md`, `DATA_FLOW.md`, `MVP.md`, dan `AGENTS.md`.

---

## 1. Ringkasan Eksekutif

`sre-triage-assistant` adalah aplikasi web berbasis Flask untuk triase otomatis insiden SRE dan pengambilan runbook. Aplikasi menerima raw error log dari pengguna, menyensor rahasia (Bearer token, API key, DB URI, email), mengklasifikasikan kategori dan severitas insiden, mengambil Top-3 runbook relevan melalui SQLite FTS5 + LLM re-ranking, dan menyediakan asisten chat Strict-RAG terkunci pada 3 runbook aktif. Semua pemrosesan data dilakukan offline-batch saat seeding; LLM hanya digunakan untuk reasoning, bukan sebagai penyimpanan data utama.

---

## 2. Epic & User Stories

### Epic E1 — Sanitasi Log Otomatis (F1)

**US1.1** Sebagai engineer, saya ingin error log yang saya masukkan disensor otomatis sebelum diproses atau dikirim ke LLM, agar kredensial tidak bocor.

| Kriteria Penerimaan | Detail |
|---|---|
| AC1.1.1 | Setiap log masuk harus melalui `redactor.py` sebelum disimpan, dicari, atau dikirim ke API LLM. |
| AC1.1.2 | Pola yang tersensor: Bearer token, API Key (OpenAI `sk-`, generic, AWS, GitHub), DB connection string (postgres/mysql/mongodb/redis/amqp), email. |
| AC1.1.3 | Hasil redaksi adalah token `<REDACTED>`; prefix bidang (misal `Authorization: Bearer `) dipertahankan agar format log tetap terbaca. |
| AC1.1.4 | `redactor.py` mengembalikan `RedactionResult` yang berisi teks hasil, jumlah redaksi, dan label pola yang terdeteksi. |

---

### Epic E2 — Klasifikasi Insiden & Penilaian Severitas (F2)

**US2.1** Sebagai engineer, saya ingin log yang saya masukkan diklasifikasikan ke kategori dan severitas dengan alasan teknis, agar saya tahu tim mana yang bertanggung jawab dan seberapa parah insidennya.

| Kriteria Penerimaan | Detail |
|---|---|
| AC2.1.1 | Output JSON terstruktur: `category`, `severity`, `reasoning`, `ranked_runbook_ids`. |
| AC2.1.2 | `category` ∈ {`network`, `database`, `deployment`, `resource`}. |
| AC2.1.3 | `severity` ∈ {`SEV1`, `SEV2`, `SEV3`, `SEV4`}. |
| AC2.1.4 | `reasoning` berisi 1–2 kalimat teknis. |
| AC2.1.5 | Saat LLM timeout/error/rate limit/malformed JSON, sistem fallback ke `category: "unclassified"` dan `severity: "SEV-PENDING"` (tidak crash). |

---

### Epic E3 — Pencarian Referensi Hybrid & Explicit Re-triage (F3)

**US3.1** Sebagai engineer, saya ingin melihat Top-3 runbook paling relevan dari log saya, sehingga saya tidak perlu mencari manual di dokumen yang terserak.

| Kriteria Penerimaan | Detail |
|---|---|
| AC3.1.1 | Stage 1: SQLite FTS5 / BM25 mengambil hingga 10 kandidat berdasarkan kata kunci dan kode error. |
| AC3.1.2 | Stage 2: LLM re-ranking memilih Top-3 dari 10 kandidat. |
| AC3.1.3 | Query FTS5 divisualisasikan melalui sanitizer yang menghapus operator sintaks (`:`, `/`, `(`, `)`, `"`, `*`) agar stack trace mentah tidak menyebabkan `sqlite3.OperationalError`. |

**US3.2** Sebagai engineer, saya ingin memperbarui daftar Top-3 saat ada konteks baru tanpa memuat ulang halaman, sehingga riwayat percakapan tetap konsisten.

| Kriteria Penerimaan | Detail |
|---|---|
| AC3.2.1 | Tombol "Perbarui Diagnosis / Refine" menjalankan ulang Hybrid Search dengan gabungan log awal + konteks baru. |
| AC3.2.2 | Panel Top-3 diperbarui secara parsial via HTMX Out-of-Band Swap. |
| AC3.2.3 | Pembatas visual `"--- Referensi Diperbarui ---"` disisipkan ke dalam alur chat. |

---

### Epic E4 — Asisten Mitigasi Terkunci (Strict-RAG) (F4)

**US4.1** Sebagai engineer, saya ingin bertanya tentang insiden aktif dan mendapatkan jawaban hanya berdasarkan 3 runbook yang terkunci, tanpa halusinasi.

| Kriteria Penerimaan | Detail |
|---|---|
| AC4.1.1 | Chat dikunci pada 3 `runbook_id` aktif; `runbook_repo.py` mengambil isi lengkap berdasarkan ID tersebut. |
| AC4.1.2 | Sistem dilarang menjawab di luar topik insiden aktif atau mengarang langkah teknis yang tidak ada dalam referensi. |
| AC4.1.3 | Saat LLM tidak tersedia, fallback ke jawaban deterministik lokal dari isi runbook. |

**US4.2** Sebagai engineer, saya ingin menggunakan quick prompt untuk menghasilkan checklist, perbandingan akar masalah, atau draf status insiden.

| Kriteria Penerimaan | Detail |
|---|---|
| AC4.2.1 | Quick action: `checklist`, `compare`, `status_draft`. |
| AC4.2.2 | Setiap aksi diekspansi menjadi prompt lengkap di sisi server oleh `chat_service.py`. |

---

### Epic E5 — Manajemen Knowledge Base & Seeding (F5)

**US5.1** Sebagai pengembang, saya ingin database terisi dengan runbook awal (seed) sebelum aplikasi dijalankan, agar FTS5 dan analitik terlihat realistis saat demo.

| Kriteria Penerimaan | Detail |
|---|---|
| AC5.1.1 | File seed: `data/seed_runbooks.json` dengan minimal 30–40 entri runbook. |
| AC5.1.2 | Skrip seeding: `scripts/seed.py` (idempotent) membuat `data/app.db` dari `data/schema.sql` dan memuat `data/seed_runbooks.json`. |
| AC5.1.3 | Tabel utama: `runbooks` (id, title, category, severity, symptoms_log, root_cause, resolution_steps, source_ref, created_at). |
| AC5.1.4 | Virtual table FTS5: `runbooks_fts` dengan trigger sinkronisasi otomatis. |
| AC5.1.5 | Anti-duplikasi: `INSERT OR IGNORE` pada `content_hash` di tabel `runbooks`. |

**US5.2** Sebagai pengguna terautentikasi (versi mendatang), saya ingin menambah dan memperbarui runbook baru melalui UI CRUD.

| Kriteria Penerimaan | Detail |
|---|---|
| AC5.2.1 | **DI TUNDA ke v0.2** (lihat AGENTS.md §2: authentikasi dan CRUD runbook out of scope untuk v0.1-mvp). |
| AC5.2.2 | Setiap runbook baru diindeks ke tabel FTS5 saat disimpan. |

---

### Epic E6 — Dashboard Analitik Operasional (F6)

**US6.1** Sebagai engineer, saya ingin melihat grafik distribusi kategori, proporsi severitas, dan tren insiden, agar saya memahami pola insiden.

| Kriteria Penerimaan | Detail |
|---|---|
| AC6.1.1 | Endpoint `GET /api/analytics/charts` mengembalikan JSON: `category_distribution`, `severity_distribution`, `incident_trend`, `summary`. |
| AC6.1.2 | Agregasi harus mendukung nilai fallback `"unclassified"` dan `"SEV-PENDING"` selain kategori dan severitas standar agar Chart.js tidak rusak saat degradation. |
| AC6.1.3 | Halaman `/dashboard` merender 3 canvas grafik interaktif. |

---

### Epic E7 — Keamanan & Resiliensi (NFR)

**US7.1** Sebagai administrator, saya ingin aplikasi dilindungi CSRF dan pembatasan panjang input, serta tidak crash saat LLM gangguan.

| Kriteria Penerimaan | Detail |
|---|---|
| AC7.1.1 | CSRFProtection diaktifkan global; token dilewatkan via `hx-headers` pada `<body>` di `base.html`. |
| AC7.1.2 | `MAX_CONTENT_LENGTH = 5000` karakter. |
| AC7.1.3 | Setiap panggilan LLM dibungkus `try...except` dengan timeout 10 detik dan graceful degradation ke FTS5 Top-3. |
| AC7.1.4 | Tidak ada hardcoded secret/API key di kode; `GEMINI_API_KEY` dan `SECRET_KEY` diambil secara eksklusif dari environment variables. |

---

### Epic E8 — Batasan Ruang Lingkup (Out of Scope)

| Item | Alasan |
|---|---|
| Auto-remediation (SSH, API Kubernetes, eksekusi perintah ke produksi) | Aplikasi read-only, tidak ada akses infrastruktur. |
| Integrasi webhook real-time (Datadog, Sentry, Prometheus) | Input log dilakukan manual oleh engineer. |
| Authentikasi & registrasi pengguna untuk v0.1 | Out of scope per AGENTS.md §2; sesi anonim tunggal. |
| IP-based rate limiting | Ditunda ke v0.2; hanya CSRF dan batas panjang input. |
| Vector embedding / pencarian semantik | Dihapus dari v0.1-mvp; catatan opsional untuk v0.2 di `DATA_FLOW.md` §5. |

---

## 3. Arsitektur Referensi (Ringkasan)

| Komponen | Path | Peran |
|---|---|---|
| Application Factory | `app/__init__.py` | `create_app()`, register blueprint, inisialisasi CSRF & LLM |
| Extensions | `app/extensions.py` | `get_db()`, `close_db()`, `llm = LLM()`, `csrf` |
| Config | `app/config.py` | `SECRET_KEY`, `MAX_CONTENT_LENGTH`, `DATABASE`, `GEMINI_API_KEY` |
| Blueprint Triase | `app/blueprints/triage.py` | Routes: `/`, `/triage`, `/triage/refine`, `/chat` |
| Blueprint Analitik | `app/blueprints/analytics.py` | Routes: `/dashboard`, `/api/analytics/charts` |
| Service: Redactor | `app/services/redactor.py` | Regex PII & secret masking |
| Service: Search | `app/services/search_service.py` | FTS5 sanitizer + hybrid search + LLM re-rank |
| Service: Triage | `app/services/triage_service.py` | Orchestration redaction → search → persist |
| Service: Chat | `app/services/chat_service.py` | Strict-RAG prompt assembly & sintesis |
| Service: Analytics | `app/services/analytics_service.py` | Agregasi kategori, severitas, tren |
| Repository: Runbook | `app/repositories/runbook_repo.py` | FTS5 BM25 search & fetch by ID |
| Repository: Log | `app/repositories/log_repo.py` | Triage event persistence & analytics queries |
| Script: Seed | `scripts/seed.py` | Inisialisasi DB & load `data/seed_runbooks.json` |
| Script: Fetch Prometheus | `scripts/fetch/fetch_prometheus_runbooks.py` | Scraping runbook dari GitHub API |
| Script: Fetch StackExchange | `scripts/fetch/fetch_stackexchange.py` | Scraping Q&A per kategori |
| Script: Normalize | `scripts/processing/normalize_runbooks.py` | Pembersihan, klasifikasi, validasi, anti-duplikasi |
| Schema | `data/schema.sql` | DDL tabel `runbooks`, `runbooks_fts`, `triage_logs`, trigger |
| Database | `data/app.db` | SQLite tunggal (gitignored) |

---

## 4. Definisi Selesai (Definition of Done) v0.1-mvp

- [ ] Aplikasi berjalan lokal dengan `flask --app "app:create_app()" --debug run` tanpa dependensi eksternal selain LLM API.
- [ ] Log dengan `Bearer` / connection string tersensor menjadi `<REDACTED>` sebelum diproses.
- [ ] Karakter khusus stack trace (`:`, `/`, `(`, `)`, `"`) tidak menyebabkan FTS5 syntax error.
- [ ] Explicit Re-triage memperbarui panel Top-3 via HTMX OOB dan menyisipkan pembatas chat.
- [ ] Saat LLM API dicabut / mati, aplikasi tetap menampilkan Top-3 FTS5 tanpa HTTP 500.
- [ ] Dashboard merender 3 grafik Chart.js dengan data akurat dari SQLite.
- [ ] Minimal 30–40 entri runbook di `data/seed_runbooks.json`, terdistribusi di 4 kategori dan 4 level severitas.
