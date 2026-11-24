"""HTTP layer daftar runbook (read-only)."""

from flask import Blueprint, render_template

from app.repositories.runbook_repo import RunbookRepository

runbook_bp = Blueprint("runbook", __name__)

_repo: RunbookRepository | None = None


def _get_repo() -> RunbookRepository:
    global _repo
    if _repo is None:
        _repo = RunbookRepository()
    return _repo


@runbook_bp.get("/runbook")
def index():
    """Halaman daftar semua runbook yang tersedia di database."""
    rows = _get_repo().list_all()
    return render_template("runbook_list.html", rows=rows)
