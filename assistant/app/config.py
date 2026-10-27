"""Configuration for the AI Personal Assistant.

Everything is driven by environment variables so the same code runs in
"offline demo" mode (no API keys at all) and in "full AI" mode (any
OpenAI-compatible LLM endpoint: OpenAI, Groq, OpenRouter, Ollama, ...).

See ``.env.example`` for the full list.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # assistant/
DATA_DIR = Path(os.environ.get("ASSISTANT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("ASSISTANT_DB_PATH", DATA_DIR / "assistant.db"))
UPLOAD_DIR = DATA_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

# --- LLM (OpenAI-compatible chat completions API) ---------------------------
LLM_API_KEY = (
    os.environ.get("LLM_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or ""
).strip()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "45"))

# --- uploads -----------------------------------------------------------------
MAX_UPLOAD_MB = float(os.environ.get("ASSISTANT_MAX_UPLOAD_MB", "15"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}

# --- auth --------------------------------------------------------------------
TOKEN_TTL_SECONDS = int(os.environ.get("ASSISTANT_TOKEN_TTL", str(7 * 24 * 3600)))


def get_secret() -> str:
    """HMAC signing secret for auth tokens.

    Taken from ASSISTANT_SECRET if set; otherwise a random secret is generated
    once and persisted in the data directory (so restarts don't invalidate
    every login). Never commit the generated file - ``data/`` is gitignored.
    """
    env_secret = os.environ.get("ASSISTANT_SECRET", "").strip()
    if env_secret:
        return env_secret
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file = DATA_DIR / ".secret"
    try:
        existing = secret_file.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    except OSError:
        pass
    new_secret = secrets.token_hex(32)
    try:
        secret_file.write_text(new_secret, encoding="utf-8")
    except OSError:
        pass
    return new_secret


SECRET = get_secret()


def llm_enabled() -> bool:
    return bool(LLM_API_KEY)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
