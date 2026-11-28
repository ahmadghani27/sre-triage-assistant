"""Agregasi untuk dasbor operasional: menggabungkan riwayat triase sesi
dengan distribusi knowledge base agar grafik tetap terisi saat demo
(lihat MVP.md §4: seed + riwayat triase sesi)."""

from typing import Any

from app.repositories.log_repo import LogRepository
from app.repositories.runbook_repo import RunbookRepository

_SEVERITY_ORDER = ["SEV1", "SEV2", "SEV3", "SEV4"]


class AnalyticsService:
    def __init__(
        self,
        log_repo: LogRepository | None = None,
        runbook_repo: RunbookRepository | None = None,
    ) -> None:
        self.log_repo = log_repo or LogRepository()
        self.runbook_repo = runbook_repo or RunbookRepository()

    def category_distribution(self) -> dict[str, int]:
        """Distribusi kategori: triase riwayat sesi + seed KB sebagai basis demo."""
        totals: dict[str, int] = {}
        for row in self.runbook_repo.count_by_category():
            totals[row["category"]] = totals.get(row["category"], 0) + int(row["total"])
        for row in self.log_repo.count_by_category():
            totals[row["category"]] = totals.get(row["category"], 0) + int(row["total"])
        return dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))

    def severity_distribution(self) -> dict[str, int]:
        totals: dict[str, int] = {sev: 0 for sev in _SEVERITY_ORDER}
        for row in self.runbook_repo.count_by_severity():
            totals[row["severity"]] = totals.get(row["severity"], 0) + int(row["total"])
        for row in self.log_repo.count_by_severity():
            totals[row["severity"]] = totals.get(row["severity"], 0) + int(row["total"])
        return totals

    def incident_trend(self, days: int = 14) -> list[dict[str, Any]]:
        rows = self.log_repo.count_by_day(days=days)
        return [
            {"day": row["day"], "total": int(row["total"])}
            for row in reversed(rows)
            if row["day"]
        ]

    def summary(self) -> dict[str, Any]:
        return {
            "total_triages": self.log_repo.count_total(),
            "fallback_rate": self.log_repo.fallback_rate(),
            "runbook_total": sum(int(r["total"]) for r in self.runbook_repo.count_by_category()),
        }