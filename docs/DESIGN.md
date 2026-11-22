# **Technical Design & Contracts (`DESIGN.md`)**

## 1. Database Schema (`data/schema.sql`)
SQLite database configured with `WAL` mode and an external-content **FTS5 virtual table** kept in sync via database triggers.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. Primary Knowledge Base Table
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

-- 2. FTS5 Virtual Table for Lexical BM25 Search
CREATE VIRTUAL TABLE IF NOT EXISTS runbooks_fts USING fts5(
    title,
    symptoms_log,
    root_cause,
    content='runbooks',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- 3. Automatic FTS5 Synchronization Triggers
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

-- 4. Anonymized Triage History for Operational Analytics
CREATE TABLE IF NOT EXISTS triage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sanitized_query TEXT NOT NULL,
    redaction_count INTEGER DEFAULT 0,
    predicted_category TEXT NOT NULL,
    predicted_severity TEXT NOT NULL,
    top_runbook_ids TEXT NOT NULL, -- Comma-separated IDs e.g. "4,12,19"
    is_fallback INTEGER DEFAULT 0, -- 0 = LLM success, 1 = FTS5 fallback
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Catatan agregasi analitik: kolom `predicted_category` dan `predicted_severity` dapat menampung nilai fallback `"unclassified"` dan `"SEV-PENDING"` selain nilai standar (`network`/`database`/`deployment`/`resource` dan `SEV1`–`SEV4`) ketika LLM gagal atau timeout. Semua kueri agregasi di `analytics_service.py` harus memperhitungkan kedua nilai ini agar visualisasi Chart.js di dashboard tidak rusak saat graceful degradation aktif.

---

## 2. LLM Prompt & Structured Output Contracts

### Contract A: Triage Classification & Re-ranking (`triage_service.py`)
* **Model:** `gemini-2.5-flash` (configured with `response_mime_type="application/json"` and strict Pydantic `response_schema`).
* **JSON Output Schema:**
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
      "description": "Up to 3 IDs selected strictly from the provided candidate list, ordered from most to least relevant."
    }
  },
  "required": ["category", "severity", "reasoning", "ranked_runbook_ids"]
}
```

### Contract B: Strict-RAG Scoped Assistant (`chat_service.py`)
* **System Instruction Guardrails:**
  ```text
  You are an SRE Incident Mitigation Assistant.
  STRICT RULE: Answer the user's request using ONLY the 3 Reference Runbooks provided below.
  - Do NOT invent commands, configuration flags, or infrastructure steps not present in the references.
  - If the user asks about topics unrelated to the active incident or missing from the references, state clearly: "Informasi tersebut tidak tersedia dalam 3 referensi runbook yang sedang aktif."
  - Respond in the same language used by the user (Indonesian or English), keeping technical terms intact.
  ```
* **Quick Prompts Mapping (Server-Side Expansion):**
  * `action="checklist"` $\rightarrow$ *"Buatkan checklist langkah mitigasi dan verifikasi secara berurutan berdasarkan referensi aktif."*
  * `action="compare"` $\rightarrow$ *"Bandingkan akar masalah (root cause) dan gejala dari ketiga referensi runbook di atas."*
  * `action="status_draft"` $\rightarrow$ *"Buatkan draf pengumuman status insiden singkat dan profesional untuk tim di Slack/Teams."*

---

## 3. Flask & HTMX Endpoint Contracts

| Method & Route | Request Payload (`form-data`) | Primary Target (`hx-target`) | Out-of-Band Swaps (`hx-swap-oob`) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `GET /` | None | Full Page (`workspace.html`) | None | Renders empty 2-column triage workspace. |
|| `POST /triage` | `raw_log` (string) | `#triage-output-area` | `#top3-reference-panel`, `#workspace-state` | Runs redaction, FTS5 + LLM triage, saves analytics log, unlocks chat. |
| `POST /triage/refine` | `refine_note`, `sanitized_log`, `locked_runbook_ids` | `#chat-messages` (`beforeend`) | `#top3-reference-panel`, `#workspace-state` | Appends context divider to chat and updates Top-3 panel + hidden IDs. |
| `POST /chat` | `message` OR `quick_action`, `locked_runbook_ids` | `#chat-messages` (`beforeend`) | None | Appends user bubble + Strict-RAG assistant response bubble. |
| `GET /dashboard` | None | Full Page (`dashboard.html`) | None | Renders analytics dashboard shell. |
| `GET /api/analytics/charts` | None | JSON Response | None | Mengembalikan agregasi hitungan berdasarkan kategori, severitas, dan tren harian. Agregasi harus mendukung nilai fallback `"unclassified"` dan `"SEV-PENDING"` selain kategori (`network`/`database`/`deployment`/`resource`) dan severitas standar (`SEV1`–`SEV4`) agar visualisasi Chart.js tidak rusak saat degradation. |

---

## 4. UI Layout & Wireframe (`workspace.html`)

```text
+---------------------------------------------------------------------------------------------------+
| [SRE Triage Assistant]                                              [Workspace]  [Dashboard]    |
+-------------------------------------------------------+-------------------------------------------+
| LEFT COLUMN (60%): Triage & Scoped Chat               | RIGHT COLUMN (40%): Locked Top-3 Runbooks |
|                                                       |                                           |
| +---------------------------------------------------+ | +---------------------------------------+ |
| | Paste Error Log / Stack Trace:                    | | | #1 [SEV2] [deployment]                | |
| | [                                               ] | | | Upstream 502 After Rolling Update     | |
| | [ Analyze Incident ]                            | | | Root Cause: Pod readiness probe...  | |
| +---------------------------------------------------+ | | [View Full Resolution Steps ▼]        | |
|                                                       | +---------------------------------------+ |
| +---------------------------------------------------+ |                                           |
| | TRIAGE RESULT: [deployment] [SEV2]                | | +---------------------------------------+ |
| | 🔒 2 secret(s) redacted automatically.            | | | #2 [SEV2] [network]                   | |
| | Reasoning: Upstream connection reset immediately  | | | Nginx Keepalive Timeout Mismatch      | |
| | after service deployment indicates rollout issue. | | | Root Cause: Gunicorn worker timeout... | |
| +---------------------------------------------------+ | | [View Full Resolution Steps ▼]        | |
|                                                       | +---------------------------------------+ |
| +---------------------------------------------------+ |                                           |
| | SCOPED MITIGATION CHAT (Locked to Top-3)          | | +---------------------------------------+ |
| | Quick: [Checklist] [Compare Causes] [Status Draft]| | | #3 [SEV3] [deployment]                | |
| | ------------------------------------------------- | | | Container Port Binding Mismatch       | |
| | Bot: Based on Runbook #1, first verify...         | | | [View Full Resolution Steps ▼]        | |
| | --- Referensi Diperbarui ---                      | | +---------------------------------------+ |
| | ------------------------------------------------- | |                                           |
| | [Ask about these 3 runbooks...         ] [Send]   | | +---------------------------------------+ |
| | [Refine context: e.g. OOMKilled...     ] [Refine] | | | Hidden State: #workspace-state        | |
| +---------------------------------------------------+ | +---------------------------------------+ |
+-------------------------------------------------------+-------------------------------------------+
```