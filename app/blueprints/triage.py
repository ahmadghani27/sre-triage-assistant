"""HTTP layer triase & chat (request parsing + render_template saja)."""

from flask import Blueprint, render_template, request, url_for

from app.services.triage_service import TriageService
from app.services.chat_service import ChatService

triage_bp = Blueprint("triage", __name__)

_triage_service: TriageService | None = None
_chat_service: ChatService | None = None


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