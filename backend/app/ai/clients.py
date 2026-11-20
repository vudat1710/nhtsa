"""Model clients (MAF chat clients): live Azure OpenAI / Foundry, scripted (tests), and the LlmSetup the pipeline
receives. No model configured -> no LlmSetup: the pipeline answers with the rules alone, labelled."""
from dataclasses import dataclass
from typing import Any

from agent_framework import BaseChatClient, ChatMiddlewareLayer, ChatResponse, FunctionInvocationLayer, Message

from app.config import Settings


@dataclass
class LlmSetup:
    client: Any                     # MAF chat client: live Azure OpenAI or ScriptedChatClient
    model_name: str = ""


def setup_from_settings(settings: Settings) -> LlmSetup | None:
    if not (settings.azure_endpoint and settings.deployment):
        return None
    client = live_client(settings.azure_endpoint, settings.deployment, settings.azure_api_version,
                         settings.max_tool_calls)
    return LlmSetup(client=client, model_name=settings.deployment)


class LlmUnavailable(RuntimeError):
    """No model answer: kind = timeout | unavailable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class ScriptedChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Tests: returns prepared turns in order: a JSON string, a callable(messages) -> str, or a list of af.Content."""

    def __init__(self, turns: list, **kwargs):
        super().__init__(**kwargs)
        self.turns = list(turns)
        self.seen = []  # the messages each call received, for assertions

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

    if "/openai/v1" in endpoint:
        where = {"base_url": endpoint}
    else:
        where = {"azure_endpoint": endpoint, "api_version": api_version}
    return OpenAIChatClient(model=deployment, credential=DefaultAzureCredential(), **where,
                            function_invocation_configuration={"max_function_calls": max_tool_calls})
