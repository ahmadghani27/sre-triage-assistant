"""Test: HistoryRepository save/list/get_by_id on triage_history table."""

from app.repositories.history_repo import HistoryRepository


def _in_app_context(app, fn):
    with app.app_context():
        return fn()


def test_history_repo_save_and_list(app):
    def run():
        repo = HistoryRepository()
        hid = repo.save("Laporan Nginx", "nginx timeout", "network", "SEV3", [1, 2, 3])
        rows = repo.list()
        assert len(rows) == 1
        assert rows[0]["title"] == "Laporan Nginx"
        assert rows[0]["query"] == "nginx timeout"
        assert rows[0]["id"] == hid
        return hid

    _in_app_context(app, run)


def test_history_repo_get_by_id(app):
    def run():
        repo = HistoryRepository()
        hid = repo.save("Laporan Postgres", "postgres pool exhaustion", "database", "SEV1", [4])
        row = repo.get_by_id(hid)
        assert row is not None
        assert row["id"] == hid
        assert row["title"] == "Laporan Postgres"
        assert row["category"] == "database"
        assert row["severity"] == "SEV1"
        assert row["top_runbook_ids"] == "4"
        assert repo.get_by_id(999999) is None

    _in_app_context(app, run)
