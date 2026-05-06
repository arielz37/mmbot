from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"


def load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def get_host() -> str:
    return os.environ.get("HOST", "127.0.0.1")


def get_port() -> int:
    return int(os.environ.get("PORT", "3000"))


def get_model_base_url() -> str:
    return os.environ.get("MODEL_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"


def get_model_name() -> str:
    return os.environ.get("MODEL_NAME") or os.environ.get("OPENAI_MODEL") or ""


def get_model_api_key() -> str:
    return os.environ.get("MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""


def get_model_timeout_ms() -> int:
    return int(os.environ.get("MODEL_TIMEOUT_MS", "20000"))


def get_embedding_base_url() -> str:
    return os.environ.get("EMBEDDING_BASE_URL") or get_model_base_url()


def get_embedding_model() -> str:
    return os.environ.get("EMBEDDING_MODEL") or ""


def get_embedding_api_key() -> str:
    return os.environ.get("EMBEDDING_API_KEY") or ""


def get_db_path() -> Path:
    raw = os.environ.get("APP_DB_PATH")
    if raw:
        return Path(raw).expanduser().resolve()
    return BASE_DIR / "data" / "club-bot.sqlite"


def model_configured() -> bool:
    return bool(get_model_base_url() and get_model_name() and get_model_api_key())


def embedding_configured() -> bool:
    return bool(get_embedding_base_url() and get_embedding_model() and get_embedding_api_key())
