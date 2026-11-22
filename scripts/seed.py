"""Idempotent database seeder for sre-triage-assistant (v0.1-mvp).

Inisialisasi data/app.db dari data/schema.sql lalu memuat
data/seed_runbooks.json (INSERT OR IGNORE via content_hash untuk
anti-duplikasi lintas batch). Tidak menggunakan sentence-transformers /
embedding — FTS5 porter unicode61 adalah indeks pencarian tunggal MVP.

Dipanggil:
    python scripts/seed.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "app.db")
SCHEMA_PATH = os.path.join(DATA_DIR, "schema.sql")
SEED_PATH = os.path.join(DATA_DIR, "seed_runbooks.json")

RUNBOOK_COLUMNS = [
    "title",
    "category",
    "severity",
    "symptoms_log",
    "root_cause",
    "resolution_steps",
    "source_ref",
    "content_hash",
]

VALID_CATEGORIES = {"network", "database", "deployment", "resource"}
VALID_SEVERITIES = {"SEV1", "SEV2", "SEV3", "SEV4"}
REQUIRED_FIELDS = {"title", "category", "severity", "symptoms_log", "root_cause", "resolution_steps"}


def compute_hash(title: str, symptoms_log: str) -> str:
    raw = f"{title.strip().lower()}::{symptoms_log.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_record(record: dict[str, Any], idx: int) -> tuple[bool, str]:
    missing = [f for f in REQUIRED_FIELDS if not str(record.get(f, "")).strip()]
    if missing:
        return False, f"Baris #{idx}: field wajib kosong {missing}"

    category = str(record["category"]).strip().lower()
    if category not in VALID_CATEGORIES:
        return False, f"Baris #{idx}: category tidak valid '{category}'"

    severity = str(record["severity"]).strip().upper()
    if severity not in VALID_SEVERITIES:
        return False, f"Baris #{idx}: severity tidak valid '{severity}'"

    return True, "OK"


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(SCHEMA_PATH):
        raise FileNotFoundError(f"Schema SQL tidak ditemukan: {SCHEMA_PATH}")

    if not os.path.exists(SEED_PATH):
        raise FileNotFoundError(
            f"Seed file tidak ditemukan: {SEED_PATH}. "
            "Jalankan terlebih dahulu scripts/processing/normalize_runbooks.py"
        )

    with open(SEED_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise ValueError(f"Format {SEED_PATH} harus berupa JSON array.")

    conn = sqlite3.connect(DB_PATH)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        placeholders = ",".join("?" for _ in RUNBOOK_COLUMNS)
        insert_sql = f"""
            INSERT OR IGNORE INTO runbooks
                ({','.join(RUNBOOK_COLUMNS)})
            VALUES ({placeholders})
        """

        inserted = 0
        skipped = 0
        invalid = 0

        for idx, record in enumerate(records, start=1):
            is_valid, err_msg = validate_record(record, idx)
            if not is_valid:
                print(f"[warn] Melewati record invalid -> {err_msg}")
                invalid += 1
                continue

            title = record["title"].strip()
            symptoms_log = record["symptoms_log"].strip()
            category = record["category"].strip().lower()
            severity = record["severity"].strip().upper()
            content_hash = (
                str(record.get("content_hash", "")).strip()
                or compute_hash(title, symptoms_log)
            )

            values = (
                title,
                category,
                severity,
                symptoms_log,
                record["root_cause"].strip(),
                record["resolution_steps"].strip(),
                (record.get("source_ref") or "internal").strip(),
                content_hash,
            )

            cur = conn.execute(insert_sql, values)
            if cur.rowcount == 1:
                inserted += 1
            else:
                skipped += 1

        # Pastikan indeks FTS5 sinkron penuh dengan tabel utama
        total_runbooks = conn.execute("SELECT COUNT(*) FROM runbooks").fetchone()[0]
        total_fts = conn.execute("SELECT COUNT(*) FROM runbooks_fts").fetchone()[0]
        if total_runbooks != total_fts:
            conn.execute("INSERT INTO runbooks_fts(runbooks_fts) VALUES('rebuild')")

        cat_dist = dict(
            conn.execute("SELECT category, COUNT(*) FROM runbooks GROUP BY category").fetchall()
        )
        sev_dist = dict(
            conn.execute("SELECT severity, COUNT(*) FROM runbooks GROUP BY severity").fetchall()
        )

        conn.commit()
    finally:
        conn.close()

    print("=== Hasil Seeding Database ===")
    print(f"Database  : {DB_PATH}")
    print(f"Inserted  : {inserted} | Duplikat di-skip: {skipped} | Invalid: {invalid}")
    print(f"Total DB  : {total_runbooks} runbook (FTS5 indexed: {total_runbooks})")
    print(f"Kategori  : {cat_dist}")
    print(f"Severitas : {sev_dist}")


if __name__ == "__main__":
    main()