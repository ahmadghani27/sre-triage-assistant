# **System Architecture (`ARCHITECTURE.md`)**

## 1. Architectural Style & Core Principles
The `sre-triage-assistant` (`v0.1-mvp`) is designed as a **Modular Monolith** following **Hypermedia-Driven Application (HDA)** principles:
* **Strict Layered Separation:** HTTP routing (`blueprints`), business orchestration (`services`), and data persistence (`repositories`) are strictly decoupled. Routes never execute raw SQL or call external LLM SDKs directly.
* **Hypermedia over JSON SPA:** Instead of building a heavy client-side state store, the server renders HTML fragments (`partials/`) and updates multiple UI regions atomically using **HTMX Out-of-Band (OOB) Swaps**.
* **Offline-First Knowledge Base:** Runbook retrieval relies on an embedded **SQLite FTS5** engine. External LLM APIs are strictly used for reasoning, re-ranking, and natural language synthesis—never as the primary data store.
* **Graceful Degradation:** Any external API failure (timeout, quota exhaustion, malformed output) degrades cleanly into a deterministic local search experience without crashing the request lifecycle.

---

## 2. Project Directory Structure
```text
sre-triage-assistant/
├── app/
│   ├── __init__.py              # Flask Application Factory (create_app)
│   ├── config.py                # Environment & app configuration classes
│   ├── extensions.py            # SQLite connection helper, CSRFProtect, LLM client init
│   ├── blueprints/              # HTTP Layer (Request parsing & HTML response rendering)
│   │   ├── triage.py            # Routes: /, /triage, /triage/refine, /chat
│   │   └── analytics.py         # Routes: /dashboard, /api/analytics/charts
│   ├── services/                # Business Logic Layer (Pure Python orchestration)
│   │   ├── redactor.py          # Regex PII & secret masking engine
│   │   ├── search_service.py    # Hybrid search (FTS5 query sanitization + LLM re-rank)
│   │   ├── triage_service.py    # Incident classification & severity assessment
│   │   ├── chat_service.py      # Strict-RAG prompt assembly & synthesis
│   │   └── analytics_service.py # Aggregation logic for dashboard visualizations
│   ├── repositories/            # Data Access Layer (Raw SQL & FTS5 queries)
│   │   ├── runbook_repo.py      # FTS5 BM25 search & ID-based runbook fetching
│   │   └── log_repo.py          # Triage event persistence & analytics queries
│   ├── templates/
│   │   ├── base.html            # Base layout (Tailwind/Pico CDN + HTMX CDN)
│   │   ├── workspace.html       # Main 2-column triage & chat interface
│   │   ├── dashboard.html       # Operational analytics view
│   │   └── partials/            # HTMX swap fragments
│   │       ├── _triage_result.html    # Category, SEV badge, reasoning, & redaction notice
│   │       ├── _top3_panel.html       # Right-panel locked runbooks (supports OOB swap)
│   │       ├── _chat_message.html     # Single user/assistant chat bubble
│   │       └── _context_divider.html  # Visual separator upon Explicit Re-triage
│   └── static/
│       └── js/charts.js         # Chart.js / Plotly rendering logic
├── data/
│   ├── schema.sql               # DDL for tables, FTS5 virtual table, & triggers
│   ├── seed_runbooks.json       # Curated initial corpus (30-40 runbooks)
│   └── app.db                   # Local SQLite database file (gitignored)
├── scripts/
│   └── seed.py                  # Idempotent script to initialize DB & load seed data
├── tests/                       # Unit tests for redactor, FTS5 sanitizer, & fallbacks
├── .env.example                 # Template for GEMINI_API_KEY & SECRET_KEY
├── requirements.txt
└── run.py                       # Entry point
```

---

## 3. Core Request Lifecycles (Data Flow)

### Flow A: Initial Incident Triage (`POST /triage`)
1. **Validation & Redaction:** Flask-WTF validates the CSRF token and input length ($\le 5000$ chars). `redactor.py` strips sensitive patterns (Bearer tokens, DB URIs, API keys, emails) and replaces them with `<REDACTED>`.
2. **Lexical Retrieval (Stage 1):** `search_service.py` extracts alphanumeric tokens and error codes (e.g., `502`, `OOMKilled`, `ECONNREFUSED`) while stripping FTS5 syntax operators (`:`, `/`, `(`, `)`, `"`, `*`). `runbook_repo.py` executes a BM25 ranked query against `runbooks_fts` to fetch the **Top-10 candidates**.
3. **Semantic Triage & Re-ranking (Stage 2):** `triage_service.py` sends the *sanitized log* + *Top-10 candidate summaries* to the LLM API using Structured Output (JSON Schema) to determine:
   * Domain `category` (`network`, `database`, `deployment`, `resource`)
   * `severity` (`SEV1`–`SEV4`) & `reasoning`
   * `ranked_runbook_ids` (selecting the best **Top-3** from the 10 candidates)
4. **Persistence & Response:** The anonymized triage metadata is saved to `triage_logs` for analytics. Flask renders `_triage_result.html` (main target) alongside `_top3_panel.html` (`hx-swap-oob="true"`) and initializes the chat workspace.

