"""Model clients (MAF chat clients): live Azure OpenAI / Foundry, offline (replay only), scripted (tests)."""
from agent_framework import BaseChatClient, ChatMiddlewareLayer, ChatResponse, FunctionInvocationLayer, Message


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
