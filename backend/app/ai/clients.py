"""Model clients (MAF chat clients): live Azure OpenAI / Foundry, offline (replay only), scripted (tests), and the
LlmSetup the pipeline receives (client + record/replay mode)."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import BaseChatClient, ChatMiddlewareLayer, ChatResponse, FunctionInvocationLayer, Message

from app.config import Settings


@dataclass
class LlmSetup:
    client: Any                     # MAF chat client: live Azure OpenAI, OfflineChatClient or ScriptedChatClient
    cassette_dir: Path | None = None
    cassette_mode: str = "live"     # replay | record | live
    model_name: str = ""
    options: dict = field(default_factory=dict)  # MAF default_options, e.g. {"reasoning": {"summary": "auto"}}


def setup_from_settings(s: Settings) -> LlmSetup:
    """Live model if configured, else offline (recorded answers only). Record mode needs a live model."""
    configured = bool(s.azure_endpoint and s.deployment)
    client = live_client(s.azure_endpoint, s.deployment, s.azure_api_version, s.max_tool_calls) if configured \
        else OfflineChatClient()
    mode = s.llm_mode.value if configured else "replay"
    # a reasoning summary changes what the model reports, not what it decides; it is shown to people, never used
    options = {"reasoning": {"summary": s.reasoning_summary}} if configured and s.reasoning_summary else {}
    return LlmSetup(client=client, cassette_dir=s.cassette_dir, cassette_mode=mode,
                    model_name=s.deployment if configured else "", options=options)


class LlmUnavailable(RuntimeError):
    """No model answer: kind = timeout | unavailable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class OfflineChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """No model configured: recorded answers still replay; anything else fails cleanly (-> fallback)."""

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        raise LlmUnavailable("unavailable", "no model endpoint configured (NHTSA_AZURE_ENDPOINT)")


class ScriptedChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Tests: returns prepared turns in order: a JSON string, a callable(messages) -> str, or a list of af.Content."""

    def __init__(self, turns: list, **kwargs):
        super().__init__(**kwargs)
        self.turns, self.seen = list(turns), []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        if callable(turn):
            turn = turn(messages)
        contents = turn if isinstance(turn, list) else [turn]
        return ChatResponse(messages=[Message(role="assistant", contents=contents)], model="scripted",
                            usage_details={"input_token_count": 1000, "output_token_count": 200})


def live_client(endpoint: str, deployment: str, api_version: str, max_tool_calls: int):
    """Azure OpenAI / Foundry via Entra ID (az login). '/openai/v1' endpoints use the v1 API (no api-version)."""
    from agent_framework.openai import OpenAIChatClient
    from azure.identity import DefaultAzureCredential

    where = {"base_url": endpoint} if "/openai/v1" in endpoint else {"azure_endpoint": endpoint,
                                                                     "api_version": api_version}
    return OpenAIChatClient(model=deployment, credential=DefaultAzureCredential(), **where,
                            function_invocation_configuration={"max_function_calls": max_tool_calls})
