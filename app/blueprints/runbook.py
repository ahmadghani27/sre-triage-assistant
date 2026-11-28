"""HTTP layer daftar runbook (read-only)."""

from flask import Blueprint, render_template, request

from app.repositories.runbook_repo import RunbookRepository

runbook_bp = Blueprint("runbook", __name__)

_repo: RunbookRepository | None = None


def _get_repo() -> RunbookRepository:
    global _repo
    if _repo is None:
        _repo = RunbookRepository()
    return _repo


PAGE_SIZES = (25, 50, 100)


@runbook_bp.get("/runbook")
def index():
    """Halaman daftar semua runbook yang tersedia di database."""
    page = request.args.get("page", type=int, default=1)
    page_size_raw = request.args.get("page_size", default="all")
    if page_size_raw == "all":
        page_size: int | None = None
    else:
        try:
            page_size = int(page_size_raw)
            if page_size not in PAGE_SIZES:
                page_size = 25
        except (TypeError, ValueError):
            page_size = 25
    rows = _get_repo().list_all(page=page, page_size=page_size)
    total = len(_get_repo().list_all(page_size=None))
    if page_size:
        total_pages = max(1, (total + page_size - 1) // page_size)
    else:
        total_pages = 1
    has_prev = page > 1
    has_next = page_size and page < total_pages
    return render_template(
        "runbook_list.html",
        rows=rows,
        page=page,
        page_size=page_size or "all",
        page_sizes=PAGE_SIZES,
        total=total,
        total_pages=total_pages,
        has_prev=has_prev,
        has_next=has_next,
    )
