"""
services/translation_service/config/settings.py

Pydantic Settings model for AuroLab.
Reads from environment variables and .env file automatically.

Usage:
    from services.translation_service.config.settings import get_settings
    settings = get_settings()
    print(settings.groq_api_key)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AurolabSettings(BaseSettings):
    """
    All AuroLab configuration in one place.
    Values are read from environment variables (case-insensitive).
    Falls back to .env file if present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────
    groq_api_key: str = Field(default="", description="Groq API key")
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model name",
    )

    # ── Server ───────────────────────────────────────────────
    port: int = Field(default=8080)
    env: Literal["dev", "prod"] = Field(default="prod")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    allowed_origins: str = Field(default="*")

    # ── Data storage ─────────────────────────────────────────
    chroma_persist: str = Field(default="./data/chroma")
    registry_path: str = Field(default="./data/registry.json")
    telemetry_db: str = Field(default="./data/telemetry.db")

    # ── RAG pipeline ─────────────────────────────────────────
    use_hyde: bool = Field(default=True)
    use_reranker: bool = Field(default=True)
    rag_top_k: int = Field(default=5, ge=1, le=20)
    embed_model: str = Field(default="all-MiniLM-L6-v2")

    # ── Simulation ───────────────────────────────────────────
    aurolab_sim_mode: Literal["mock", "pybullet", "live"] = Field(default="pybullet")
    isaac_sim_host: str = Field(default="localhost")
    isaac_sim_port: int = Field(default=5555)
    isaac_sim_timeout: float = Field(default=120.0)

    # ── Vision ───────────────────────────────────────────────
    aurolab_vision_backend: Literal["mock", "groq", "cosmos"] = Field(default="mock")

    # ── Dashboard ────────────────────────────────────────────
    api_base_url: str = Field(default="http://localhost:8080")

    @field_validator("groq_api_key")
    @classmethod
    def warn_missing_key(cls, v: str) -> str:
        if not v:
            import warnings
            warnings.warn(
                "GROQ_API_KEY is not set. Protocol generation will fail. "
                "Set it in .env or as an environment variable.",
                RuntimeWarning,
                stacklevel=2,
            )
        return v

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


@lru_cache(maxsize=1)
def get_settings() -> AurolabSettings:
    """
    Return a cached Settings instance.
    Call get_settings.cache_clear() in tests to reset.
    """
    return AurolabSettings()