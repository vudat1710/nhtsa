"""MAF middleware around the agent.

- CassetteMiddleware (chat)   replay recorded model answers offline, or record live ones (tests, reviewers, demo)
- FaultMiddleware (chat)      break the model on purpose, so the repair and fallback paths run for real
- ToolTraceMiddleware (fn)    record every tool call for the audit trail and the UI
"""
import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from agent_framework import (
    ChatContext,
    ChatMiddleware,
    ChatResponse,
    FunctionInvocationContext,
    FunctionMiddleware,
    Message,
)

from app.ai.clients import LlmUnavailable


def cassette_key(context: ChatContext) -> str:
    """Same conversation + instructions + tools -> same key, so a recording replays only for an identical request."""
    payload = {"messages": [m.to_dict() for m in context.messages],
               "instructions": (context.options or {}).get("instructions"),
               "tools": sorted(getattr(t, "name", str(t)) for t in (context.options or {}).get("tools") or [])}
    raw = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


class CassetteMiddleware(ChatMiddleware):
    """replay: serve recorded answers, never call the model; record: call it and save; live: pass through."""

    def __init__(self, directory: Path, mode: str):
        self.dir, self.mode = directory, mode

    async def process(self, context: ChatContext, call_next) -> None:
        if self.mode == "live":
            await call_next()
            return
        path = self.dir / f"{cassette_key(context)}.json"
        if self.mode == "replay":
            if not path.exists():
                raise LlmUnavailable("unavailable", f"no recording {path.name} (replay mode, no live model)")
            context.result = ChatResponse.from_dict(json.loads(path.read_text(encoding="utf-8")))
            return
        await call_next()
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(context.result.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8",
                        newline="\n")


class FaultMiddleware(ChatMiddleware):
    """llm_down: every call fails. malformed_json / bad_quote / unknown_recall: the first final answer is corrupted, so
    the repair path runs. Suffix ':always' corrupts every answer, forcing the fallback."""

    MODES = ("llm_down", "malformed_json", "bad_quote", "unknown_recall")

    def __init__(self, mode: str):
        self.mode, _, always = mode.partition(":")
        if self.mode not in self.MODES:
            raise ValueError(f"unknown fault mode '{mode}'")
        self.always, self.done = always == "always", False

    async def process(self, context: ChatContext, call_next) -> None:
        if self.mode == "llm_down":
            raise LlmUnavailable("unavailable", "injected fault: model unavailable")
        if self.done and not self.always:
            await call_next()
            return
        await call_next()
        text = context.result.text if context.result else ""
        if not text.strip().startswith("{"):
            return  # a tool-call turn; corrupt the final answer only
        self.done = True
        context.result = ChatResponse(messages=[Message(role="assistant", contents=[corrupt(text, self.mode)])],
                                      model=context.result.model, usage_details=context.result.usage_details)


def corrupt(text: str, mode: str) -> str:
    if mode == "malformed_json":
        return text[: len(text) // 2]
    data = json.loads(text)
    if not data.get("checks"):
        data["checks"] = [{"campno": "00V000000", "verdict": "different", "complaint_quote": "x",
                           "recall_quote": "x", "reason": "injected"}]
    if mode == "bad_quote":
        data["checks"][0]["complaint_quote"] = "the vehicle exploded without any warning at all"
    else:  # unknown_recall
        data["checks"][0]["campno"] = "99V999000"
    return json.dumps(data)


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
