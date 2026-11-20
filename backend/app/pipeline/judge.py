"""Step 3 (AI): judge. Builds the agent for one case and asks it once (or again, with the verifier's issues).

The agent gets the masked complaint and the candidate recalls, may call search_complaints, and answers JSON. Nothing
it says is used until verify.py has checked it.
"""
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from agent_framework import Agent, AgentSession, Message

from app.ai.clients import LlmSetup, LlmUnavailable
from app.ai.middleware import CassetteMiddleware, FaultMiddleware, ToolTraceMiddleware
from app.ai.prompt import INSTRUCTIONS
from app.ai.tools import search_tool
from app.models import Attempt, Complaint


@dataclass
class Judge:
    agent: Agent
    session: AgentSession           # keeps the conversation (incl. tool calls) so the repair turn has context
    trace: ToolTraceMiddleware
    found: dict[int, str]           # complaint texts the search tool returned, for the verifier


def build_judge(con: sqlite3.Connection, complaint: Complaint, llm: LlmSetup, fault: str | None,
                on_tool_call: Callable[[dict], None]) -> Judge:
    found: dict[int, str] = {}
    trace = ToolTraceMiddleware(on_tool_call)
    middleware: list = [FaultMiddleware(fault)] if fault else []
    if llm.cassette_dir is not None:
        middleware.append(CassetteMiddleware(llm.cassette_dir, llm.cassette_mode))
    middleware.append(trace)
    agent = Agent(client=llm.client, name="recall_judge", instructions=INSTRUCTIONS,
                  tools=[search_tool(con, complaint, found)], middleware=middleware)
    return Judge(agent, AgentSession(), trace, found)


async def ask(judge: Judge, n: int, text: str, model_name: str) -> tuple[Attempt, str, str]:
    """One turn. Never raises: an outage or provider error becomes Attempt.error (-> fallback in verify)."""
    try:
        r = await judge.agent.run([Message(role="user", contents=[text])], session=judge.session)
        usage = getattr(r, "usage_details", None) or {}
        reply = r.text or ""
        return (Attempt(n=n, raw=reply[:6000], input_tokens=usage.get("input_token_count") or 0,
                        output_tokens=usage.get("output_token_count") or 0),
                reply, getattr(r, "model", "") or model_name)
    except Exception as exc:
        cause = exc.__cause__ if isinstance(exc.__cause__, LlmUnavailable) else exc
        return Attempt(n=n, error=f"{getattr(cause, 'kind', 'error')}: {cause}"), "", model_name
