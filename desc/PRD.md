# **SRE Incident Triage & Runbook Assistant** (`sre-triage-assistant`)

## 1. Latar Belakang & Pernyataan Masalah (Problem Statement)
Dalam operasional sistem produksi (_production_), tim _Software Engineering_ dan _Site Reliability Engineering_ (SRE) menghadapi tingginya frekuensi insiden teknis (kegagalan _deployment_, _latency spike_, _database connection exhaustion_, dan _HTTP 5xx errors_).
Proses triase awal saat ini memiliki tiga hambatan struktural:
1.  **Fragmentasi Pengetahuan (_Tribal Knowledge_):** Solusi insiden terdahulu tersebar di riwayat _chat_, dokumentasi usang, atau hanya diketahui oleh _engineer_ senior tertentu.
2.  **Tingginya _Cognitive Load_ Saat Insiden:** _Engineer_ harus membaca _stack trace_ mentah secara manual di bawah tekanan waktu untuk menentukan tingkat keparahan dan tim yang bertanggung jawab.
3.  **Absennya Pembelajaran Sistemik:** Insiden berulang tidak terdokumentasi dalam format terstruktur yang dapat dicari kembali secara semantik.
    

## 2. Tujuan Produk
Membangun aplikasi web terpusat yang berfungsi sebagai sistem pendukung keputusan (_decision-support system_) untuk mempercepat analisis akar masalah (_Root Cause Analysis_) dan standarisasi mitigasi insiden.
    
## 3. Target Pengguna & Hak Akses (User Personas & RBAC)
1.  **Guest / Unauthenticated Engineer:** Akses cepat untuk melakukan triase insiden darurat tanpa hambatan _login_. Riwayat triase tetap dicatat secara anonim untuk kebutuhan analitik tren insiden, namun tidak terikat pada profil pengguna mana pun.
2.  **Authenticated Engineer (Backend, DevOps, SRE):** Memiliki akun terverifikasi untuk menyimpan riwayat triase dan menambahkan atau memperbarui dokumen _runbook_ baru ke dalam _Knowledge Base_.
    
## 4. Spesifikasi Fungsional (Functional Requirements)
### F1. Sanitasi Log Otomatis (Automated Secret & PII Redaction)
-   **Deskripsi:** Sebelum _error log_ diproses oleh mesin pencari atau dikirim ke API LLM eksternal, sistem wajib menjalankan filter _regex_ di sisi server (_backend_).
-   **Cakupan:** Menyensor otomatis pola sensitif seperti _Bearer Tokens_,  _API Keys_,  _Database Connection Strings_ (kata sandi), dan alamat email pengguna menjadi token `<REDACTED>`.
    

### F2. Klasifikasi Insiden & Penilaian Severitas (Automated Triage Engine)
-   **Deskripsi:** Sistem menganalisis input _error log_ (mendukung bahasa Indonesia, Inggris, maupun campuran) dan menghasilkan output terstruktur (JSON):
    -   **Domain Kategori:** `network`, `database`, `deployment`, atau `resource`.
    -   **Tingkat Severitas:** `SEV1` (Critical/Outage), `SEV2` (Major Degradation), `SEV3` (Minor/Partial Impact), atau `SEV4` (Low/Warning).
    -   **Triage Reasoning:** Penjelasan teknis 1–2 kalimat mengenai dasar penetapan kategori dan severitas tersebut (menggantikan skor persentase arbitrer).
        



### F3. Pencarian Referensi Hybrid & Explicit Re-triage (Top-3 Runbooks)
- **Deskripsi:** Menggabungkan dua tahap penyaringan untuk mengambil 3 dokumen _runbook_ paling relevan:
  1. _Lexical Retrieval (SQLite FTS5 / BM25):_ Mengambil hingga 10 kandidat referensi berdasarkan kecocokan kata kunci dan kode error eksak (misal: `502 Bad Gateway`, `ECONNREFUSED`, `OOMKilled`).
  2. _Semantic Filtering (LLM Re-ranking):_ Mengevaluasi kesesuaian konteks gejala dari kandidat tersebut untuk memilih Top-3 referensi terbaik.
