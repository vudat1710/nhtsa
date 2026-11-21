"""Model clients (MAF chat clients): live Azure OpenAI / Foundry, scripted (tests), and the LlmSetup the pipeline
receives. No model configured -> no LlmSetup: the pipeline answers with the rules alone, labelled."""
from dataclasses import dataclass
from typing import Any

from agent_framework import (
    AgentResponse,
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)
from agent_framework.exceptions import ChatClientContentFilterException
from openai.lib._parsing._completions import type_to_response_format_param
from pydantic import BaseModel

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


def strict_format(model: type[BaseModel]) -> dict:
    """The model's JSON Schema as a strict structured-output format: the provider then constrains a completed,
    non-refusal answer to the schema. Built by the OpenAI SDK's own converter (the same schema it sends for a model
    class), but passed as a mapping so the framework does not parse the reply itself: we read why an answer is
    missing (refused, cut off, filtered) and parse it ourselves."""
    return type_to_response_format_param(model)


def is_refusal(content: Content) -> bool:
    props = content.additional_properties or {}
    core = props.get("core") or {}
    return "refusal" in (props.get("model_output_kind"), core.get("model_output_kind"))


def no_answer(response: ChatResponse | AgentResponse) -> str | None:
    """Why a completed call has no usable answer (strict output does not cover these), or None."""
    if response.finish_reason == "length":
        return "incomplete: the answer was cut off at the output token limit"
    if response.finish_reason == "content_filter":
        return "content_filter: the provider's content filter stopped the answer"
    for message in response.messages:
        for content in message.contents:
            if is_refusal(content):
                return f"refused: {(content.text or '')[:200]}"
    return None


def error_kind(exc: BaseException) -> str:
    """timeout | unavailable (LlmUnavailable) | content_filter (the provider blocked the request) | error."""
    for cause in (exc, exc.__cause__):
        if isinstance(cause, LlmUnavailable):
            return cause.kind
        if isinstance(cause, ChatClientContentFilterException):
            return "content_filter"
    return "error"


class ScriptedChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Tests: returns prepared turns in order: a JSON string, a callable(messages) -> str, a list of af.Content, or a
    ChatResponse (e.g. one cut off at the token limit)."""

    def __init__(self, turns: list, **kwargs):
        super().__init__(**kwargs)
        self.turns = list(turns)
        self.seen = []  # the messages each call received, for assertions
        self.options = []  # the options each call received (e.g. response_format)

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.seen.append(list(messages))
        self.options.append(dict(options or {}))
        turn = self.turns.pop(0)
        if callable(turn):
            turn = turn(messages)
        if isinstance(turn, ChatResponse):
            return turn
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
