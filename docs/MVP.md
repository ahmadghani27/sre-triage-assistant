# **MVP Specification: SRE Incident Triage & Runbook Assistant (`v0.1-mvp`)**

## 1. Tujuan Rilis MVP
Membuktikan validitas alur kerja utama (*core value proposition*) aplikasi: menerima *raw error log*, menyensor data sensitif secara otomatis, mengklasifikasikan insiden, menemukan Top-3 referensi *runbook* relevan, serta menyediakan asisten tanya jawab terkunci (*Strict-RAG*) dan visualisasi analitik dasar dalam satu siklus demo yang stabil.

## 2. Pemangkasan Ruang Lingkup (Scope Cut Matrix)
Pemetaan fitur dari `PRD.md` ke dalam rilis `v0.1-mvp` untuk memaksimalkan efisiensi waktu pengembangan:

| Fitur PRD | Status di MVP | Implementasi di MVP (`v0.1`) | Alasan Teknis / Trade-Off |
| :--- | :--- | :--- | :--- |
| **F1. Sanitasi Log Otomatis** | **IN-SCOPE (Full)** | Filter *regex* sisi server untuk menyensor *Bearer Token*, *API Key*, kata sandi DB, dan email menjadi `<REDACTED>`[cite: 1]. | Komponen keamanan wajib dengan kompleksitas rendah dan dampak demo tinggi. |
| **F2. Klasifikasi & Severitas** | **IN-SCOPE (Full)** | Ekstraksi JSON terstruktur via LLM API (`category`, `severity`, `reasoning`)[cite: 1]. | Inti dari fitur otomatisasi triase. |
| **F3. Hybrid Search & Re-triage** | **IN-SCOPE (Full)** | Pencarian 2 tahap (SQLite FTS5 BM25 + LLM Re-ranking) + tombol *Refine* dengan HTMX OOB Swap[cite: 1]. | Pembeda utama aplikasi dibandingkan pencarian teks biasa. |
| **F4. Scoped Assistant** | **IN-SCOPE (Full)** | *Chat* terkunci pada Top-3 *runbook* aktif + 3 tombol *Quick Prompts*[cite: 1]. | Memenuhi syarat komponen *chatbot* kontekstual mata kuliah. |
| **F5. Manajemen Knowledge Base & Auth** | **SIMPLIFIED (Mocked)** | **Tanpa Login/Register.** Menggunakan sesi anonim tunggal. Data *runbook* diisi melalui skrip *seeding* (`seed.py` dari file JSON/CSV), bukan form CRUD di UI. | Menghindari *boilerplate* manajemen sesi, hashing password, dan form CRUD agar waktu fokus pada *AI & Search engine*. |
| **F6. Dashboard Analitik** | **IN-SCOPE (Core)** | Menampilkan 3 grafik utama (Distribusi Kategori, Proporsi `SEV1`–`SEV4`, dan Tren Insiden)[cite: 1] menggunakan data gabungan *seed* + riwayat triase sesi. | Memenuhi syarat komponen visualisasi data mata kuliah. |
| **NFR. Security & Rate Limit** | **SIMPLIFIED** | Menggunakan proteksi CSRF standar Flask-WTF dan batas panjang karakter input (`max_length=5000`). *IP Rate Limiting* ditunda. | Cukup untuk mencegah *payload* berlebih saat demo tanpa perlu setup Redis/Memcached. |


## 3. Alur Pengguna Utama (Happy Path Demo Flow)
1. **Input Insiden:** Pengguna membuka halaman utama (langsung masuk tanpa *login*), lalu menempelkan contoh *error log* (misal: `502 Bad Gateway` dengan kredensial dummy di dalamnya).
2. **Sanitasi & Triase:** Sistem menampilkan notifikasi bahwa kredensial telah disensor (`<REDACTED>`), memunculkan label kategori (`deployment`) dan severitas (`SEV2`) beserta alasan teknisnya[cite: 1].
3. **Inspeksi Referensi:** Panel kanan menampilkan **Top-3 Runbook** paling relevan dari SQLite.
4. **Diskusi & Mitigasi:** Pengguna menekan tombol *Quick Prompt* **"Buat Checklist Mitigasi"** di kolom *chat*. Bot menjawab murni berdasarkan 3 referensi tersebut[cite: 1].
5. **Explicit Re-triage:** Pengguna menambahkan konteks baru di kotak *Refine* (misal: *"Ternyata pod container terkena OOMKilled"*), menekan **Perbarui Diagnosis**, daftar Top-3 berganti tanpa *reload* halaman, dan muncul garis pemisah di *chat*[cite: 1].
6. **Monitoring Analitik:** Pengguna berpindah ke tab **Dashboard** untuk melihat pembaruan grafik distribusi insiden[cite: 1].


## 4. Kebutuhan Data Awal (Seed Data Requirements)
Agar pencarian FTS5 dan grafik analitik terlihat realistis saat demo, sistem wajib memiliki **minimal 30–40 entri runbook** dalam file `data/seed_runbooks.json` sebelum aplikasi dijalankan:
- **Distribusi Kategori:** Minimal 8–10 kasus untuk masing-masing domain (`network`, `database`, `deployment`, `resource`)[cite: 1].
- **Distribusi Severitas:** Mencakup variasi seimbang dari `SEV1` hingga `SEV4`[cite: 1].
- **Kelengkapan Atribut:** Setiap entri wajib memiliki `title`, `category`, `severity`, `symptoms_log`, `root_cause`, dan `resolution_steps`[cite: 1].


## 5. Kriteria Keberhasilan MVP (Definition of Done)
Rilis `v0.1-mvp` dinyatakan selesai dan siap didemokan apabila memenuhi seluruh kriteria berikut:
- [ ] Aplikasi berjalan lokal dengan satu perintah (`flask run`) tanpa ketergantungan layanan eksternal selain LLM API.
- [ ] Input log yang mengandung pola `Bearer ...` atau `postgres://user:pass@...` terbukti tersensor menjadi `<REDACTED>` sebelum diproses[cite: 1].
- [ ] Kueri dengan karakter spesial stack trace (seperti `:`, `/`, `(`, `)`) tidak menyebabkan *syntax error* pada SQLite FTS5.
- [ ] Fitur *Explicit Re-triage* memperbarui panel Top-3 secara parsial (HTMX OOB) dan menyisipkan pembatas konteks di alur *chat*[cite: 1].
- [ ] Ketika API key LLM dicabut atau koneksi internet dimatikan (*Graceful Degradation*), aplikasi tetap menampilkan Top-3 hasil pencarian FTS5 beserta langkah perbaikannya tanpa mengalami *crash* (HTTP 500)[cite: 1].
- [ ] Halaman Dashboard merender ketiga grafik interaktif dengan akurat berdasarkan data di SQLite[cite: 1].


## 6. Item yang Ditunda ke Fase Berikutnya (Post-MVP / v0.2)
- Sistem registrasi dan autentikasi pengguna (`Flask-Login` + `bcrypt`)[cite: 1].
- Halaman riwayat diagnosis pribadi per akun pengguna[cite: 1].
- Antarmuka web (UI) untuk menambah, mengedit, dan menghapus dokumen *runbook* (CRUD)[cite: 1].
- Implementasi *IP-based Rate Limiting* menggunakan `Flask-Limiter`[cite: 1].