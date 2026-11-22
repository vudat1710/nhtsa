"""Settings from environment / .env (prefix NHTSA_). Pick one way to reach a model, or none:
  - Azure OpenAI / Foundry: NHTSA_AZURE_ENDPOINT + NHTSA_DEPLOYMENT, signed in with `az login` (Entra ID), or with
    NHTSA_AZURE_API_KEY;
  - OpenAI: NHTSA_OPENAI_API_KEY + NHTSA_OPENAI_MODEL.
Keys go in .env only (git-ignored). With none set, the app runs on stored results and labels new checks "AI is off"."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NHTSA_", env_file=ROOT / ".env", extra="ignore")

    azure_endpoint: str = ""          # https://<resource>.services.ai.azure.com/openai/v1; empty = no Azure model
    azure_api_version: str = "2025-04-01-preview"
    deployment: str = ""
    azure_api_key: str = ""           # optional: key auth instead of `az login`
    openai_api_key: str = ""          # OpenAI instead of Azure (used only when no Azure endpoint is set)
    openai_model: str = ""
    db_path: Path = ROOT / "data" / "nhtsa.db"      # NHTSA data, read-only
    app_db_path: Path = ROOT / "data" / "app.db"    # results and reviews written by the app
    max_tool_calls: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
