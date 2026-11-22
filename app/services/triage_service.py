"""Triage orchestration: redaction → hybrid search → persist log.

Tidak melakukan HTTP parsing, SQL langsung, atau rendering template —
itu tanggung jawab blueprint (AGENTS.md §2).
"""

from dataclasses import dataclass, field
from typing import Any

from app.repositories.log_repo import LogRepository
from app.repositories.runbook_repo import RunbookRepository
from app.services.redactor import redact_secrets
from app.services.search_service import SearchService


@dataclass
class TriageResult:
    sanitized_log: str
    redaction_count: int
    redaction_labels: list[str] = field(default_factory=list)
    category: str = "unclassified"
    severity: str = "SEV-PENDING"
    reasoning: str = ""
    is_fallback: bool = False
    top_runbooks: list[dict[str, Any]] = field(default_factory=list)
    ranked_ids: list[int] = field(default_factory=list)


class TriageService:
    def __init__(
        self,
        search: SearchService | None = None,
        runbook_repo: RunbookRepository | None = None,
        log_repo: LogRepository | None = None,
    ) -> None:
        self.search = search or SearchService()
        self.runbook_repo = runbook_repo or RunbookRepository()
        self.log_repo = log_repo or LogRepository()

    def run(self, raw_log: str) -> TriageResult:
        """Jalankan pipeline triase penuh untuk satu input log mentah."""
        # 1. Redaksi wajib sebelum pencarian/penyimpanan/eksternal API
        redaction = redact_secrets(raw_log)
        sanitized_log = redaction.text

        # 2. Stage-1 lexical retrieval
        candidates = self.search.lexical_search(sanitized_log)

        # 3. Stage-2 classification + re-ranking (graceful degradation internal)
        verdict, is_fallback = self.search.classify_and_rerank(sanitized_log, candidates)
        if verdict is None:
            return TriageResult(
                sanitized_log=sanitized_log,
                redaction_count=redaction.count,
                redaction_labels=redaction.labels,
                is_fallback=True,
            )

        ranked_ids: list[int] = list(verdict["ranked_runbook_ids"])

        # 4. Ambil dokumen penuh untuk Top-3 terpilih (pertahankan urutan peringkat)
        top_runbooks = self.runbook_repo.get_by_ids(ranked_ids)
        if not top_runbooks:
            # Kasus ekstrem: ID pilihan LLM hilang dari DB → pakai kandidat lexical
            top_runbooks = candidates[: SearchService.TOP_K]
            ranked_ids = [c["id"] for c in top_runbooks]

        # 5. Persistensi analitik anonim
        self.log_repo.save(
            sanitized_query=sanitized_log[:2000],
            redaction_count=redaction.count,
            predicted_category=verdict["category"],
            predicted_severity=verdict["severity"],
            top_runbook_ids=ranked_ids,
            is_fallback=is_fallback,
        )

        return TriageResult(
            sanitized_log=sanitized_log,
            redaction_count=redaction.count,
            redaction_labels=redaction.labels,
            category=verdict["category"],
            severity=verdict["severity"],
            reasoning=verdict.get("reasoning", ""),
            is_fallback=is_fallback,
            top_runbooks=top_runbooks,
            ranked_ids=ranked_ids,
        )

    def refine(self, original_sanitized_log: str, refine_note: str) -> TriageResult:
        """Explicit re-triage: gabungkan log awal + konteks baru, jalankan ulang."""
        redaction = redact_secrets(refine_note)
        combined = f"{original_sanitized_log}\n\n[REFINE CONTEXT]\n{redaction.text}".strip()
        return self.run(combined)