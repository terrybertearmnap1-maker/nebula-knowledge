"""Application settings, loaded from environment variables or a local .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    The app defaults to DeepSeek's OpenAI-compatible endpoint. If no API key is
    configured it automatically starts in demo mode, so the API can be tried
    without any external credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Nebula Knowledge"
    environment: str = "development"

    # LLM configuration (any OpenAI-compatible provider works).
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=60.0, gt=0)

    # Set DEMO_MODE=true to force the deterministic offline model.
    demo_mode: bool | None = None

    # Web search. "auto" uses Tavily when a key exists, otherwise DuckDuckGo.
    web_search_provider: Literal["auto", "tavily", "bing", "ddgs", "disabled"] = "auto"
    tavily_api_key: SecretStr | None = None
    web_search_max_results: int = Field(default=5, ge=1, le=10)
    web_search_timeout_seconds: float = Field(default=20.0, gt=0, le=60)

    # Team knowledge base.
    data_dir: Path = Path("data")
    max_upload_mb: int = Field(default=10, ge=1, le=50)
    chunk_size: int = Field(default=900, ge=200, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)

    max_input_chars: int = Field(default=4000, ge=1)

    # Comma-separated list. "*" allows every origin (fine for local demos).
    cors_origins: str = "*"

    @property
    def is_demo(self) -> bool:
        """Use the offline model when explicitly requested or no key exists."""
        return self.demo_mode if self.demo_mode is not None else self.api_key is None

    @property
    def api_key(self) -> str | None:
        if self.llm_api_key is None:
            return None
        value = self.llm_api_key.get_secret_value().strip()
        return value or None

    @property
    def tavily_key(self) -> str | None:
        if self.tavily_api_key is None:
            return None
        value = self.tavily_api_key.get_secret_value().strip()
        return value or None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
