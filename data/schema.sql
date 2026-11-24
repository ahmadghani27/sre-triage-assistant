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

CREATE TABLE IF NOT EXISTS triage_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    top_runbook_ids TEXT NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);