```text
[User Raw Log] 
      │
      ▼ (POST /triage + CSRF)
[Regex Redactor] ──► Masks secrets to <REDACTED>
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
       [Top-3 Selected + Category/SEV]                      [Fallback: FTS5 Top-3 + "UNKNOWN" Badge]
                      │                                                     │
                      └──────────────────────────┬──────────────────────────┘
                                                 ▼
                                [Save to `triage_logs` & Render HTML]
                                 (Main Panel + OOB Right Panel Swap)
```

### Flow B: Explicit Re-triage (`POST /triage/refine`)
To prevent silent **context drift** during troubleshooting, the Top-3 references remain locked by default. Re-evaluation only occurs when explicitly triggered:
1. HTMX submits the user's new clarification text along with hidden state inputs (`original_sanitized_log` and `previous_runbook_ids`).
2. `redactor.py` sanitizes the new clarification text and concatenates it with `original_sanitized_log`.
3. `search_service.py` re-runs the **2-Stage Hybrid Search** (FTS5 Top-10 $\rightarrow$ LLM Re-rank Top-3).
4. The server returns a multi-part HTMX response:
   * Appends `_context_divider.html` (`"--- Referensi Diperbarui ---"`) into the chat stream.
   * Performs an **Out-of-Band Swap** (`hx-swap-oob="true"`) to replace the right-hand reference panel (`_top3_panel.html`) and update the hidden `locked_runbook_ids` input field.

### Flow C: Scoped Strict-RAG Chat (`POST /chat`)
1. HTMX submits the user's question (or quick-prompt action) plus the current `locked_runbook_ids` hidden input.
2. `runbook_repo.py` fetches the full `symptoms_log`, `root_cause`, and `resolution_steps` for those exact 3 IDs.
3. `chat_service.py` constructs a **Strict-RAG System Prompt** instructing the LLM to synthesize an answer *exclusively* from the 3 provided documents.
4. Flask returns `_chat_message.html` appended to the chat container.

---

## 4. State Management Strategy (Stateless Workspace)
Because `v0.1-mvp` omits user authentication, storing active triage state in server-side global variables or cookie sessions (`flask.session`) would cause state collisions if an engineer opens multiple browser tabs for concurrent incidents.

Instead, the architecture uses **DOM-Anchored Hidden State**:
* When `/triage` or `/triage/refine` renders the workspace, it embeds a `<form id="workspace-state">` containing:
  * `<input type="hidden" name="sanitized_log" value="...">`
  * `<input type="hidden" name="locked_runbook_ids" value="12,4,29">`
* Every subsequent HTMX action (`/chat` and `/triage/refine`) uses `hx-include="#workspace-state"` to pass the exact active context back to the server.
* **Trade-off:** Slightly larger form payloads (a few hundred bytes per request) in exchange for zero server memory overhead, multi-tab isolation, and effortless horizontal scalability.

---

## 5. Security & Input Hardening Layers
1. **Pre-Processing Secret Redaction (`redactor.py`):** Runs synchronously before any log touches SQLite or leaves the network boundary to an LLM API. Covers `Authorization: Bearer`, `sk-...` / `ghp_...` keys, `postgres://` / `mysql://` credentials, and email patterns.
2. **FTS5 Injection & Syntax Guard:** SQLite FTS5 `MATCH` queries interpret punctuation (`-`, `:`, `*`, `"`, `(`, `)`) as boolean/column operators. A dedicated regex tokenizer strips non-alphanumeric characters (preserving underscores and dots inside error codes) and joins tokens with `OR` operators so raw stack traces never raise `sqlite3.OperationalError`.
3. **CSRF & Payload Bounds:** `Flask-WTF` enforces CSRF tokens across all `POST` endpoints (injected via `hx-headers` in `base.html`), while `MAX_CONTENT_LENGTH` prevents oversized log payloads.

---

## 6. Resilience & Graceful Degradation Matrix
External LLM calls are wrapped in a strict timeout (`timeout=10.0s`) and exception handler (`try/except`) inside `triage_service.py` and `chat_service.py`:

| Failure Scenario | System Behavior (Fallback Strategy) | User Experience Impact |
| :--- | :--- | :--- |
| **LLM API Timeout / Network Down** | Bypass LLM re-ranking. Return the top 3 raw results directly from SQLite FTS5 BM25 scores. Set category to `unclassified` and severity to `SEV-PENDING`. | Triage still succeeds in $<50\text{ms}$ with local runbooks visible; subtle warning banner indicates AI synthesis is offline. |
| **LLM Rate Limit (`HTTP 429`)** | Immediate fallback to FTS5 Top-3 without retry loops (avoids blocking Flask worker threads). | Zero request hanging; user immediately receives deterministic runbook matches. |
| **Malformed LLM JSON Response** | Catch `ValidationError` / `JSONDecodeError`; fallback to FTS5 Top-3 ordering while preserving valid fields if partial. | Prevents HTTP 500 Internal Server Error. |
| **Zero FTS5 Matches (`0 rows`)** | Relax query tokens (split camelCase/snake_case error codes) and retry once; if still empty, return top 3 most frequent runbooks in the predicted category. | User is never left with an empty screen. |