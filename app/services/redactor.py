"""Regex PII & secret masking engine.

WAJIB dijalankan pada setiap log masuk SEBELUM log disimpan, dicari,
atau dikirim ke API LLM eksternal (lihat AGENTS.md §3.1 dan ARCHITECTURE.md §5.1).
"""

import re
from dataclasses import dataclass, field

# (nama pola, regex terkompilasi) — urutan penting: URI kredensial diproses
# lebih dulu agar bagian "password" di dalam URI ikut tersensor.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "bearer_token",
        re.compile(r"(?i)\b(authorization\s*[:=]?\s*bearer\s+)[A-Za-z0-9._\-]+"),
    ),
    (
        "db_connection_uri",
        re.compile(
            r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)(://)"
            r"([^\s:@/]+):([^\s@/]+)@"
        ),
    ),
    (
        "api_key_openai_style",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
    (
        "api_key_generic",
        re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?key|secret[_-]?key)\s*[:=]\s*[\"']?([^\s\"']{8,})"),
    ),
    (
        "aws_key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "ipv4",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ),
]

REDACTED = "<REDACTED>"


@dataclass
class RedactionResult:
    text: str
    count: int
    labels: list[str] = field(default_factory=list)


def redact_secrets(text: str) -> RedactionResult:
    """Sensor pola sensitif dalam teks dan kembalikan hasil beserta jumlah redaksi.

    Pola seperti bearer token dan URI database diformat dengan prefix dipertahankan
    (misal ``Authorization: Bearer <REDACTED>``) agar format log tetap terbaca dan
    pola tetap teridentifikasi sebagai struktur kredensial, tanpa membocorkan nilai
    sebenarnya. Pola lain (email, IPv4, API key murni) diganti sepenuhnya karena
    tidak memiliki prefix yang bermakna untuk dipertahankan.
    """
    if not text:
        return RedactionResult(text=text or "", count=0, labels=[])

    result = text
    total_count = 0
    labels: list[str] = []

    for label, pattern in _PATTERNS:
        matches = list(pattern.finditer(result))
        if not matches:
            continue

        hit = len(matches)
        total_count += hit
        labels.append(label)

        if label in ("bearer_token",):
            # Pertahankan prefix "Authorization: Bearer " → sensor hanya token
            def _sub_bearer(m: re.Match[str]) -> str:
                return f"{m.group(1)}{REDACTED}"

            result = pattern.sub(_sub_bearer, result)
        elif label in ("db_connection_uri",):
            # Pertahankan skema:// → sensor kredensial user:password
            def _sub_uri(m: re.Match[str]) -> str:
                return f"{m.group(1)}{m.group(2)}{REDACTED}:{REDACTED}@"

            result = pattern.sub(_sub_uri, result)
        elif label in ("api_key_generic",):
            # Pertahankan nama field → sensor nilai
            def _sub_field(m: re.Match[str]) -> str:
                return f"{m.group(1)}: {REDACTED}"

            result = pattern.sub(_sub_field, result)
        else:
            result = pattern.sub(REDACTED, result)

    return RedactionResult(text=result, count=total_count, labels=labels)