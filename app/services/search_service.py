"""Hybrid search: FTS5 lexical retrieval → LLM re-ranking.

Bertanggung jawab atas sanitasi query FTS5 (AGENTS.md §2) dan graceful
degradation ke hasil lexical murni ketika lapisan LLM tidak tersedia.
"""

from typing import Any

from app.extensions import llm
from app.repositories.runbook_repo import RunbookRepository, build_fts_query


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

    def _summarize_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        fallback = {
            "category": "unclassified",
            "severity": "SEV-PENDING",
            "reasoning": "",
            "ranked_runbook_ids": fallback_ids,
        }

        if not llm.enabled:
            return fallback, True

        try:
            import json

            system_prompt = (
                "You are an SRE triage engine. Given a sanitized incident log and a list of "
                "candidate runbooks (id + title), classify the incident AND pick the most "
                "relevant runbook ids ordered from most to least relevant. "
                "Respond ONLY with a JSON object."
            )
            user_payload = {
                "sanitized_log": sanitized_log[:4000],
                "candidates": self._summarize_candidates(candidates),
                "instruction": "Return max 3 ranked_runbook_ids taken strictly from the candidate list.",
            }

            schema = {
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

            verdict, is_fallback = llm.generate_json(
                system_instruction=system_prompt,
                user_payload=user_payload,
                schema=schema,
                temperature=0.2,
            )
            if verdict is None:
                return fallback, True

            ids = [int(i) for i in verdict.get("ranked_runbook_ids", [])][: self.TOP_K]
            if not ids:
                return fallback, True

            # Pastikan hanya ID kandidat yang diterima
            allowed = {c["id"] for c in candidates}
            ids = [i for i in ids if i in allowed] or fallback_ids

            return {
                "category": verdict.get("category") or "unclassified",
                "severity": verdict.get("severity") or "SEV-PENDING",
                "reasoning": verdict.get("reasoning") or "",
                "ranked_runbook_ids": ids,
            }, False

        except Exception:  # noqa: BLE001 - graceful degradation untuk semua kegagalan LLM
            return fallback, True