sre-triage-assistant/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── extensions.py
│   ├── blueprints/
│   │   ├── analytics.py
│   │   └── triage.py
│   ├── repositories/
│   │   ├── log_repo.py
│   │   └── runbook_repo.py
│   └── services/
│       ├── analytics_service.py
│       ├── chat_service.py
│       ├── redactor.py
│       ├── search_service.py
│       └── triage_service.py
├── data/
│   ├── app.db
│   ├── schema.sql
│   └── seed_runbooks.json
├── docs/
│   ├── AGENTS.md
│   ├── ARCHI.md
│   ├── ARCHITECTURE.md
│   ├── CLEAN_CODE_GUARD_REPORT.md
│   ├── DATA_FLOW.md
│   ├── DESIGN.md
│   ├── MVP.md
│   ├── PRD.md
│   ├── PRD2.md
│   └── STRUKTUR_DIREKTORI.md
├── scripts/
│   ├── fetch/
│   │   ├── fetch_prometheus_runbooks.py
│   │   └── fetch_stackexchange.py
│   ├── processing/
│   │   └── normalize_runbooks.py
│   └── seed.py
├── requirements.txt
└── tests/
