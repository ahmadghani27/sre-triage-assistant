"""Test: data/schema.sql contains triage_history table DDL."""

import sqlite3


def test_schema_contains_triage_history_table():
    conn = sqlite3.connect(":memory:")
    conn.executescript(open("data/schema.sql").read())
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='triage_history'"
    ).fetchall()
    assert len(tables) == 1
