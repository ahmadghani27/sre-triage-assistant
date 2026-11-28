"""Unit test untuk endpoint triase/chat/analytics & rendering UI HTMX."""

from __future__ import annotations

import re

SECRET_LOG = (
    "2026-11-20T03:14:02Z error nginx upstream timed out 502 Bad Gateway after deploy "
    "payment-service\nAuthorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\n"
    "postgres://app_user:sup3rsecret@db.internal:5432/prod"
)


def _csrf(client) -> str:
    page = client.get("/").data.decode()
    m = re.search(r'hx-headers=\'{"X-CSRFToken": "([0-9a-zA-Z.\-_]+)"}\'', page)
    assert m, "CSRF token tidak ditemukan"
    return m.group(1)


class TestPages:
    def test_workspace_renders(self, client):
        r = client.get("/")
        assert r.status_code == 200
        html = r.data.decode()
        assert 'id="triage-output-area"' in html
        assert 'id="top3-reference-panel"' in html
        assert 'id="workspace-state"' in html

    def test_dashboard_renders_with_three_canvases(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 200
        html = r.data.decode()
        assert html.count("<canvas") == 3
        assert "chart-category" in html
        assert "chart-severity" in html
        assert "chart-trend" in html

    def test_base_template_wires_htmx_and_csrf(self, client):
        html = client.get("/").data.decode()
        assert "htmx" in html
        assert "hx-headers" in html
        assert "X-CSRFToken" in html

    def test_nav_links_present(self, client):
        html = client.get("/").data.decode()
        assert 'href="/"' in html
        assert 'href="/dashboard"' in html


class TestAnalyticsApi:
    def test_charts_json_contract(self, client):
        r = client.get("/api/analytics/charts")
        assert r.status_code == 200
        data = r.get_json()
        assert set(data.keys()) == {
            "category_distribution",
            "severity_distribution",
            "incident_trend",
            "summary",
        }
        assert isinstance(data["incident_trend"], list)
        assert data["summary"]["runbook_total"] >= 1

    def test_trend_populated_after_triage(self, client):
        client.post("/triage", data={"raw_log": SECRET_LOG})
        data = client.get("/api/analytics/charts").get_json()
        assert data["summary"]["total_triages"] >= 1
        assert len(data["incident_trend"]) >= 1

    def test_fallback_reflects_llm_off(self, client):
        client.post("/triage", data={"raw_log": SECRET_LOG})
        data = client.get("/api/analytics/charts").get_json()
        assert data["summary"]["fallback_rate"] == 1.0


class TestTriageEndpoint:
    def test_triage_returns_partials_and_oob(self, client):
        r = client.post("/triage", data={"raw_log": SECRET_LOG})
        assert r.status_code == 200
        body = r.data.decode()

        assert "lexical fallback" in body
        assert "rahasia disensor" in body
        assert "AI offline" in body
        assert 'id="top3-reference-panel"' in body
        assert "hx-swap-oob" in body
        assert 'id="workspace-state"' in body
        assert "View Full Resolution Steps" in body

    def test_triage_secrets_not_in_response(self, client):
        body = client.post("/triage", data={"raw_log": SECRET_LOG}).data.decode()
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in body
        assert "sup3rsecret" not in body

    def test_triage_locked_ids_extractable(self, client):
        body = client.post("/triage", data={"raw_log": SECRET_LOG}).data.decode()
        m = re.search(r'id="state-locked-ids" value="([^"]*)"', body)
        assert m
        ids = [int(i) for i in m.group(1).split(",")]
        assert 1 <= len(ids) <= 3

    def test_triage_empty_input_returns_inline_error(self, client):
        r = client.post("/triage", data={"raw_log": "   "})
        assert r.status_code == 200
        assert "tidak boleh kosong" in r.data.decode()

    def test_triage_specials_do_not_break_fts5(self, client):
        payload = 'ERROR: src/db/(pool)[0] - "pool exhausted" * 5 "quoted"'
        r = client.post("/triage", data={"raw_log": payload})
        assert r.status_code == 200
        assert "lexical fallback" in r.data.decode()

    def test_triage_csrf_required(self, app_csrf):
        client = app_csrf.test_client()
        r = client.post("/triage", data={"raw_log": SECRET_LOG})
        assert r.status_code == 400


class TestSaveReportEndpoint:
    def test_save_report_endpoint(self, client):
        resp = client.post("/triage/save-report", data={
            "title": "Laporan Nginx 502",
            "query": "nginx upstream timed out",
            "category": "network",
            "severity": "SEV3",
            "top_runbook_ids": "1,2",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert isinstance(data["id"], int)

    def test_save_report_endpoint_validation_fail(self, client):
        resp = client.post("/triage/save-report", data={
            "title": "",
            "query": "",
            "category": "",
            "severity": "",
            "top_runbook_ids": "",
        })
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "error" in data


class TestHistoryEndpoint:
    def test_history_page_renders(self, client):
        client.post("/triage/save-report", data={
            "title": "Laporan Nginx 502",
            "query": "nginx upstream timed out",
            "category": "network",
            "severity": "SEV3",
            "top_runbook_ids": "1,2",
        })
        resp = client.get("/triage/history")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "History Triase" in html
        assert "Laporan Nginx 502" in html
        assert "nginx upstream timed out" in html


class TestRefineEndpoint:
    def test_refine_returns_divider_and_oob_updates(self, client):
        r = client.post(
            "/triage/refine",
            data={"sanitized_log": "nginx 502 bad gateway", "refine_note": "pod OOMKilled"},
        )
        assert r.status_code == 200
        body = r.data.decode()
        assert "Referensi Diperbarui" in body
        assert 'id="top3-reference-panel"' in body
        assert 'id="workspace-state"' in body

    def test_refine_missing_context_inline_error(self, client):
        r = client.post("/triage/refine", data={"sanitized_log": "", "refine_note": "x"})
        assert r.status_code == 200
        assert "kosong" in r.data.decode()


class TestChatEndpoint:
    def test_chat_appends_user_and_assistant_bubbles(self, client):
        body = client.post("/triage", data={"raw_log": SECRET_LOG}).data.decode()
        locked = re.search(r'id="state-locked-ids" value="([^"]*)"', body).group(1)

        r = client.post(
            "/chat",
            data={"message": "apa penyebabnya?", "locked_runbook_ids": locked},
        )
        assert r.status_code == 200
        resp = r.data.decode()
        assert "You" in resp
        assert "Strict-RAG Assistant" in resp

    def test_chat_quick_action_scoped_to_locked_runbooks(self, client):
        body = client.post("/triage", data={"raw_log": SECRET_LOG}).data.decode()
        locked = re.search(r'id="state-locked-ids" value="([^"]*)"', body).group(1)

        r = client.post(
            "/chat",
            data={"quick_action": "checklist", "locked_runbook_ids": locked},
        )
        assert r.status_code == 200
        assert "ecklist" in r.data.decode()
        assert "#1" in r.data.decode()

    def test_chat_without_locked_ids_degrades_gracefully(self, client):
        r = client.post("/chat", data={"quick_action": "checklist", "locked_runbook_ids": ""})
        assert r.status_code == 200
        assert "Strict-RAG Assistant" in r.data.decode()


class TestTriageBlueprintHelpers:
    """Tes untuk helper yang diekstrak dari triage() dan refine()."""

    def test_build_locked_ids_joins_ranked_ids(self):
        from app.blueprints.triage import _build_locked_ids

        class FakeResult:
            ranked_ids = [5, 1, 9]

        assert _build_locked_ids(FakeResult()) == "5,1,9"

    def test_render_oob_partials_returns_top3_and_state(self, app):
        from app.blueprints.triage import _render_oob_partials

        class Runbook:
            def __init__(self, rid, title, category, severity, root_cause, resolution_steps):
                self.id = rid
                self.title = title
                self.category = category
                self.severity = severity
                self.root_cause = root_cause
                self.resolution_steps = resolution_steps

        class FakeResult:
            ranked_ids = [1]
            top_runbooks = [
                Runbook(1, "Runbook A", "network", "SEV2", "upstream mismatch", "1. Drain\n2. Verify"),
            ]
            sanitized_log = "log bersih"
            category = "network"
            severity = "SEV2"
            redaction_count = 0
            redaction_labels = []
            is_fallback = False

        with app.app_context():
            partial = _render_oob_partials(FakeResult(), "log bersih", "1")
        assert "hx-swap-oob" in partial
        assert "top3-reference-panel" in partial or "top3" in partial.lower()
        assert "workspace-state" in partial

    def test_render_triage_partial_includes_result(self, app):
        from app.blueprints.triage import _render_triage_partial

        class FakeResult:
            ranked_ids = [1]
            top_runbooks = []
            sanitized_log = "log bersih"
            category = "network"
            severity = "SEV2"
            reasoning = "fallback"
            redaction_count = 0
            redaction_labels = []
            is_fallback = False

        with app.app_context():
            partial = _render_triage_partial(FakeResult(), "log bersih", "1", oob=True)
        assert "hx-swap-oob" in partial
        assert "log bersih" in partial or "network" in partial
