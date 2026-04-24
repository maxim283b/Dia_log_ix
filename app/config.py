from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os

from dotenv import load_dotenv


load_dotenv()


DEFAULT_TELEGRAM_BOT_TOKEN = ""
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./digestbot.db"
DEFAULT_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LLM_API_KEY = ""
DEFAULT_LLM_MODEL = "mock"
DEFAULT_TRANSCRIPTION_MODE = "mock"
DEFAULT_TRANSCRIPTION_API_KEY = ""
DEFAULT_TRANSCRIPTION_MODEL = "whisper-1"
DEFAULT_TRANSCRIPTION_BASE_URL = ""
DEFAULT_TELEGRAM_PROXY_URL = ""
DEFAULT_TELEGRAM_SSL_VERIFY = True
DEFAULT_BOT_MODE = "polling"
DEFAULT_WEBHOOK_URL = ""
DEFAULT_BOT_USERNAME = ""
DEFAULT_APP_NAME = "telegram-digest-agent"
DEFAULT_LLM_TIMEOUT_SECONDS = 180


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str = DEFAULT_TELEGRAM_BOT_TOKEN
    database_url: str = DEFAULT_DATABASE_URL
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_api_key: str = DEFAULT_LLM_API_KEY
    llm_model: str = DEFAULT_LLM_MODEL
    transcription_mode: str = DEFAULT_TRANSCRIPTION_MODE
    transcription_api_key: str = DEFAULT_TRANSCRIPTION_API_KEY
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL
    transcription_base_url: str = DEFAULT_TRANSCRIPTION_BASE_URL
    telegram_proxy_url: str = DEFAULT_TELEGRAM_PROXY_URL
    telegram_ssl_verify: bool = DEFAULT_TELEGRAM_SSL_VERIFY
    bot_mode: str = DEFAULT_BOT_MODE
    webhook_url: str = DEFAULT_WEBHOOK_URL
    bot_username: str = DEFAULT_BOT_USERNAME
    app_name: str = DEFAULT_APP_NAME
    llm_timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "Settings":
        def env_or_default(key: str, default: str) -> str:
            value = os.getenv(key)
            if value is None:
                return default
            value = value.strip()
            return value if value else default

        def env_int_or_default(key: str, default: int) -> int:
            value = os.getenv(key)
            if value is None:
                return default
            value = value.strip()
            if not value:
                return default
            try:
                return int(value)
            except ValueError:
                return default

        def env_bool_or_default(key: str, default: bool) -> bool:
            value = os.getenv(key)
            if value is None:
                return default
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "no", "n", "off"}:
                return False
            return default

        return cls(
            telegram_bot_token=env_or_default("TELEGRAM_BOT_TOKEN", DEFAULT_TELEGRAM_BOT_TOKEN),
            database_url=env_or_default("DATABASE_URL", DEFAULT_DATABASE_URL),
            llm_base_url=env_or_default("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
            llm_api_key=env_or_default("LLM_API_KEY", DEFAULT_LLM_API_KEY),
            llm_model=env_or_default("LLM_MODEL", DEFAULT_LLM_MODEL),
            transcription_mode=env_or_default("TRANSCRIPTION_MODE", DEFAULT_TRANSCRIPTION_MODE),
            transcription_api_key=env_or_default("TRANSCRIPTION_API_KEY", DEFAULT_TRANSCRIPTION_API_KEY),
            transcription_model=env_or_default("TRANSCRIPTION_MODEL", DEFAULT_TRANSCRIPTION_MODEL),
            transcription_base_url=env_or_default("TRANSCRIPTION_BASE_URL", DEFAULT_TRANSCRIPTION_BASE_URL),
            telegram_proxy_url=env_or_default("TELEGRAM_PROXY_URL", DEFAULT_TELEGRAM_PROXY_URL),
            telegram_ssl_verify=env_bool_or_default("TELEGRAM_SSL_VERIFY", DEFAULT_TELEGRAM_SSL_VERIFY),
            bot_mode=env_or_default("BOT_MODE", DEFAULT_BOT_MODE),
            webhook_url=env_or_default("WEBHOOK_URL", DEFAULT_WEBHOOK_URL),
            bot_username=env_or_default("BOT_USERNAME", DEFAULT_BOT_USERNAME),
            app_name=env_or_default("APP_NAME", DEFAULT_APP_NAME),
            llm_timeout_seconds=env_int_or_default("LLM_TIMEOUT_SECONDS", DEFAULT_LLM_TIMEOUT_SECONDS),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
