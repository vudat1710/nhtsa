"""Step 3 (AI): judge. Builds the agent for one case and asks it once (or again, with the verifier's issues).

The agent gets the masked complaint and the candidate recalls, may call search_complaints, and answers JSON. Nothing
it says is used until verify.py has checked it.
"""
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from agent_framework import Agent, AgentSession, Message

from app.ai.clients import LlmSetup, error_kind, no_answer, strict_format
from app.ai.middleware import FaultMiddleware, ToolTraceMiddleware
from app.ai.prompt import INSTRUCTIONS
from app.ai.tools import search_tool
from app.models import Attempt, Complaint, Judgment

# The provider constrains every completed, non-refusal answer to the Judgment schema (strict structured output).
# Refusals, answers cut off at the token limit and blocked requests are not covered: no_answer() and error_kind()
# report them, and verify.py still checks the content (quotes, ids, numbers).
JUDGMENT_FORMAT = strict_format(Judgment)


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
    middleware = [FaultMiddleware(fault), trace] if fault else [trace]
    agent = Agent(client=llm.client, name="recall_judge", instructions=INSTRUCTIONS,
                  tools=[search_tool(con, complaint, found)], middleware=middleware,
                  default_options={"response_format": JUDGMENT_FORMAT})
    return Judge(agent, AgentSession(), trace, found)


async def ask(judge: Judge, attempt_no: int, text: str, model_name: str) -> tuple[Attempt, str, str]:
    """One turn: returns (the attempt record, the reply text, the model that answered).

    Never raises: an outage, a blocked request, a refusal or an answer cut off at the token limit becomes
    Attempt.error ("<kind>: <detail>"), which verify turns into the rules-only fallback."""
    try:
        response = await judge.agent.run([Message(role="user", contents=[text])], session=judge.session)
    except Exception as exc:
        # An exception raised inside the agent can arrive wrapped; report the cause (and its kind), not the wrapper
        cause = exc.__cause__ if isinstance(exc.__cause__, Exception) else exc
        return Attempt(n=attempt_no, error=f"{error_kind(exc)}: {cause}"), "", model_name
    usage = getattr(response, "usage_details", None) or {}
    reply = response.text or ""
    attempt = Attempt(n=attempt_no, raw=reply[:6000], error=no_answer(response),
                      input_tokens=usage.get("input_token_count") or 0,
                      output_tokens=usage.get("output_token_count") or 0)
    model = getattr(response, "model", "") or model_name
    return attempt, reply, model
