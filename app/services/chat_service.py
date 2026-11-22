"""Strict-RAG scoped assistant (lihat DESIGN.md Contract B).

Jawaban WAJIB hanya bersumber dari dokumen runbook yang dikunci pada segment
percakapan aktif. Kegagalan LLM jatuh ke jawaban deterministik lokal.
"""

from typing import Any

from app.extensions import llm
from app.repositories.runbook_repo import RunbookRepository

_SYSTEM_INSTRUCTION = (
    "You are an SRE Incident Mitigation Assistant. "
    "STRICT RULE: Answer the user's request using ONLY the locked Reference Runbooks "
    "provided by the system. Do NOT invent commands, configuration flags, or "
    "infrastructure steps not present in the references. If the user asks about topics "
    "unrelated to the active incident or missing from the references, state clearly in the "
    "user's language: 'Informasi tersebut tidak tersedia dalam 3 referensi runbook yang "
    "sedang aktif.' Respond in the same language used by the user (Indonesian or English), "
    "keeping technical terms intact."
)

_QUICK_PROMPTS: dict[str, str] = {
    "checklist": "Buatkan checklist langkah mitigasi dan verifikasi secara berurutan berdasarkan referensi aktif.",
    "compare": "Bandingkan akar masalah (root cause) dan gejala dari ketiga referensi runbook di atas.",
    "status_draft": "Buatkan draf pengumuman status insiden singkat dan profesional untuk tim di Slack/Teams.",
}


class ChatService:
    def __init__(self, repo: RunbookRepository | None = None) -> None:
        self.repo = repo or RunbookRepository()

    @staticmethod
    def expand_quick_action(action: str | None, message: str | None) -> tuple[str, bool]:
        """Ubah aksi cepat menjadi prompt lengkap di sisi server.

        Mengembalikan (teks prompt, is_quick_action)."""
        if action and action in _QUICK_PROMPTS:
            return _QUICK_PROMPTS[action], True
        return (message or "").strip(), False

    def _build_context_block(self, runbooks: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for idx, rb in enumerate(runbooks, start=1):
            parts.append(
                f"--- Reference Runbook #{idx} (id={rb['id']}) ---\n"
                f"Title: {rb['title']}\n"
                f"Category: {rb['category']} | Severity: {rb['severity']}\n"
                f"Symptoms: {rb['symptoms_log']}\n"
                f"Root Cause: {rb['root_cause']}\n"
                f"Resolution Steps:\n{rb['resolution_steps']}\n"
            )
        return "\n".join(parts)

    def _local_answer(
        self, runbooks: list[dict[str, Any]], prompt: str, is_quick_action: bool
    ) -> str:
        """Fallback deterministik ketika LLM tidak tersedia.

        Menyusun jawaban langsung dari isi runbook tanpa menambah informasi baru.
        """
        if not runbooks:
            return (
                "Layanan AI sintesis sedang tidak tersedia dan tidak ada referensi "
                "runbook aktif. Silakan muat ulang triase untuk menyegarkan konteks."
            )

        if is_quick_action and prompt == _QUICK_PROMPTS["checklist"]:
            lines = ["Checklist mitigasi & verifikasi (disusun dari referensi aktif):"]
            for idx, rb in enumerate(runbooks, start=1):
                lines.append(f"\n#{idx} {rb['title']}")
                lines.extend(rb["resolution_steps"].splitlines())
            return "\n".join(lines)

        if is_quick_action and prompt == _QUICK_PROMPTS["compare"]:
            lines = ["Perbandingan akar masalah & gejala antar referensi:"]
            for idx, rb in enumerate(runbooks, start=1):
                lines.append(f"\n#{idx} {rb['title']}")
                lines.append(f"  Gejala: {rb['symptoms_log'][:300]}")
                lines.append(f"  Akar masalah: {rb['root_cause']}")
            return "\n".join(lines)

        if is_quick_action and prompt == _QUICK_PROMPTS["status_draft"]:
            rb = runbooks[0]
            return (
                "Draf pengumuman status (dari referensi aktif):\n\n"
                f"[INCURRING] Sedang menangani insiden terkait "
                f"'{rb['title']}' (kategori {rb['category']}, severity {rb['severity']}). "
                f"Dampak: {rb['symptoms_log'][:200]}. "
                f"Langkah mitigasi mengacu pada runbook #{rb['id']}; "
                "pembaruan berikutnya akan dikirim setelah mitigasi tervalidasi."
            )

        # Pertanyaan bebas: berikan ringkasan referensi yang relevan secara lexical
        return (
            "Layanan AI sintesis sedang offline. Ringkasan referensi aktif berikut "
            "merupakan data langkah perbaikan yang tersedia:\n\n"
            + "\n\n".join(
                f"#{idx} {rb['title']}\n{rb['resolution_steps']}" for idx, rb in enumerate(runbooks, 1)
            )
        )

    def answer(
        self, locked_runbook_ids: list[int], message: str | None, quick_action: str | None
    ) -> dict[str, Any]:
        """Hasilkan jawaban Strict-RAG untuk runbook yang sedang dikunci."""
        prompt, is_quick_action = self.expand_quick_action(quick_action, message)
        runbooks = self.repo.get_by_ids(locked_runbook_ids)

        if not prompt and not is_quick_action:
            return {
                "user_message": "",
                "answer": "Prompt kosong — tidak ada pertanyaan yang dikirim.",
                "is_fallback": False,
            }

        if llm.enabled:
            try:
                context_block = self._build_context_block(runbooks)
                full_user = f"[LOCKED REFERENCES]\n{context_block}\n\n[USER REQUEST]\n{prompt}"

                text, is_fallback = llm.generate_text(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    user_content=full_user,
                    temperature=0.2,
                )
                if text:
                    return {
                        "user_message": prompt,
                        "answer": text,
                        "is_fallback": is_fallback,
                    }
            except Exception:  # noqa: BLE001 - graceful degradation
                pass

        return {
            "user_message": prompt,
            "answer": self._local_answer(runbooks, prompt, is_quick_action),
            "is_fallback": True,
        }