"""Unit test untuk graceful degradation (NFR — MVP.md Definition of Done).

Ketika LLM tidak tersedia (timeout / 429 / JSON invalid), sistem WAJIB
jatuh ke peringkat lexical FTS5 murni tanpa HTTP 500 dan tetap menampilkan
Top-3 runbook.
"""

from app.repositories.runbook_repo import RunbookRepository
from app.services.chat_service import ChatService
from app.services.search_service import SearchService
from app.services.triage_service import TriageService

SECRET_LOG = (
    "2026-11-20T03:14:02Z error nginx upstream timed out 502 Bad Gateway after deploy "
    "payment-service\nAuthorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\n"
    "postgres://app_user:sup3rsecret@db.internal:5432/prod"
)


class TestTriageFallback:
    def test_llm_off_still_returns_top3_no_crash(self, app):
        with app.app_context():
            result = TriageService().run(SECRET_LOG)

        assert result.is_fallback is True
        assert 1 <= len(result.top_runbooks) <= 3
        assert len(result.ranked_ids) == len(result.top_runbooks)
        assert result.category == "unclassified"
        assert result.severity == "SEV-PENDING"
        assert result.reasoning == ""
        assert all(
            r["category"] in {"network", "database", "deployment", "resource"}
            for r in result.top_runbooks
        )

    def test_fallback_result_is_redacted(self, app):
        with app.app_context():
            result = TriageService().run(SECRET_LOG)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.sanitized_log
        assert "sup3rsecret" not in result.sanitized_log
        assert result.redaction_count >= 2

    def test_fallback_ranked_ids_match_lexical_order(self, app):
        with app.app_context():
            candidates = SearchService().lexical_search("nginx 502 gateway")
            result = TriageService().run("nginx 502 gateway upstream")
        assert result.ranked_ids == [c["id"] for c in candidates[:3]]

    def test_fallback_runbooks_carry_resolution_steps(self, app):
        with app.app_context():
            result = TriageService().run("nginx 502 Bad Gateway upstream timeout")
        assert all(r["resolution_steps"].strip() for r in result.top_runbooks)

    def test_zero_match_input_still_returns_results(self, app):
        with app.app_context():
            result = TriageService().run("qwertzuiop asdfghjkl zxcvbnm")
        assert result.is_fallback is True
        assert len(result.top_runbooks) >= 1


class TestTriagePersistence:
    def test_triage_log_saved_with_fallback_flag(self, app):
        from app.extensions import get_db

        with app.app_context():
            TriageService().run(SECRET_LOG)
            db = get_db()
            row = db.execute(
                "SELECT predicted_category, predicted_severity, is_fallback, "
                "redaction_count, top_runbook_ids FROM triage_logs "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()

        assert row["is_fallback"] == 1
        assert row["redaction_count"] >= 2
        assert row["top_runbook_ids"]
        assert "," in row["top_runbook_ids"]

    def test_refine_combines_context_and_reruns(self, app):
        with app.app_context():
            service = TriageService()
            first = service.run("nginx 502 gateway")
            refined = service.refine(first.sanitized_log, "ternyata pod terkena OOMKilled")

        assert refined.is_fallback is True
        assert len(refined.top_runbooks) == 3
        assert any(r["category"] == "resource" for r in refined.top_runbooks)


class TestChatFallback:
    def test_quick_action_uses_locked_runbooks(self, app):
        with app.app_context():
            ids = [r["id"] for r in RunbookRepository().get_any(limit=3)]
            payload = ChatService().answer(ids, message=None, quick_action="checklist")

        assert payload["is_fallback"] is True
        assert payload["user_message"]
        assert "ecklist" in payload["answer"]
        assert "#1" in payload["answer"]

    def test_quick_action_status_draft(self, app):
        with app.app_context():
            payload = ChatService().answer([1, 2, 3], message=None, quick_action="status_draft")
        assert "status" in payload["answer"].lower() or "insiden" in payload["answer"].lower()

    def test_chat_without_locked_runbooks_does_not_crash(self, app):
        with app.app_context():
            payload = ChatService().answer([], message="apa pun", quick_action=None)
        assert payload["answer"]
        assert payload["is_fallback"] is True

    def test_unknown_quick_action_falls_back_to_message(self, app):
        prompt, is_quick = ChatService.expand_quick_action("bogus", "  pertanyaan user  ")
        assert is_quick is False
        assert prompt == "pertanyaan user"
