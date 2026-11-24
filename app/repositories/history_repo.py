"""Data Access Layer untuk riwayat triase yang disimpan user (triage_history)."""

from typing import Any

from app.extensions import get_db


class HistoryRepository:
    """Data Access Layer untuk riwayat triase yang disimpan user (triage_history)."""

    def save(
        self,
        title: str,
        query: str,
        category: str,
        severity: str,
        top_runbook_ids: list[int],
    ) -> int:
        db = get_db()
        cur = db.execute(
            """
            INSERT INTO triage_history (title, query, category, severity, top_runbook_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                title or "Tanpa Judul",
                query,
                category,
                severity,
                ",".join(str(i) for i in top_runbook_ids),
            ),
        )
        db.commit()
        return int(cur.lastrowid)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        db = get_db()
        cur = db.execute(
            """
            SELECT id, title, query, category, severity, top_runbook_ids, created_at
            FROM triage_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_by_id(self, history_id: int) -> dict[str, Any] | None:
        db = get_db()
        row = db.execute(
            """
            SELECT id, title, query, category, severity, top_runbook_ids, created_at
            FROM triage_history
            WHERE id = ?
            """,
            (history_id,),
        ).fetchone()
        return dict(row) if row else None
