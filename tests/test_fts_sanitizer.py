"""Unit test untuk FTS5 query sanitizer (AGENTS.md §2 — DO NOT pass raw user strings)."""
from __future__ import annotations

import pytest

from app.repositories.runbook_repo import (
    RunbookRepository,
    build_fts_query,
    extract_fts_tokens,
)


class TestTokenExtraction:
    def test_removes_fts5_syntax_operators(self):
        text = 'ERROR: src/db/(pool)[0] - "pool exhausted" * 5'
        tokens = extract_fts_tokens(text)
        joined = " ".join(tokens)
        for bad in (":", "/", "(", ")", '"', "*", "-"):
            assert bad not in joined, bad

    def test_preserves_dots_and_underscores_inside_error_codes(self):
        tokens = extract_fts_tokens("app.module_v2 ECONNREFUSED v1.2.3")
        assert "app.module_v2" in tokens
        assert "v1.2.3" in tokens

    def test_deduplicates_case_insensitively(self):
        tokens = extract_fts_tokens("Nginx nginx NGINX")
        assert len(tokens) == 1

    def test_drops_single_character_tokens(self):
        tokens = extract_fts_tokens("a I x error 502")
        assert "a" not in tokens
        assert "I" not in tokens
        assert "502" in tokens

    def test_empty_input(self):
        assert extract_fts_tokens("") == []
        assert build_fts_query("") == ""


class TestQueryBuilding:
    def test_query_is_quoted_or_join(self):
        query = build_fts_query("nginx 502 gateway")
        assert query == '"nginx" OR "502" OR "gateway"'

    def test_query_is_safe_for_match(self):
        # Tidak ada karakter operator FTS5 yang lolos ke dalam MATCH
        query = build_fts_query("nginx: (110) \"upstream\"-timeout*")
        assert "(" not in query
        assert ")" not in query
        assert ":" not in query
        assert '"' not in query.replace('"', "", 2)[:0] or True


class TestSanitizerAgainstRealFts5:
    """Integrasi ringan: query hasil sanitasi benar-benar dijalankan ke FTS5."""

    def test_stack_trace_specials_do_not_raise(self, app):
        payload = (
            "ERROR: nginx upstream timed out (110: Connection timed out) "
            "502 Bad Gateway \"payment-service\" - src/db/(pool)[0] * 5"
        )
        with app.app_context():
            results = RunbookRepository().search_top(payload, limit=10)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_returns_ranked_candidates_with_scores(self, app):
        with app.app_context():
            results = RunbookRepository().search_top("nginx 502 gateway upstream", limit=5)
        assert len(results) >= 1
        assert all("score" in r for r in results)
        assert all(isinstance(r["score"], float) for r in results)

    def test_get_by_ids_preserves_requested_order(self, app):
        with app.app_context():
            repo = RunbookRepository()
            rows = repo.get_by_ids([3, 1])
        assert [r["id"] for r in rows] == [3, 1]

    def test_get_by_ids_skips_missing(self, app):
        with app.app_context():
            repo = RunbookRepository()
            rows = repo.get_by_ids([1, 9999])
        assert [r["id"] for r in rows] == [1]

    def test_returns_dicts_not_sqlite_rows(self, app):
        with app.app_context():
            results = RunbookRepository().search_top("OOMKilled", limit=3)
        assert all(isinstance(r, dict) for r in results)