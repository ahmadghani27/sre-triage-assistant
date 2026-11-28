"""Hybrid search: FTS5 lexical retrieval → LLM re-ranking.

Bertanggung jawab atas sanitasi query FTS5 (AGENTS.md §2) dan graceful
degradation ke hasil lexical murni ketika lapisan LLM tidak tersedia.
"""

import logging
from typing import Any

from app.extensions import llm
from app.repositories.runbook_repo import RunbookRepository, build_fts_query

logger = logging.getLogger(__name__)


def _split_tokens_for_relaxed_query(text: str) -> str:
    """Pecah camelCase & snake_case agar kode error seperti ``OOMKilled`` tetap
    bisa dicari ketika queryBM25 awal mengembalikan nol baris."""
    replacements = [
        ("_", " "),
        ("-", " "),
    ]
    softened = text
    for src, dst in replacements:
        softened = softened.replace(src, dst)
    # sisipkan spasi pada transisi huruf kecil→huruf besar (camelCase)
    relaxed_chars: list[str] = []
    for idx, ch in enumerate(softened):
        if ch.isupper() and idx > 0 and (softened[idx - 1].islower() or softened[idx - 1].isdigit()):
            relaxed_chars.append(" ")
        relaxed_chars.append(ch)
    return "".join(relaxed_chars)


class SearchService:
    """Mengorkestrasi tahap 1 (lexical) dan tahap 2 (semantik) hybrid search."""

    CANDIDATE_LIMIT = 10
    TOP_K = 3

    def __init__(self, repo: RunbookRepository | None = None) -> None:
        self.repo = repo or RunbookRepository()

    @staticmethod
    def _build_json_schema() -> dict[str, Any]:
        """Skema JSON untuk verdict LLM: kategori, severitas, penalaran, daftar ID terurut."""
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["network", "database", "deployment", "resource"],
                },
                "severity": {
                    "type": "string",
                    "enum": ["SEV1", "SEV2", "SEV3", "SEV4"],
                },
                "reasoning": {"type": "string"},
                "ranked_runbook_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
            "required": ["category", "severity", "reasoning", "ranked_runbook_ids"],
        }

    @staticmethod
    def _build_llm_payload(sanitized_log: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Susun payload untuk pemanggilan LLM generate_json."""
        return {
            "sanitized_log": sanitized_log[:4000],
            "candidates": SearchService._summarize_candidates(candidates),
            "instruction": "Return max 3 ranked_runbook_ids taken strictly from the candidate list.",
        }

    @staticmethod
    def _filter_ranked_ids(
        ids: list[int], allowed: set[int], fallback_ids: list[int]
    ) -> list[int]:
        """Terima hanya ID yang ada di kandidat; fallback ke urutan lexical jika kosong."""
        filtered = [i for i in ids if i in allowed][: SearchService.TOP_K]
        return filtered or fallback_ids[: SearchService.TOP_K]

    @staticmethod
    def _verdict_to_result(verdict: dict[str, Any], fallback_ids: list[int]) -> dict[str, Any]:
        """Map verdict LLM ke dict hasil, dengan default saat field hilang."""
        return {
            "category": verdict.get("category") or "unclassified",
            "severity": verdict.get("severity") or "SEV-PENDING",
            "reasoning": verdict.get("reasoning") or "",
            "ranked_runbook_ids": verdict.get("ranked_runbook_ids", []) or fallback_ids,
        }

    def lexical_search(self, sanitized_text: str, limit: int = CANDIDATE_LIMIT) -> list[dict[str, Any]]:
        """Tahap 1: FTS5 BM25 Top-N, dengan retry sekali terhadap token yang dilonggarkan."""
        if not sanitized_text or not build_fts_query(sanitized_text):
            return []

        results = self.repo.search_top(sanitized_text, limit=limit)
        if results:
            return results

        relaxed = _split_tokens_for_relaxed_query(sanitized_text)
        if build_fts_query(relaxed):
            results = self.repo.search_top(relaxed, limit=limit)
            if results:
                return results

        # Zero rows → gunakan runbook paling sering muncul sebagai fallback deterministik
        return self.repo.get_any(limit=limit)

    @staticmethod
    def _summarize_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "title": c["title"],
                "category": c["category"],
                "severity": c["severity"],
                "symptoms": c["symptoms_log"][:300],
            }
            for c in candidates
        ]

    def classify_and_rerank(
        self,
        sanitized_log: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, bool]:
        """Tahap 2: LLM classification + re-ranking Top-3.

        Mengembalikan (hasil, is_fallback). Ketika LLM tidak aktif atau gagal,
        ``is_fallback`` bernilai True dan hasil memakai urutan lexical apa adanya.
        """
        if not candidates:
            return None, False

        fallback_ids = [c["id"] for c in candidates[: self.TOP_K]]
        if not llm.enabled:
            return self._fallback(fallback_ids, candidates), True

        try:
            system_prompt = (
                "You are an SRE triage engine. Given a sanitized incident log and a list of "
                "candidate runbooks (id + title), classify the incident AND pick the most "
                "relevant runbook ids ordered from most to least relevant. "
                "Respond ONLY with a JSON object."
            )
            user_payload = SearchService._build_llm_payload(sanitized_log, candidates)
            schema = SearchService._build_json_schema()

            verdict, _ = llm.generate_json(
                system_instruction=system_prompt,
                user_payload=user_payload,
                schema=schema,
                temperature=0.2,
            )
            if verdict is None:
                return self._fallback(fallback_ids, candidates), True

            ids = SearchService._filter_ranked_ids(
                [int(i) for i in verdict.get("ranked_runbook_ids", [])],
                {c["id"] for c in candidates},
                fallback_ids,
            )
            return SearchService._verdict_to_result(verdict, fallback_ids), False

        except Exception as exc:  # noqa: BLE001 - graceful degradation untuk semua kegagalan LLM
            logger.warning("[Search] LLM gagal, fallback ke peringkat lexical: %s", exc)
            return self._fallback(fallback_ids, candidates), True

    @staticmethod
    def _fallback(fallback_ids: list[int], candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Hasil default saat LLM mati/gagal: urutan lexical apa adanya.
        Severity diambil dari runbook teratas hasil pencarian lexical agar
        tidak selalu SEV-PENDING ketika LLM offline.
        """
        top_severity = candidates[0].get("severity") if candidates else "SEV-PENDING"
        return {
            "category": "unclassified",
            "severity": top_severity or "SEV-PENDING",
            "reasoning": "",
            "ranked_runbook_ids": fallback_ids,
        }