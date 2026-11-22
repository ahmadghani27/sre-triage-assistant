# **ARCHI — Spesifikasi Arsitektur Teknis** (`sre-triage-assistant`, v0.1-mvp)

Dokumen ini merupakan turunan dari `PRD2.md` (epic → user story → acceptance criteria) ke spesifikasi arsitektur implementasi: komponen, antarmuka, alur data, skema database, dan kontrak API. Konsisten dengan `DESIGN.md`, `ARCHITECTURE.md`, `DATA_FLOW.md`, `MVP.md`, dan `AGENTS.md`.

---

## 1. Ringkasan Arsitektur

Aplikasi dibangun sebagai **Modular Monolith** dengan **Hypermedia-Driven Application (HDA)**:

* **Strict Layered Separation:** HTTP routing (`blueprints`), business orchestration (`services`), dan data persistence (`repositories`) terpisah ketat. Routes tidak pernah mengeksekusi SQL langsung atau memanggil SDK LLM.
* **Hypermedia over JSON SPA:** Server renders HTML fragments (`partials/`) dan update multiple UI regions secara atomic menggunakan HTMX Out-of-Band (OOB) Swaps.
* **Offline-First Knowledge Base:** Runbook retrieval bergantung pada embedded SQLite FTS5. External LLM API hanya digunakan untuk reasoning, re-ranking, dan sintesis bahasa alami—bukan sebagai primary data store.
* **Graceful Degradation:** Semua external API failure (timeout, quota exhaustion, malformed output) degrade secara deterministik ke hasil pencarian lokal tanpa crash request lifecycle.

---

## 2. Komponen & Tanggung Jawab

| Komponen | Path | Tanggung Jawab Utama | Epic Terkait |
|---|---|---|---|
| Application Factory | `app/__init__.py` | `create_app()`, register blueprint, inisialisasi CSRF & LLM, setup data dir | E7 |
| Extensions | `app/extensions.py` | `get_db()`, `close_db()`, `llm = LLM()`, `csrf = CSRFProtect()`, `init_db_getter()`, `_ensure_schema()` | E5, E7 |
| Config | `app/config.py` | `SECRET_KEY`, `MAX_CONTENT_LENGTH`, `DATABASE`, `GEMINI_API_KEY`, `GEMINI_MODEL` | E7 |
| Blueprint: Triase | `app/blueprints/triage.py` | Routes `GET /`, `POST /triage`, `POST /triage/refine`, `POST /chat`; request parsing + render_template saja | E1–E4, E7 |
| Blueprint: Analitik | `app/blueprints/analytics.py` | Routes `GET /dashboard`, `GET /api/analytics/charts` | E6 |
| Service: Redactor | `app/services/redactor.py` | Regex PII & secret masking; `redact_secrets(text) -> RedactionResult` | E1 |
| Service: Search | `app/services/search_service.py` | FTS5 sanitizer + hybrid search (lexical stage 1 → LLM re-rank stage 2) | E3 |
| Service: Triage | `app/services/triage_service.py` | Orchestration redaction → search → persist; `TriageResult` dataclass | E1–E3, E7 |
| Service: Chat | `app/services/chat_service.py` | Strict-RAG prompt assembly & sintesis; quick action expansion | E4 |
| Service: Analytics | `app/services/analytics_service.py` | Agregasi kategori, severitas, tren; mendukung nilai fallback | E6 |
| Repository: Runbook | `app/repositories/runbook_repo.py` | FTS5 BM25 search & fetch by ID; `build_fts_query`, `extract_fts_tokens` | E3, E5 |
| Repository: Log | `app/repositories/log_repo.py` | Triage event persistence & analytics queries (`triage_logs`) | E6, E7 |
| Script: Seed | `scripts/seed.py` | Idempotent: inisialisasi `data/app.db` dari `data/schema.sql` + load `data/seed_runbooks.json` | E5 |
| Script: Fetch Prometheus | `scripts/fetch/fetch_prometheus_runbooks.py` | Scraping runbook Prometheus dari GitHub API → `data/raw_prometheus_candidates.json` | E5 |
| Script: Fetch StackExchange | `scripts/fetch/fetch_stackexchange.py` | Scraping Q&A Stack Exchange per kategori → `data/raw_stackexchange_candidates.json` | E5 |
| Script: Normalize | `scripts/processing/normalize_runbooks.py` | Pembersihan, klasifikasi, validasi, anti-duplikasi → `data/seed_runbooks.json` | E5 |
| Schema | `data/schema.sql` | DDL tabel `runbooks`, `runbooks_fts`, `triage_logs`, trigger sinkronisasi | E5 |
| Database | `data/app.db` | SQLite tunggal, WAL mode, gitignored | E5, E7 |

