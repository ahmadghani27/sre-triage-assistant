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
        # Saat LLM offline, severity diambil dari runbook teratas hasil
        # pencarian lexical (bukan selalu SEV-PENDING).
        assert result.severity == "SEV2"
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


class TestChatServiceLocalAnswers:
    """Tes untuk fungsi pendek _local_answer per quick_action."""

    def _runbooks(self):
        return [
            {
                "id": 1,
                "title": "Runbook A",
                "category": "network",
                "severity": "SEV2",
                "symptoms_log": "502 Bad Gateway",
                "root_cause": "upstream mismatch",
                "resolution_steps": "1. Drain old pods\n2. Verify nginx upstream\n3. Roll back if mismatch",
            },
            {
                "id": 2,
                "title": "Runbook B",
                "category": "database",
                "severity": "SEV1",
                "symptoms_log": "pool exhausted",
                "root_cause": "max_connections exceeded",
                "resolution_steps": "1. Identify idle connections\n2. Terminate idle backends\n3. Introduce PgBouncer",
            },
        ]

    def test_local_checklist_returns_steps_per_runbook(self, app):
        from app.services.chat_service import ChatService

        answer = ChatService._local_checklist(self._runbooks())
        assert "Checklist mitigasi" in answer
        assert "#1 Runbook A" in answer
        assert "#2 Runbook B" in answer
        assert "Drain old pods" in answer
        assert "Introduce PgBouncer" in answer

    def test_local_checklist_empty_runbooks(self, app):
        from app.services.chat_service import ChatService

        answer = ChatService._local_checklist([])
        assert "Checklist mitigasi" in answer

    def test_local_compare_returns_root_cause_and_symptoms(self, app):
        from app.services.chat_service import ChatService

        answer = ChatService._local_compare(self._runbooks())
        assert "Perbandingan" in answer
        assert "Runbook A" in answer
        assert "upstream mismatch" in answer
        assert "max_connections exceeded" in answer

    def test_local_status_draft_uses_first_runbook(self, app):
        from app.services.chat_service import ChatService

        answer = ChatService._local_status_draft(self._runbooks())
        assert "Runbook A" in answer
        assert "network" in answer
        assert "SEV2" in answer

    def test_local_status_draft_empty_runbooks(self, app):
        from app.services.chat_service import ChatService

        answer = ChatService._local_status_draft([])
        assert answer  # tidak crash meski kosong


class TestSearchServiceExtractedHelpers:
    """Tes untuk fungsi-fungsi pendek yang diekstrak dari classify_and_rerank."""

    def test_build_json_schema_has_required_properties(self):
        from app.services.search_service import SearchService

        schema = SearchService._build_json_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == {
            "category",
            "severity",
            "reasoning",
            "ranked_runbook_ids",
        }
        assert set(schema["properties"].keys()) == set(schema["required"])

    def test_build_llm_payload_keys(self):
        from app.services.search_service import SearchService

        candidates = [{"id": 1, "title": "x", "category": "network", "severity": "SEV1", "symptoms_log": "err"}]
        payload = SearchService._build_llm_payload("nginx 502 error", candidates)
        assert payload["sanitized_log"] == "nginx 502 error"
        assert payload["candidates"] == [{"id": 1, "title": "x", "category": "network", "severity": "SEV1", "symptoms": "err"}]
        assert "instruction" in payload

    def test_filter_ranked_ids_keeps_only_allowed(self):
        from app.services.search_service import SearchService

        allowed = {1, 2, 3}
        assert SearchService._filter_ranked_ids([1, 2, 3, 99], allowed, [1, 2]) == [1, 2, 3]
        assert SearchService._filter_ranked_ids([99, 100], allowed, [1]) == [1]
        assert SearchService._filter_ranked_ids([3, 1, 2], allowed, [9]) == [3, 1, 2]

    def test_verdict_to_result_maps_fields(self):
        from app.services.search_service import SearchService

        verdict = {
            "category": "database",
            "severity": "SEV1",
            "reasoning": "conn pool exhausted",
            "ranked_runbook_ids": [5, 6],
        }
        result = SearchService._verdict_to_result(verdict, fallback_ids=[1, 2])
        assert result["category"] == "database"
        assert result["severity"] == "SEV1"
        assert result["reasoning"] == "conn pool exhausted"
        assert result["ranked_runbook_ids"] == [5, 6]

    def test_verdict_to_result_fills_defaults(self):
        from app.services.search_service import SearchService

        result = SearchService._verdict_to_result({}, fallback_ids=[9])
        assert result["category"] == "unclassified"
        assert result["severity"] == "SEV-PENDING"
        assert result["reasoning"] == ""
        assert result["ranked_runbook_ids"] == [9]
