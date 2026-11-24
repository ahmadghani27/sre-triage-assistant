"""HTTP layer triase & chat (request parsing + render_template saja)."""

from flask import Blueprint, render_template, request, url_for, jsonify

from app.services.triage_service import TriageService
from app.services.chat_service import ChatService
from app.repositories.history_repo import HistoryRepository
from app.repositories.runbook_repo import RunbookRepository

triage_bp = Blueprint("triage", __name__)

_triage_service: TriageService | None = None
_chat_service: ChatService | None = None
_history_repo: HistoryRepository | None = None
_runbook_repo: RunbookRepository | None = None


def _get_triage_service() -> TriageService:
    global _triage_service
    if _triage_service is None:
        _triage_service = TriageService()
    return _triage_service


def _get_chat_service() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


def _get_history_repo() -> HistoryRepository:
    global _history_repo
    if _history_repo is None:
        _history_repo = HistoryRepository()
    return _history_repo


@triage_bp.get("/")
def index():
    return render_template("workspace.html")


@triage_bp.post("/triage")
def triage():
    raw_log = (request.form.get("raw_log") or "").strip()
    if not raw_log:
        return (
            render_template("partials/_error.html", message="Log insiden tidak boleh kosong."),
            200,
            {"HX-Retarget": "#triage-output-area"},
        )

    result = _get_triage_service().run(raw_log)
    locked_ids = ",".join(str(i) for i in result.ranked_ids)

    partial = render_template(
        "partials/_triage_result.html",
        result=result,
        sanitized_log=result.sanitized_log,
        locked_ids=locked_ids,
    )
    # OOB swap: panel kanan Top-3 + hidden state, dikirim dalam satu respons
    top3 = render_template(
        "partials/_top3_panel.html",
        runbooks=result.top_runbooks,
        oob=True,
    )
    state = render_template(
        "partials/_workspace_state.html",
        sanitized_log=result.sanitized_log,
        locked_ids=locked_ids,
        category=result.category,
        severity=result.severity,
        oob=True,
    )
    return partial + top3 + state


@triage_bp.post("/triage/refine")
def refine():
    sanitized_log = (request.form.get("sanitized_log") or "").strip()
    refine_note = (request.form.get("refine_note") or "").strip()
    if not sanitized_log or not refine_note:
        return render_template(
            "partials/_error.html", message="Konteks awal atau catatan refine kosong."
        )

    result = _get_triage_service().refine(sanitized_log, refine_note)
    locked_ids = ",".join(str(i) for i in result.ranked_ids)

    divider = render_template("partials/_context_divider.html")
    triage_partial = render_template(
        "partials/_triage_result.html",
        result=result,
        sanitized_log=result.sanitized_log,
        locked_ids=locked_ids,
        oob=True,
    )
    top3 = render_template(
        "partials/_top3_panel.html",
        runbooks=result.top_runbooks,
        oob=True,
    )
    state = render_template(
        "partials/_workspace_state.html",
        sanitized_log=result.sanitized_log,
        locked_ids=locked_ids,
        category=result.category,
        severity=result.severity,
        oob=True,
    )
    return divider + triage_partial + top3 + state


@triage_bp.post("/chat")
def chat():
    locked_ids_raw = (request.form.get("locked_runbook_ids") or "").strip()
    locked_ids = [int(i) for i in locked_ids_raw.split(",") if i.strip().isdigit()]

    message = (request.form.get("message") or "").strip()
    quick_action = (request.form.get("quick_action") or "").strip()

    payload = _get_chat_service().answer(locked_ids, message or None, quick_action or None)

    user_bubble = ""
    if payload["user_message"]:
        user_bubble = render_template("partials/_chat_message.html", role="user", text=payload["user_message"])
    assistant_bubble = render_template(
        "partials/_chat_message.html", role="assistant", text=payload["answer"]
    )
    return user_bubble + assistant_bubble


@triage_bp.post("/triage/save-report")
def save_report():
    """Simpan hasil triase ke tabel triage_history agar tidak hilang saat refresh."""
    title = (request.form.get("title") or "").strip()
    query = (request.form.get("query") or "").strip()
    category = (request.form.get("category") or "").strip()
    severity = (request.form.get("severity") or "").strip()
    ids_raw = (request.form.get("top_runbook_ids") or "").strip()
    if not query or not category or not severity:
        return jsonify({"ok": False, "error": "Field wajib diisi"}), 400
    ids = [int(i) for i in ids_raw.split(",") if i.strip().isdigit()]
    hid = _get_history_repo().save(title, query, category, severity, ids)
    return jsonify({"ok": True, "id": hid})


@triage_bp.get("/triage/history")
def history():
    """Halaman daftar riwayat triase yang disimpan user (survives refresh)."""
    rows = _get_history_repo().list()
    return render_template("history.html", rows=rows)


def _get_runbook_repo() -> RunbookRepository:
    global _runbook_repo
    if _runbook_repo is None:
        _runbook_repo = RunbookRepository()
    return _runbook_repo


@triage_bp.post("/triage/history/<int:history_id>/delete")
def history_delete(history_id: int):
    """Hapus satu riwayat berdasarkan id."""
    ok = _get_history_repo().delete(history_id)
    return jsonify({"ok": ok})


@triage_bp.post("/triage/history/<int:history_id>/load")
def history_load(history_id: int):
    """Muat ulang riwayat ke workspace: query, top-3 runbook, category, severity."""
    row = _get_history_repo().get_by_id(history_id)
    if not row:
        return jsonify({"ok": False, "error": "Riwayat tidak ditemukan"}), 404
    ids = [int(i) for i in (row["top_runbook_ids"] or "").split(",") if i.strip().isdigit()]
    top_runbooks = _get_runbook_repo().get_by_ids(ids)
    top3_html = render_template(
        "partials/_top3_panel.html",
        runbooks=top_runbooks,
        oob=False,
    )
    return jsonify({
        "ok": True,
        "query": row["query"],
        "category": row["category"],
        "severity": row["severity"],
        "top_runbook_ids": ids,
        "top_runbooks": top_runbooks,
        "top3_html": top3_html,
    })

