import json
import logging
import os
import re
import sqlite3
from flask import g, current_app
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)

try:
    from google import genai
except Exception:  # pragma: no cover - genai optional at import time
    genai = None

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - openai optional at import time
    OpenAI = None

csrf = CSRFProtect()


class LLM:
    """Wrapper dual-provider LLM (Gemini native + OpenAI-compatible custom)
    with graceful degradation. Provider env vars dibaca dari .env.
    """

    def __init__(self):
        self.gemini_client = None
        self.custom_client = None
        self.gemini_enabled = False
        self.custom_enabled = False
        self.gemini_model = None
        self.custom_model = None

    def init_app(self, app):
        # --- Provider 1: Gemini (native google-genai) ---
        api_key = os.environ.get("GEMINI_API_KEY") or app.config.get("GEMINI_API_KEY")
        model = (
            os.environ.get("GEMINI_MODEL")
            or app.config.get("GEMINI_MODEL", "gemini-2.5-flash")
        )
        if api_key and genai is not None:
            try:
                self.gemini_client = genai.Client(api_key=api_key)
                self.gemini_enabled = True
                self.gemini_model = model
            except Exception as exc:  # pragma: no cover - client init failure
                logger.warning("[LLM Init Gemini Error] %s", exc)
                self.gemini_client = None
                self.gemini_enabled = False
        else:
            self.gemini_enabled = False

        # --- Provider 2: Custom / OpenAI-compatible (hcnsec.cn) ---
        ckey = os.environ.get("CUSTOM_API_KEY") or app.config.get("CUSTOM_API_KEY")
        cbase = (
            os.environ.get("CUSTOM_BASE_URL")
            or app.config.get("CUSTOM_BASE_URL", "https://api.hcnsec.cn/v1")
        )
        cmodel = (
            os.environ.get("CUSTOM_MODEL")
            or app.config.get("CUSTOM_MODEL", "Qwen3.8-Flash-Next")
        )
        if ckey and OpenAI is not None:
            try:
                self.custom_client = OpenAI(api_key=ckey, base_url=cbase, timeout=30.0)
                self.custom_enabled = True
                self.custom_model = cmodel
            except Exception as exc:  # pragma: no cover - client init failure
                logger.warning("[LLM Init Custom Error] %s", exc)
                self.custom_client = None
                self.custom_enabled = False
        else:
            self.custom_enabled = False

        # Taruh di paling akhir init_app (di luar try/except) agar selalu tercetak saat startup
        logger.warning(
            "[LLM Init] Gemini enabled=%s (model=%s) | Custom enabled=%s (model=%s)",
            self.gemini_enabled,
            self.gemini_model,
            self.custom_enabled,
            self.custom_model,
        )
        # --- Provider 1: Gemini (native google-genai) ---
        api_key = os.environ.get("GEMINI_API_KEY") or app.config.get("GEMINI_API_KEY")
        model = (
            os.environ.get("GEMINI_MODEL")
            or app.config.get("GEMINI_MODEL", "gemini-2.5-flash")
        )
        if api_key and genai is not None:
            try:
                self.gemini_client = genai.Client(api_key=api_key)
                self.gemini_enabled = True
                self.gemini_model = model
            except Exception:  # pragma: no cover - client init failure
                logger.warning("[LLM Init Gemini Error] %s", exc)
                self.gemini_client = None
                self.gemini_enabled = False
        else:
            self.gemini_enabled = False

        # --- Provider 2: Custom / OpenAI-compatible (hcnsec.cn) ---
        ckey = os.environ.get("CUSTOM_API_KEY") or app.config.get("CUSTOM_API_KEY")
        cbase = (
            os.environ.get("CUSTOM_BASE_URL")
            or app.config.get("CUSTOM_BASE_URL", "https://api.hcnsec.cn/v1")
        )
        cmodel = (
            os.environ.get("CUSTOM_MODEL")
            or app.config.get("CUSTOM_MODEL", "Qwen3.8-Flash-Next")
        )
        if ckey and OpenAI is not None:
            try:
                self.custom_client = OpenAI(api_key=ckey, base_url=cbase, timeout=30.0)
                self.custom_enabled = True
                self.custom_model = cmodel
            except Exception:  # pragma: no cover - client init failure
                self.custom_client = None
                self.custom_enabled = False
        else:
            self.custom_enabled = False

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """Bersihkan blok <think>...</think> atau ```json ... ``` sebelum json.loads."""
        cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            cleaned = match.group(0)
        return json.loads(cleaned)
    
    @property
    def enabled(self):
        """Setidaknya satu provider siap."""
        return self.gemini_enabled or self.custom_enabled

    @property
    def client(self):
        """Backward-compat: kembalikan client provider aktif utama (Gemini dulu)."""
        return self.gemini_client if self.gemini_enabled else self.custom_client

    # ------------------------------------------------------------------ #
    # Generasi teks bebas (digunakan ChatService)
    # ------------------------------------------------------------------ #
    def generate_text(self, system_instruction, user_content, temperature=0.2):
        """Hasilkan teks bebas. Coba Gemini dulu, fallback ke custom provider.

        Mengembalikan (teks, is_fallback). Jika semua provider mati/gagal,
        teks kosong dan is_fallback=True.
        """
        # Gemini
        if self.gemini_enabled and self.gemini_client is not None:
            try:
                from google.genai import types  # type: ignore

                response = self.gemini_client.models.generate_content(
                    model=self.gemini_model,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=temperature,
                    ),
                )
                text = (response.text or "").strip() if response else ""
                if text:
                    return text, False
            except Exception:  # noqa: BLE001 - coba provider lain
                pass

        # Custom OpenAI-compatible
        if self.custom_enabled and self.custom_client is not None:
            try:
                response = self.custom_client.chat.completions.create(
                    model=self.custom_model,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=temperature,
                )
                reply = (
                    (response.choices[0].message.content or "").strip()
                    if response and response.choices
                    else ""
                )
                if reply:
                    return reply, False
            except Exception:  # noqa: BLE001
                pass

        return "", True

    # ------------------------------------------------------------------ #
    # Generasi JSON terstruktur (digunakan SearchService classify_and_rerank)
    # ------------------------------------------------------------------ #
    def generate_json(self, system_instruction, user_payload, schema, temperature=0.2):
        """Hasilkan objek JSON. Coba Gemini (response_mime_type application/json)
        dulu, fallback ke custom provider yang meminta JSON via system prompt.

        Mengembalikan (dict, is_fallback).
        """
        import json

        # Gemini
        if self.gemini_enabled and self.gemini_client is not None:
            try:
                from google.genai import types  # type: ignore

                response = self.gemini_client.models.generate_content(
                    model=self.gemini_model,
                    contents=json.dumps(user_payload, ensure_ascii=False),
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=temperature,
                    ),
                )
                if response and response.text:
                    return json.loads(response.text), False
            except Exception:  # noqa: BLE001
                pass

        # Custom OpenAI-compatible: paksa JSON melalui system prompt
        if self.custom_enabled and self.custom_client is not None:
            try:
                sys_msg = (
                    system_instruction
                    + "\nRespond ONLY with a valid JSON object. No markdown fences."
                )
                response = self.custom_client.chat.completions.create(
                    model=self.custom_model,
                    messages=[
                        {"role": "system", "content": sys_msg},
                        {
                            "role": "user",
                            "content": json.dumps(user_payload, ensure_ascii=False),
                        },
                    ],
                    temperature=temperature,
                )
                text = (
                    (response.choices[0].message.content or "").strip()
                    if response and response.choices
                    else ""
                )
                if text:
                    return json.loads(text), False
            except Exception:  # noqa: BLE001
                pass

        return None, True


db_getter = None

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "schema.sql")


def init_db_getter(getter):
    global db_getter
    db_getter = getter


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Bootstrap idempotens: aplikasi tetap jalan meski `scripts/seed.py` belum dijalankan
    (`CREATE TABLE IF NOT EXISTS` aman untuk dipanggul berulang kali).
    Juga menjalankan migration ringan untuk kolom baru pada tabel yang sudah ada."""
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    except FileNotFoundError:
        pass

    # Migration ringan: tambah kolom `title` pada triage_history jika belum ada
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(triage_history)").fetchall()]
        if "title" not in cols:
            conn.execute("ALTER TABLE triage_history ADD COLUMN title TEXT NOT NULL DEFAULT 'Tanpa Judul'")
            conn.commit()
    except sqlite3.OperationalError:
        pass


def get_db():
    if db_getter is not None:
        return db_getter()
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        _ensure_schema(g.db)
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


llm = LLM()
