# **AI Coding Agent Guidelines (`AGENTS.md`)**

## 1. Project Identity & Tech Stack
You are building **`sre-triage-assistant` (`v0.1-mvp`)**, a Python web application for automated SRE incident triage and runbook retrieval.
* **Language:** Python 3.11+
* **Web Framework:** Flask (Application Factory pattern + Blueprints)
* **Database:** SQLite3 (`sqlite3` standard library) with **FTS5** full-text search
* **Frontend / Interactivity:** Jinja2 templates + **HTMX** (via CDN) + **Tailwind CSS** (via CDN) + **Chart.js** (via CDN)
* **LLM Integration:** `google-genai` SDK (`gemini-2.5-flash`) with Structured Outputs

---

## 2. Strict Architectural Boundaries (DO & DO NOT)
* **DO NOT implement Authentication:** User registration, login, password hashing, and user profile pages are explicitly out of scope for `v0.1-mvp`. Use stateless DOM hidden inputs (`#workspace-state`) for tracking active triage context.
* **DO NOT put SQL or LLM calls in Blueprints:** `app/blueprints/*.py` must only handle HTTP request parsing, form/CSRF validation, calling `app/services/*`, and returning `render_template(...)`.
* **DO NOT pass raw user strings to SQLite FTS5 `MATCH`:** Raw logs contain punctuation (`:`, `/`, `-`, `"`, `(`, `)`) that trigger FTS5 syntax errors. Always sanitize queries through a dedicated token extractor before executing `MATCH`.
* **DO NOT let LLM failures crash the app:** Every call to the Gemini API must be wrapped in `try...except` with a 10-second timeout and fall back gracefully to raw SQLite FTS5 results.
* **DO NOT store secrets in code:** Load `GEMINI_API_KEY` and `SECRET_KEY` exclusively from environment variables (`python-dotenv`).

---

## 3. Security & Data Hygiene Mandates
1. **Redaction First:** Every incoming log or refinement note must pass through `app/services/redactor.py` (`redact_secrets(text)`) **before** being logged, searched, or sent to any external API.
2. **Parameterized SQL:** Always use `?` placeholders for SQLite parameter binding. Never use f-strings to interpolate user values into SQL queries.
3. **CSRF Protection:** Enable `Flask-WTF` `CSRFProtect` globally and attach the CSRF token to all HTMX requests via `hx-headers` on the `<body>` tag in `base.html`.

---

## 4. Coding Conventions & File Naming
* **Python Style:** Follow PEP 8, use `snake_case` for functions/variables, `PascalCase` for classes/Pydantic schemas, and include Python type hints on all service and repository functions.
* **Template Partials:** Prefix all HTMX partial templates inside `app/templates/partials/` with a leading underscore (e.g., `_triage_result.html`, `_top3_panel.html`, `_chat_message.html`).
* **Repository Return Types:** Repositories (`app/repositories/*.py`) must convert `sqlite3.Row` objects into standard Python `dict` or `@dataclass` instances before returning them to services.

---

## 5. Development & Verification Commands
* **Initialize & Seed Database:**
  ```bash
  python scripts/seed.py
  ```
* **Run Development Server:**
  ```bash
  flask --app run.py --debug run
  ```
* **Run Automated Tests:**
  ```bash
  pytest -v
  ```