- **Explicit Re-triage (Pembaruan Konteks Terkontrol):** Selama sesi diskusi berlangsung, daftar Top-3 referensi tetap terkunci (_locked_) secara default agar riwayat percakapan konsisten. Namun, pengguna dapat menekan tombol **"Perbarui Diagnosis / Refine"** dengan menyertakan informasi tambahan. Sistem kemudian:
  - Menjalankan ulang _Hybrid Search_ menggunakan gabungan log awal dan konteks baru.
  - Memperbarui panel Top-3 referensi secara parsial tanpa memuat ulang halaman (_via_ HTMX Out-of-Band Swap).
  - Menyisipkan pembatas visual (_"--- Referensi Diperbarui ---"_) ke dalam alur _chat_ untuk menandai perubahan basis pengetahuan pada pesan-pesan berikutnya.

### F4. Asisten Mitigasi Terkunci (Strict-RAG Scoped Assistant)
- **Deskripsi:** Antarmuka diskusi kontekstual yang **dikunci secara ketat** pada 3 referensi _runbook_ yang sedang aktif pada segmen percakapan tersebut.
- **Guardrails:** Sistem dilarang menjawab pertanyaan di luar topik insiden aktif atau mengarang langkah teknis yang tidak didukung oleh referensi (_anti-hallucination prompt_).
- **Aksi Cepat (_Quick Prompts_):** Menyediakan tombol instan untuk menghasilkan: (1) _Checklist_ langkah mitigasi berurutan, (2) Perbandingan akar masalah dari 3 referensi, dan (3) Draf pengumuman status insiden untuk kanal komunikasi tim (_Slack/Teams_).
    
### F5. Manajemen Knowledge Base & Riwayat (CRUD & Seeding)
-   **Deskripsi:** Pengguna terautentikasi dapat melihat riwayat diagnosis pribadi dan berkontribusi menambah _runbook_ baru (Judul, Gejala/Log, Kategori, Severitas, Akar Masalah, Langkah Perbaikan). Setiap _runbook_ baruotomatis diindeks ke tabel FTS5 saat disimpan.

### F6. Dashboard Analitik Operasional
-   **Deskripsi:** Visualisasi data berbasis grafik interaktif yang menampilkan: (1) Distribusi insiden berdasarkan kategori domain, (2) Proporsi tingkat severitas (`SEV1`–`SEV4`), dan (3) Tren frekuensi insiden dari waktu ke waktu.
    

## 5. Persyaratan Non-Fungsional (Non-Functional Requirements)
-   **Arsitektur Modular:** Backend dibangun menggunakan pola _Flask Application Factory_ dan _Blueprints_ (`auth`,  `triage`,  `runbooks`,  `analytics`) dengan pemisahan ketat antara _routing layer_ dan _service/business logic layer_.
-   **Graceful Degradation (Resiliensi):** Jika layanan LLM API eksternal mengalami gangguan (_timeout_ atau _rate limit_), aplikasi tidak boleh _crash_. Sistem wajib melakukan _fallback_ otomatis dengan tetap menampilkan hasil pencarian Top-3 dari database lokal beserta langkah perbaikannya.
-   **Keamanan Aplikasi Web:** Implementasi proteksi CSRF pada seluruh _form_,  _password hashing_ standar industri (`bcrypt`/`argon2`), serta _rate limiting_ berbasis IP untuk mencegah penyalahgunaan kuota API LLM.
-   **Portabilitas Database:** Penggunaan SQLAlchemy ORM agar skema database dapat dijalankan secara lokal menggunakan SQLite saat pengembangan/demo, namun siap dimigrasi ke PostgreSQL pada lingkungan produksi skala besar.
    

## 6. Batasan Ruang Lingkup (Out of Scope)
-   **Non-Eksekusi (Read-Only):** Aplikasi tidak memiliki akses SSH, API Kubernetes, atau kredensial infrastruktur untuk mengeksekusi perintah perbaikan otomatis (_auto-remediation_) ke server produksi.
-   **Tidak Ada Integrasi Webhook Real-Time:** Sistem tidak menarik log secara otomatis dari _monitoring tools_ (seperti Datadog/Sentry/Prometheus); input dilakukan secara manual oleh _engineer_.