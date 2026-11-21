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
    Content,
    FunctionInvocationContext,
    FunctionMiddleware,
    Message,
)

from app.ai.clients import LlmUnavailable


class FaultMiddleware(ChatMiddleware):
    """Break the model on purpose, so every failure path runs for real (ops portal drills):
    - llm_down: every call fails (-> rules-only fallback). Simulated.
    - malformed_json: the first final answer is cut in half (-> the verifier rejects it, one repair turn). Simulated:
      with strict structured output a completed answer always matches the schema.
    - incomplete: the call is sent with a tiny output-token limit, so the provider really cuts the answer off
      (-> "incomplete", fallback).
    - refusal: the first final answer is replaced by a refusal, as the provider marks one (-> "refused", fallback).
      Simulated: a real refusal cannot be triggered on demand.
    A real content-filter block needs no drill: complaints 11705719 and 11752255 trigger Azure's filter."""

    MODES = ("llm_down", "malformed_json", "incomplete", "refusal")
    TINY_OUTPUT_LIMIT = 16  # output tokens: too few for any answer, so the provider stops with finish_reason length

    def __init__(self, mode: str):
        if mode not in self.MODES:
            raise ValueError(f"unknown fault mode '{mode}'")
        self.mode = mode
        self.done = False  # True once the first final answer has been corrupted

    async def process(self, context: ChatContext, call_next) -> None:
        if self.mode == "llm_down":
            raise LlmUnavailable("unavailable", "injected fault: model unavailable")
        if self.mode == "incomplete":
            context.options["max_tokens"] = self.TINY_OUTPUT_LIMIT
        await call_next()
        if self.mode == "incomplete":
            return
        text = context.result.text if context.result else ""
        if self.done or not text.strip().startswith("{"):
            return  # already corrupted once, or a tool-call turn: corrupt the first final answer only
        self.done = True
        # change only the text: the response's ids are what lets the repair turn continue this conversation
        # (a new ChatResponse dropped them, and the model was asked to fix an answer it could no longer see)
        if self.mode == "refusal":
            refusal = Content.from_text("I'm sorry, I can't help with that request.",
                                        additional_properties={"model_output_kind": "refusal"})
            context.result.messages = [Message(role="assistant", contents=[refusal])]
        else:
            context.result.messages = [Message(role="assistant", contents=[text[: len(text) // 2]])]


class ToolTraceMiddleware(FunctionMiddleware):
    def __init__(self, on_call: Callable[[dict], None] | None = None):
        self.calls: list[dict] = []
        self.on_call = on_call

    async def process(self, context: FunctionInvocationContext, call_next) -> None:
        arguments = context.arguments
        args = arguments.model_dump() if hasattr(arguments, "model_dump") else dict(arguments)
        started = time.perf_counter()
        await call_next()

        # The result is one item or a list of content items; their text holds the ids of the complaints returned
        parts = context.result if isinstance(context.result, list) else [context.result]
        part_texts = []
        for part in parts:
            part_texts.append(str(getattr(part, "text", None) or part))
        text = " ".join(part_texts)
        odinos = [int(odino) for odino in re.findall(r'"odino": (\d+)', text)]
        call = {"tool": context.function.name, "arguments": args, "results": odinos,
                "ms": round((time.perf_counter() - started) * 1000)}
        self.calls.append(call)
        if self.on_call:
            self.on_call(call)
