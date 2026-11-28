import re
import sqlite3
from typing import Any

from app.extensions import get_db

# Karakter yang diperbolehkan dalam token: alfanumerik, underscore, titik (untuk versi/ekstensi)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.]+")


def extract_fts_tokens(text: str) -> list[str]:
    """Ekstrak token aman dari teks mentah untuk query FTS5 MATCH.

    Menghapus seluruh operator sintaks FTS5 (`:`, `/`, `-`, `"`, `(`, `)`, `*`, dsb.)
    sehingga stack trace mentah tidak memicu sqlite3.OperationalError.
    Token yang terlalu pendek (<2 karakter) dibuang agar query tetap selektif.
    """
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text)
    seen: set[str] = set()
    unique: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if len(low) < 2 or low in seen:
            continue
        seen.add(low)
        unique.append(tok)
    return unique


def build_fts_query(text: str) -> str:
    """Bangun query FTS5 yang aman: token digabung dengan operator OR."""
    tokens = extract_fts_tokens(text)
    if not tokens:
        return ""
    # Bungkus token dalam tanda kutip ganda → diperlakukan sebagai frasa/literal,
    # sehingga karakter apa pun di dalamnya tidak boleh menafsirkan sintaks MATCH.
    quoted = [f'"{tok}"' for tok in tokens]
    return " OR ".join(quoted)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


class RunbookRepository:
    """Data Access Layer untuk runbook: FTS5 BM25 search & fetch by ID."""

    def search_top(self, raw_text: str, limit: int = 10) -> list[dict[str, Any]]:
        """Stage 1: BM25 lexical search. Mengembalikan list of dict berisi skor relevansi."""
        match_query = build_fts_query(raw_text)
        if not match_query:
            return []

        db = get_db()
        cur = db.execute(
            """
            SELECT r.id, r.title, r.category, r.severity, r.symptoms_log,
                   r.root_cause, r.resolution_steps, r.source_ref,
                   bm25(runbooks_fts, 5.0, 5.0, 5.0) AS score
            FROM runbooks_fts f
            JOIN runbooks r ON r.id = f.rowid
            WHERE runbooks_fts MATCH ?
            ORDER BY bm25(runbooks_fts, 5.0, 5.0, 5.0)
            LIMIT ?
            """,
            (match_query, limit),
        )
        return _rows_to_dicts(cur.fetchall())

    def get_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Ambil runbook penuh berdasarkan daftar ID, mempertahankan urutan input."""
        if not ids:
            return []
        db = get_db()
        placeholders = ",".join("?" for _ in ids)
        cur = db.execute(
            f"""
            SELECT id, title, category, severity, symptoms_log,
                   root_cause, resolution_steps, source_ref
            FROM runbooks WHERE id IN ({placeholders})
            """,
            tuple(ids),
        )
        found = _rows_to_dicts(cur.fetchall())
        by_id = {row["id"]: row for row in found}
        return [by_id[i] for i in ids if i in by_id]

    def get_any(self, limit: int = 3) -> list[dict[str, Any]]:
        """Fallback terakhir: runbook terbaru apa pun kategorinya."""
        db = get_db()
        cur = db.execute(
            """
            SELECT r.id, r.title, r.category, r.severity, r.symptoms_log,
                   r.root_cause, r.resolution_steps, r.source_ref, 0.0 AS score
            FROM runbooks r
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return _rows_to_dicts(cur.fetchall())

    def list_all(self) -> list[dict[str, Any]]:
        """Semua runbook yang tersedia di DB, urutan terbaru dulu."""
        db = get_db()
        cur = db.execute(
            """
            SELECT id, title, category, severity, source_ref, created_at,
                   root_cause, resolution_steps
            FROM runbooks
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def count_by_category(self) -> list[dict[str, Any]]:
        """Agregasi jumlah runbook per kategori (untuk dasbor yang memadukan seed + live)."""
        db = get_db()
        cur = db.execute(
            "SELECT category, COUNT(*) AS total FROM runbooks GROUP BY category ORDER BY total DESC"
        )
        return _rows_to_dicts(cur.fetchall())

    def count_by_severity(self) -> list[dict[str, Any]]:
        db = get_db()
        cur = db.execute(
            "SELECT severity, COUNT(*) AS total FROM runbooks GROUP BY severity ORDER BY severity"
        )
        return _rows_to_dicts(cur.fetchall())