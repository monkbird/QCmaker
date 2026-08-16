from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_PATH, env_file_encoding="utf-8", extra="ignore", case_sensitive=True)
    PROJECT_NAME: str = "Smart QC-Circle Generator"
    OPENAI_API_KEY: str | None = None
    LLM_PROVIDER: str = "openai"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    USE_LOCAL_LLM: bool = False
    LOCAL_LLM_URL: str = "http://localhost:11434/v1"
    LOCAL_LLM_MODEL: str = "llama3"
    TAVILY_API_KEY: str | None = None
    MAX_BUDGET_USD: float = Field(default=5.0, ge=0)
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=2048, ge=1)
    UNKNOWN_MODEL_RESERVE_USD: float = Field(default=0.25, gt=0)
    CORS_ORIGINS: str = "http://localhost:5173"
    DATASET_TTL_HOURS: int = 24
    PPT_TTL_DAYS: int = 7
    CONFIG_REVISION: int = 0

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]


_lock = threading.RLock()
settings = Settings(_env_file=ENV_PATH)


def update_settings(values: dict[str, Any]) -> Settings:
    global settings
    with _lock:
        current = {key: value for key, value in settings.model_dump().items() if value is not None}
        if ENV_PATH.exists():
            current.update({key: value for key, value in dotenv_values(ENV_PATH).items() if value is not None})
        for key, value in values.items():
            if value is not None and not (key.endswith("_KEY") and value == ""):
                current[key] = "true" if value is True else "false" if value is False else str(value)
        current["CONFIG_REVISION"] = str(settings.CONFIG_REVISION + 1)
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".env.", dir=ENV_PATH.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                for key in sorted(current):
                    if current[key] is not None:
                        stream.write(f"{key}={str(current[key]).replace(chr(10), '')}\n")
            os.replace(temp_name, ENV_PATH)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        settings = Settings(_env_file=ENV_PATH)
        return settings


def get_settings() -> Settings:
    return settings
