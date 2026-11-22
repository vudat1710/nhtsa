"""Which model a reviewer's settings reach: Azure with `az login` or a key, OpenAI with a key, or none."""
from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.ai.clients import setup_from_settings
from app.config import Settings

V1 = "https://res.services.ai.azure.com/openai/v1"


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_no_model_configured_means_rules_only(monkeypatch):
    for name in ("NHTSA_AZURE_ENDPOINT", "NHTSA_DEPLOYMENT", "NHTSA_OPENAI_API_KEY", "NHTSA_OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert setup_from_settings(settings()) is None
    assert setup_from_settings(settings(openai_api_key="sk-test")) is None          # a key but no model


def test_azure_key_on_the_v1_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://elsewhere.example/v1")         # must not reroute the request
    setup = setup_from_settings(settings(azure_endpoint=V1, deployment="gpt-x", azure_api_key="az-key"))
    sdk = setup.client.client
    assert type(sdk) is AsyncOpenAI and str(sdk.base_url).startswith(V1) and sdk.api_key == "az-key"
    assert setup.model_name == "gpt-x"


def test_azure_key_on_the_older_endpoint():
    setup = setup_from_settings(settings(azure_endpoint="https://res.openai.azure.com/", deployment="gpt-x",
                                         azure_api_key="az-key"))
    assert isinstance(setup.client.client, AsyncAzureOpenAI) and setup.client.client.api_key == "az-key"


def test_azure_login_on_the_older_endpoint_keeps_the_older_api():
    """The framework sent these to /openai/v1/ with an api-version, which the service rejected."""
    setup = setup_from_settings(settings(azure_endpoint="https://res.openai.azure.com/", deployment="gpt-x"))
    sdk = setup.client.client
    assert isinstance(sdk, AsyncAzureOpenAI) and str(sdk.base_url).endswith("/openai/")


def test_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://elsewhere.example/v1")
    setup = setup_from_settings(settings(openai_api_key="sk-test", openai_model="gpt-y"))
    sdk = setup.client.client
    assert str(sdk.base_url).startswith("https://api.openai.com/v1") and sdk.api_key == "sk-test"
    assert setup.model_name == "gpt-y"


def test_azure_wins_when_both_are_set():
    setup = setup_from_settings(settings(azure_endpoint=V1, deployment="gpt-x", azure_api_key="az-key",
                                         openai_api_key="sk-test", openai_model="gpt-y"))
    assert setup.model_name == "gpt-x"
