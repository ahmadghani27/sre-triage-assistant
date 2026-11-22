from typing import Any

from app.extensions import get_db


class LogRepository:
    """Data Access Layer untuk riwayat triase anonim & kueri agregasi analitik."""

    def save(
        self,
        sanitized_query: str,
        redaction_count: int,
        predicted_category: str,
        predicted_severity: str,
        top_runbook_ids: list[int],
        is_fallback: bool,
    ) -> int:
        db = get_db()
        cur = db.execute(
            """
            INSERT INTO triage_logs
                (sanitized_query, redaction_count, predicted_category,
                 predicted_severity, top_runbook_ids, is_fallback)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sanitized_query,
                redaction_count,
                predicted_category,
                predicted_severity,
                ",".join(str(i) for i in top_runbook_ids),
                1 if is_fallback else 0,
            ),
        )
        db.commit()
        return int(cur.lastrowid)

    def count_by_category(self) -> list[dict[str, Any]]:
        db = get_db()
        cur = db.execute(
            """
            SELECT predicted_category AS category, COUNT(*) AS total
            FROM triage_logs
            GROUP BY predicted_category ORDER BY total DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def count_by_severity(self) -> list[dict[str, Any]]:
        db = get_db()
        cur = db.execute(
            """
            SELECT predicted_severity AS severity, COUNT(*) AS total
            FROM triage_logs
            GROUP BY predicted_severity ORDER BY severity
            """
        )
        return [dict(row) for row in cur.fetchall()]

    def count_by_day(self, days: int = 14) -> list[dict[str, Any]]:
        db = get_db()
        cur = db.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS total
            FROM triage_logs
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) DESC
            LIMIT ?
            """,
            (days,),
        )
        return [dict(row) for row in cur.fetchall()]

    def count_total(self) -> int:
        db = get_db()
        row = db.execute("SELECT COUNT(*) AS total FROM triage_logs").fetchone()
        return int(row["total"])

    def fallback_rate(self) -> float:
        db = get_db()
        row = db.execute(
            """
            SELECT
                CASE WHEN COUNT(*) = 0 THEN 0.0
                     ELSE ROUND(1.0 * SUM(is_fallback) / COUNT(*), 4) END AS rate
            FROM triage_logs
            """
        ).fetchone()
        return float(row["rate"])