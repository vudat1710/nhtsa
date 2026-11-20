"""Settings from environment / .env (prefix NHTSA_). Nothing secret: Azure auth is Entra ID via `az login`."""
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class LlmMode(StrEnum):
    REPLAY = "replay"  # recorded answers only, never calls the model (tests, reviewers without Azure)
    RECORD = "record"  # call the model and save each answer
    LIVE = "live"      # call the model, save nothing


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NHTSA_", env_file=ROOT / ".env", extra="ignore")

    llm_mode: LlmMode = LlmMode.REPLAY
    azure_endpoint: str = ""          # https://<resource>.services.ai.azure.com/openai/v1
    azure_api_version: str = "2025-04-01-preview"
    deployment: str = ""
    db_path: Path = ROOT / "data" / "nhtsa.db"      # NHTSA data, read-only
    app_db_path: Path = ROOT / "data" / "app.db"    # results and reviews written by the app
    cassette_dir: Path = ROOT / "cassettes"
    max_tool_calls: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
