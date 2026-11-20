"""MAF middleware around the agent.

- FaultMiddleware (chat)      break the model on purpose, so the repair and fallback paths run for real
- ToolTraceMiddleware (fn)    record every tool call for the audit trail and the UI
"""
import re
import time
from collections.abc import Callable

from agent_framework import (
    ChatContext,
    ChatMiddleware,
    FunctionInvocationContext,
    FunctionMiddleware,
    Message,
)

from app.ai.clients import LlmUnavailable


class FaultMiddleware(ChatMiddleware):
    """llm_down: every call fails (-> rules-only fallback). malformed_json: the first final answer is cut in half
    (-> the verifier rejects it, one repair turn)."""

    MODES = ("llm_down", "malformed_json")

    def __init__(self, mode: str):
        if mode not in self.MODES:
            raise ValueError(f"unknown fault mode '{mode}'")
        self.mode, self.done = mode, False

    async def process(self, context: ChatContext, call_next) -> None:
        if self.mode == "llm_down":
            raise LlmUnavailable("unavailable", "injected fault: model unavailable")
        await call_next()
        text = context.result.text if context.result else ""
        if self.done or not text.strip().startswith("{"):
            return  # already corrupted once, or a tool-call turn: corrupt the first final answer only
        self.done = True
        # change only the text: the response's ids are what lets the repair turn continue this conversation
        # (a new ChatResponse dropped them, and the model was asked to fix an answer it could no longer see)
        context.result.messages = [Message(role="assistant", contents=[text[: len(text) // 2]])]


class ToolTraceMiddleware(FunctionMiddleware):
    def __init__(self, on_call: Callable[[dict], None] | None = None):
        self.calls: list[dict] = []
        self.on_call = on_call

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        args = context.arguments.model_dump() if hasattr(context.arguments, "model_dump") else dict(context.arguments)
        t0 = time.perf_counter()
        await call_next()
        parts = context.result if isinstance(context.result, list) else [context.result]
        text = " ".join(str(getattr(p, "text", None) or p) for p in parts)
        call = {"tool": context.function.name, "arguments": args,
                "results": [int(x) for x in re.findall(r'"odino": (\d+)', text)],
                "ms": round((time.perf_counter() - t0) * 1000)}
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)
