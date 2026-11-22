"""Fixture bersama untuk seluruh test suite.

Setiap test mendapat database SQLite sementara (tmp_path) dengan skema lengkap
plus fixture runbook minimal, sehingga tidak menyentuh data/app.db sebenarnya.
LLM sengaja dimatikan agar jalur graceful-degradation (fallback lexical)
yang diuji adalah jalur deterministik, bukan panggilan jaringan.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

SCHEMA_PATH = os.path.join(PROJECT_ROOT, "data", "schema.sql")

FIXTURE_RUNBOOKS = [
    {
        "title": "Upstream 502 Bad Gateway After Rolling Update",
        "category": "deployment",
        "severity": "SEV2",
        "symptoms_log": "502 Bad Gateway nginx upstream returned invalid response after rolling deployment of payment-service",
        "root_cause": "New pods released before old pods terminated, causing upstream connection mismatch.",
        "resolution_steps": "1. Drain old pods gracefully before scaling the new deployment.\n2. Verify the nginx upstream block points to healthy backend pods.\n3. Roll back the deployment if the mismatch persists.",
        "content_hash": "upstream-502-bad-gateway-rolling-update",
    },
    {
        "title": "Nginx Keepalive Timeout Mismatch",
        "category": "network",
        "severity": "SEV2",
        "symptoms_log": "intermittent 504 Gateway Timeout on nginx reverse proxy with upstream keepalive errors",
        "root_cause": "Gunicorn worker timeout shorter than nginx keepalive timeout.",
        "resolution_steps": "1. Align nginx keepalive_timeout with the Gunicorn worker timeout.\n2. Increase proxy_read_timeout in the nginx configuration.\n3. Reload nginx configuration without a restart.",
        "content_hash": "nginx-keepalive-timeout-mismatch",
    },
    {
        "title": "PostgreSQL Connection Pool Exhaustion",
        "category": "database",
        "severity": "SEV1",
        "symptoms_log": "FATAL remaining connection slots are reserved for superuser replication connections",
        "root_cause": "Application connection pool exceeded max_connections due to leaked idle connections.",
        "resolution_steps": "1. Identify idle connections via pg_stat_activity.\n2. Terminate idle backends exceeding the hold threshold.\n3. Introduce connection pooling with PgBouncer.",
        "content_hash": "postgres-pool-exhaustion",
    },
    {
        "title": "Pod OOMKilled Resource Exhaustion",
        "category": "resource",
        "severity": "SEV2",
        "symptoms_log": "pod terminated reason OOMKilled memory usage exceeded container limit java heap space",
        "root_cause": "JVM heap exceeded the container memory limit because of a leak.",
        "resolution_steps": "1. Increase the container memory limit in the deployment manifest.\n2. Enable heap dump on OOM.\n3. Profile heap usage with jmap.",
        "content_hash": "pod-oomkilled-resource-exhaustion",
    },
    {
        "title": "CrashLoopBackOff Node.js App",
        "category": "deployment",
        "severity": "SEV2",
        "symptoms_log": "CrashLoopBackOff node application exited with code 1 unhandled promise rejection on startup",
        "root_cause": "Missing environment variable crashed the process on startup.",
        "resolution_steps": "1. Inspect container logs with kubectl logs --previous.\n2. Add the missing environment variable to the deployment.\n3. Redeploy and verify the process stays running.",
        "content_hash": "crashloopbackoff-nodejs-app",
    },
    {
        "title": "Disk Space Exhaustion on Node",
        "category": "resource",
        "severity": "SEV1",
        "symptoms_log": "no space left on device kubelet garbage collection failed node reports DiskPressure",
        "root_cause": "Container images and logs accumulated beyond the ephemeral storage threshold.",
        "resolution_steps": "1. Confirm disk pressure with kubectl describe node.\n2. Prune unused images with crictl rmi --prune.\n3. Rotate and compress application logs.",
        "content_hash": "disk-space-exhaustion-node",
    },
]


def _build_db(db_path: str) -> None:
    """Buat skema lengkap + seed fixture runbook ke database sementara."""
    conn = sqlite3.connect(db_path)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.executemany(
            """
            INSERT INTO runbooks (title, category, severity, symptoms_log, root_cause, resolution_steps, content_hash)
            VALUES (:title, :category, :severity, :symptoms_log, :root_cause, :resolution_steps, :content_hash)
            """,
            FIXTURE_RUNBOOKS,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def app(tmp_path):
    """Aplikasi dengan DB sementara + CSRF dimatikan (untuk test service/endpoint)."""
    db_path = str(tmp_path / "test.db")
    _build_db(db_path)

    from app import create_app
    from app.extensions import llm

    application = create_app()
    application.config.update(
        TESTING=True,
        DATABASE=db_path,
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-secret",
    )

    # Pastikan LLM benar-benar nonaktif → jalur fallback deterministik
    llm.gemini_enabled = False
    llm.custom_enabled = False
    llm.gemini_client = None
    llm.custom_client = None

    yield application

    llm.gemini_enabled = False
    llm.custom_enabled = False
    llm.gemini_client = None
    llm.custom_client = None


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def app_csrf(tmp_path):
    """Aplikasi dengan CSRF AKTIF — dipakai untuk memverifikasi proteksi token."""
    db_path = str(tmp_path / "test_csrf.db")
    _build_db(db_path)

    from app import create_app
    from app.extensions import llm

    application = create_app()
    application.config.update(
        TESTING=True,
        DATABASE=db_path,
        WTF_CSRF_ENABLED=True,
        SECRET_KEY="test-secret",
        WTF_CSRF_SECRET_KEY="test-secret",
    )

    llm.gemini_enabled = False
    llm.custom_enabled = False
    llm.gemini_client = None
    llm.custom_client = None

    yield application

    llm.gemini_enabled = False
    llm.custom_enabled = False
    llm.gemini_client = None
    llm.custom_client = None


@pytest.fixture()
def csrf_token(app_csrf):
    """Ambil CSRF token valid dari halaman workspace (mekanisme nyata UI)."""
    page = app_csrf.test_client().get("/").data.decode()
    import re

    m = re.search(r'hx-headers=\'{"X-CSRFToken": "([0-9a-zA-Z.\-_]+)"}\'', page)
    assert m, "CSRF token tidak ditemukan pada halaman workspace"
    return m.group(1)