"""Unit test untuk regex redaction engine (F1 — Security mandate AGENTS.md §3.1)."""
from __future__ import annotations

from app.services.redactor import redact_secrets


class TestBearerToken:
    def test_bearer_token_masked(self):
        result = redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.text
        assert "<REDACTED>" in result.text

    def test_bearer_prefix_preserved_for_readability(self):
        result = redact_secrets("Authorization: Bearer abc123def456")
        assert "Authorization: Bearer" in result.text
        assert "abc123def456" not in result.text

    def test_case_insensitive(self):
        result = redact_secrets("authorization: bearer qwertyuiopasdfghjklzxcvbnm")
        assert "qwertyuiopasdfghjklzxcvbnm" not in result.text
        assert result.count >= 1


class TestDatabaseConnectionUri:
    def test_postgres_credentials_masked(self):
        result = redact_secrets("postgres://app_user:sup3rsecret@db.internal:5432/prod")
        assert "sup3rsecret" not in result.text
        assert "app_user" not in result.text
        assert "<REDACTED>" in result.text

    def test_mysql_and_mongodb_schemes(self):
        for scheme in ("mysql", "mongodb+srv", "redis"):
            r = redact_secrets(f"{scheme}://user:password123@host:1234/db")
            assert "password123" not in r.text, scheme

    def test_scheme_and_host_preserved(self):
        result = redact_secrets("postgres://u:p@db.internal:5432/prod")
        assert "postgres://" in result.text
        assert "db.internal:5432" in result.text


class TestApiKeys:
    def test_openai_style_key(self):
        result = redact_secrets("key = sk-abc123def456ghi789jkl012mno345pqr")
        assert "sk-abc123def456ghi789jkl012mno345pqr" not in result.text

    def test_generic_api_key_field(self):
        result = redact_secrets("api_key: AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.text

    def test_aws_access_key_id(self):
        result = redact_secrets("AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        assert "AKIAIOSFODNN7EXAMPLE" not in result.text

    def test_github_token(self):
        token = "ghp_" + "a" * 36
        result = redact_secrets(f"GITHUB_TOKEN={token}")
        assert token not in result.text


class TestPii:
    def test_email_masked(self):
        result = redact_secrets("contact engineer@sre-team.example.com for details")
        assert "engineer@sre-team.example.com" not in result.text
        assert "<REDACTED>" in result.text

    def test_ipv4_masked(self):
        result = redact_secrets("upstream 10.0.12.34:8080 unreachable")
        assert "10.0.12.34" not in result.text


class TestMeta:
    def test_empty_input(self):
        result = redact_secrets("")
        assert result.text == ""
        assert result.count == 0

    def test_none_like_empty_string(self):
        result = redact_secrets("   ")
        assert result.count == 0

    def test_clean_log_untouched(self):
        log = "2026-11-20T03:14:02Z error nginx upstream timed out 502 Bad Gateway"
        result = redact_secrets(log)
        assert result.text == log
        assert result.count == 0
        assert result.labels == []

    def test_count_and_labels_populated(self):
        log = (
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\n"
            "postgres://user:sup3rsecret@db.internal:5432/prod\n"
            "email: ops@example.com"
        )
        result = redact_secrets(log)
        assert result.count >= 3
        assert "bearer_token" in result.labels
        assert "db_connection_uri" in result.labels
        assert "email" in result.labels

    def test_redaction_removes_all_instances(self):
        log = "sk-aaaaaaaaaaaaaaaaaaaaaa and sk-bbbbbbbbbbbbbbbbbbbbbb"
        result = redact_secrets(log)
        assert "sk-" not in result.text