---

## 3. Skema Database (`data/schema.sql`)

Tabel utama `runbooks` (melengkapi `DESIGN.md` §1):

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('network', 'database', 'deployment', 'resource')),
    severity TEXT NOT NULL CHECK (severity IN ('SEV1', 'SEV2', 'SEV3', 'SEV4')),
    symptoms_log TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    resolution_steps TEXT NOT NULL,
    source_ref TEXT DEFAULT 'internal',
    content_hash TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS runbooks_fts USING fts5(
    title,
    symptoms_log,
    root_cause,
    content='runbooks',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS runbooks_ai AFTER INSERT ON runbooks BEGIN
    INSERT INTO runbooks_fts(rowid, title, symptoms_log, root_cause)
    VALUES (new.id, new.title, new.symptoms_log, new.root_cause);
END;
CREATE TRIGGER IF NOT EXISTS runbooks_ad AFTER DELETE ON runbooks BEGIN
    INSERT INTO runbooks_fts(runbooks_fts, rowid, title, symptoms_log, root_cause)
    VALUES ('delete', old.id, old.title, old.symptoms_log, old.root_cause);
END;
CREATE TRIGGER IF NOT EXISTS runbooks_au AFTER UPDATE ON runbooks BEGIN
    INSERT INTO runbooks_fts(runbooks_fts, rowid, title, symptoms_log, root_cause)
    VALUES ('delete', old.id, old.title, old.symptoms_log, old.root_cause);
    INSERT INTO runbooks_fts(rowid, title, symptoms_log, root_cause)
    VALUES (new.id, new.title, new.symptoms_log, new.root_cause);
END;

CREATE TABLE IF NOT EXISTS triage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sanitized_query TEXT NOT NULL,
    redaction_count INTEGER DEFAULT 0,
    predicted_category TEXT NOT NULL,
    predicted_severity TEXT NOT NULL,
    top_runbook_ids TEXT NOT NULL,
    is_fallback INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Catatan: `content_hash` ditambahkan sebagai kolom `UNIQUE` untuk anti-duplikasi lintas batch (`INSERT OR IGNORE` di `scripts/seed.py`).

---

## 4. Alur Data (Data Flow)

### 4.1 Pipeline Seeding (Offline-Batch)

```text
[GitHub API / Stack Exchange API]
         │
         ▼
[scripts/fetch/*.py] ──► data/raw_*_candidates.json
         │
         ▼
[scripts/processing/normalize_runbooks.py]
         │  Input: raw_prometheus_candidates.json, raw_stackexchange_candidates.json
         │  Output: data/seed_runbooks.json
         │  Skema output: title, category, severity, symptoms_log,
         │              root_cause, resolution_steps, source_ref, content_hash
         ▼
[scripts/seed.py] ──► data/app.db (tabel runbooks + runbooks_fts + triggers)
```

Tahap embedding (`sentence-transformers`) **dihapus dari v0.1-mvp**; dicatat sebagai fitur opsional v0.2 di `DATA_FLOW.md` §5.

### 4.2 Runtime Triage (`POST /triage`)

```text
[User Raw Log]
      │
      ▼ (POST /triage + CSRF token via hx-headers)
[Regex Redactor] ──► Mask secrets to <REDACTED>
      │
      ├──────────────────────────────────────────┐
      ▼                                          ▼
[FTS5 Query Sanitizer]                   (Sanitized Log)
      │                                          │
      ▼                                          │
[SQLite FTS5 BM25] ──► Top-10 Candidates ────────┤
                                                 ▼
                                    [LLM Triage & Re-ranker]
                                      (Structured JSON Mode)
                                                 │
                      ┌──────────────────────────┴──────────────────────────┐
                      ▼ (Success)                                           ▼ (Timeout / Error)
       [Top-3 Selected + Category/SEV]                      [Fallback: FTS5 Top-3 + "unclassified" / "SEV-PENDING"]
                      │                                                     │
                      └──────────────────────────┬──────────────────────────┘
                                                 ▼
                                [Save to triage_logs & Render HTML]
                             (Main Panel + OOB Right Panel Swap)
```

### 4.3 Explicit Re-triage (`POST /triage/refine`)

1. HTMX submits `sanitized_log` + `refine_note` + hidden `locked_runbook_ids`.
2. `redactor.py` sanitize `refine_note`, concatenate dengan `original_sanitized_log`.
3. `search_service.py` re-run 2-Stage Hybrid Search (FTS5 Top-10 → LLM Re-rank Top-3).
4. Respons multipart HTMX: `_context_divider.html` appended ke chat, OOB swap `_top3_panel.html`, update hidden `#workspace-state`.

### 4.4 Strict-RAG Chat (`POST /chat`)

1. HTMX submits `message` atau `quick_action` + `locked_runbook_ids`.
2. `runbook_repo.get_by_ids(locked_runbook_ids)` mengambil isi lengkap 3 runbook.
3. `chat_service.answer()` bangun Strict-RAG system prompt, kirim ke LLM, atau fallback ke jawaban deterministik lokal.
4. Respons `_chat_message.html` appended ke chat container.

---

## 5. Kontrak Antarmuka & API

### 5.1 Endpoint Ringkasan

| Method & Route | Payload (form-data) | Target | OOB Swap | Deskripsi |
|---|---|---|---|---|
| `GET /` | None | Full Page (`workspace.html`) | None | Render workspace kosong 2 kolom |
| `POST /triage` | `raw_log` | `#triage-output-area` | `#top3-reference-panel`, `#workspace-state` | Redaction, FTS5 + LLM triage, simpan analitik, unlock chat |
| `POST /triage/refine` | `refine_note`, `sanitized_log`, `locked_runbook_ids` | `#chat-messages` (beforeend) | `#top3-reference-panel`, `#workspace-state` | Explicit re-triage, context divider, OOB update panel + hidden state |
| `POST /chat` | `message` atau `quick_action`, `locked_runbook_ids` | `#chat-messages` (beforeend) | None | User bubble + Strict-RAG assistant bubble |
| `GET /dashboard` | None | Full Page (`dashboard.html`) | None | Render shell dashboard analitik |
| `GET /api/analytics/charts` | None | JSON Response | None | Agregasi kategori, severitas, tren harian, summary |

### 5.2 Kontrak JSON: Triage Classification & Re-ranking (LLM Output Schema)

```json
{
  "type": "object",
  "properties": {
    "category": {
      "type": "string",
      "enum": ["network", "database", "deployment", "resource"]
    },
    "severity": {
      "type": "string",
      "enum": ["SEV1", "SEV2", "SEV3", "SEV4"]
    },
    "reasoning": {
      "type": "string",
      "description": "1-2 concise technical sentences explaining why this category and severity apply."
    },
    "ranked_runbook_ids": {
      "type": "array",
      "items": { "type": "integer" },
      "minItems": 1,
      "maxItems": 3,
      "description": "Up to 3 IDs selected strictly from the provided candidate list."
    }
  },
  "required": ["category", "severity", "reasoning", "ranked_runbook_ids"]
}
```

Nilai fallback saat LLM gagal: `category: "unclassified"`, `severity: "SEV-PENDING"`, `reasoning: ""`, `ranked_runbook_ids: [fallback IDs dari lexical]`.

### 5.3 Kontrak JSON: Analytics Charts (`GET /api/analytics/charts`)

```json
{
  "category_distribution": { "network": 12, "database": 8, "deployment": 10, "resource": 6, "unclassified": 2 },
  "severity_distribution": { "SEV1": 3, "SEV2": 12, "SEV3": 15, "SEV4": 8, "SEV-PENDING": 2 },
  "incident_trend": [ {"day": "2026-11-15", "total": 5}, ... ],
  "summary": { "total_triages": 40, "fallback_rate": 0.15, "runbook_total": 35 }
}
```

Agregasi harus menerima `predicted_category = "unclassified"` dan `predicted_severity = "SEV-PENDING"` tanpa crash Chart.js.

---

## 6. Pemetaan Epic → Komponen Kode

| Epic | User Story | Komponen Utama | File Terlibat |
|---|---|---|---|
| E1 Sanitasi Log | US1.1 | Redactor service | `app/services/redactor.py`, `app/blueprints/triage.py` |
| E2 Klasifikasi & Severitas | US2.1 | Search + Triage service | `app/services/search_service.py`, `app/services/triage_service.py`, `app/extensions.py` (LLM client) |
| E3 Hybrid Search & Re-triage | US3.1, US3.2 | Search service + Runbook repo + Blueprint triase | `app/services/search_service.py`, `app/repositories/runbook_repo.py`, `app/blueprints/triage.py` |
| E4 Strict-RAG Chat | US4.1, US4.2 | Chat service + Runbook repo + Blueprint triase | `app/services/chat_service.py`, `app/repositories/runbook_repo.py`, `app/blueprints/triage.py` |
| E5 KB & Seeding | US5.1 | Seed script + Schema + Fetch/Normalize scripts | `scripts/seed.py`, `data/schema.sql`, `scripts/fetch/*.py`, `scripts/processing/normalize_runbooks.py` |
| E6 Dashboard Analitik | US6.1 | Analytics service + Log repo + Blueprint analitik | `app/services/analytics_service.py`, `app/repositories/log_repo.py`, `app/blueprints/analytics.py` |
| E7 Keamanan & Resiliensi | US7.1 | Extensions + Config + Blueprint | `app/extensions.py`, `app/config.py`, `app/blueprints/triage.py` |
| E8 Out of Scope | — | — | Tidak diimplementasikan v0.1-mvp |

---

## 7. State Management (Stateless Workspace)

Karena v0.1-mvp tidak memiliki autentikasi, state triase aktif disimpan di DOM (DOM-Anchored Hidden State), bukan server-side session:

* `<form id="workspace-state">` berisi hidden input:
  * `name="sanitized_log"` — log yang sudah disensor
  * `name="locked_runbook_ids"` — daftar ID runbook terkunci (comma-separated)
* Setiap HTMX action (`/chat`, `/triage/refine`) menggunakan `hx-include="#workspace-state"` untuk mengirim konteks aktif ke server.
* Keuntungan: multi-tab isolation, zero server memory, horizontal scalability tanpa session store.

---

## 8. Resilience & Graceful Degradation Matrix

| Failure Scenario | System Behavior (Fallback) | UX Impact |
|---|---|---|
| LLM API Timeout / Network Down | Bypass LLM re-ranking; return Top-3 raw from FTS5 BM25; category=`unclassified`, severity=`SEV-PENDING` | Triage <50ms, warning banner AI offline |
| LLM Rate Limit (HTTP 429) | Immediate fallback to FTS5 Top-3, no retry loop | Zero request hang; deterministic matches immediately |
| Malformed LLM JSON | Catch `JSONDecodeError`/`ValidationError`; fallback ke FTS5 Top-3, preserve valid fields if partial | No HTTP 500 |
| Zero FTS5 Matches | Relax query tokens (split camelCase/snake_case), retry once; if still empty, return top 3 most frequent in predicted category | User never sees empty screen |

---

## 9. Keamanan

1. **Pre-Processing Secret Redaction:** `redactor.py` berjalan sinkron sebelum log menyentuh SQLite atau keluar ke LLM API. Covers `Authorization: Bearer`, `sk-...` / `ghp_...`, `postgres://`/`mysql://` credentials, email, AWS keys, GitHub tokens.
2. **FTS5 Injection Guard:** Regex tokenizer strip non-alphanumeric (kecuali underscore dan titik dalam error code), join dengan `OR`, quote setiap token. Tidak ada raw user string dalam `MATCH`.
3. **CSRF & Payload Bounds:** `Flask-WTF CSRFProtect` global, token via `hx-headers` pada `<body>` di `base.html`, `MAX_CONTENT_LENGTH = 5000`.
4. **No Hardcoded Secrets:** `GEMINI_API_KEY` dan `SECRET_KEY` diambil eksklusif dari environment variables (`python-dotenv`).

---

## 10. Definisi Selesai (Definition of Done) v0.1-mvp

- [ ] Aplikasi berjalan lokal dengan `flask --app "app:create_app()" --debug run` tanpa dependensi eksternal selain LLM API.
- [ ] `scripts/seed.py` membuat `data/app.db` dari `data/schema.sql` dan memuat `data/seed_runbooks.json` (idempotent).
- [ ] Minimal 30–40 entri runbook di `data/seed_runbooks.json`, distribusi 4 kategori × 4 level severitas.
- [ ] Log dengan `Bearer` / connection string tersensor menjadi `<REDACTED>` sebelum diproses.
- [ ] Karakter khusus stack trace (`:`, `/`, `(`, `)`, `"`) tidak menyebabkan FTS5 syntax error.
- [ ] Explicit Re-triage memperbarui panel Top-3 via HTMX OOB dan menyisipkan pembatas chat `"--- Referensi Diperbarui ---"`.
- [ ] Saat LLM API dicabut / mati, aplikasi tetap menampilkan Top-3 FTS5 tanpa HTTP 500.
- [ ] Dashboard merender 3 grafik Chart.js dengan data akurat dari SQLite, termasuk nilai fallback `unclassified` / `SEV-PENDING`.

---

*Arsitek: `sre-triage-assistant` v0.1-mvp. Dokumen ini merupakan turunan dari `PRD2.md` dan konsisten dengan `DESIGN.md`, `ARCHITECTURE.md`, `DATA_FLOW.md`, `MVP.md`, dan `AGENTS.md`.*
