"""Run one follow-up question: build the agent, ask, verify, repair once. Never raises."""
import sqlite3
from datetime import UTC, datetime

from agent_framework import Agent, Message
from pydantic import BaseModel, ValidationError

from app.ai.clients import LlmSetup
from app.ai.middleware import CassetteMiddleware, ToolTraceMiddleware
from app.ai.tools import PREVIEW_CHARS, search_tool
from app.ask.prompt import INSTRUCTIONS, AskAnswer, case_record, parse
from app.ask.verify import check
from app.models import Result
from app.pipeline.judge import reasoning_of


class Turn(BaseModel):
    """One question and its answer, stored on the ticket."""
    question: str
    answer: AskAnswer | None = None
    verified: bool = False
    issues: list[str] = []
    reasoning: str = ""
    searches: list[dict] = []
    blocked: bool = False             # the provider's safety filter refused the question (answer written by code)
    error: str | None = None
    result_id: str = ""
    at: str = ""


def earlier_complaints(con: sqlite3.Connection, r: Result) -> dict[int, dict]:
    """Earlier complaints the main check cited, with their text (all received before this complaint)."""
    out = {}
    for s in (r.judgment.similar if r.judgment else []):
        row = con.execute("SELECT received, text FROM complaints WHERE odino = ? AND received < ?",
                          (s.odino, r.complaint.received)).fetchone()
        if row:
            out[s.odino] = {"received": row[0], "text": row[1][:PREVIEW_CHARS], "full": row[1]}
    return out


async def ask(con: sqlite3.Connection, llm: LlmSetup, r: Result, history: list[Turn], question: str,
              related: list[dict] = ()) -> Turn:
    """related: recalls of the same part on other model years (the same context the analyst sees on the ticket)."""
    turn = Turn(question=question, result_id=r.id, at=datetime.now(UTC).isoformat(timespec="seconds"))
    earlier = earlier_complaints(con, r)
    found: dict[int, str] = {o: e["full"] for o, e in earlier.items()}
    trace = ToolTraceMiddleware()
    middleware: list = [CassetteMiddleware(llm.cassette_dir, llm.cassette_mode)] if llm.cassette_dir else []
    middleware.append(trace)
    agent = Agent(client=llm.client, name="case_assistant", instructions=INSTRUCTIONS,
                  tools=[search_tool(con, r.complaint, found)], middleware=middleware,
                  default_options=llm.options or None)
    messages = [Message(role="user", contents=[case_record(r, {o: {k: v for k, v in e.items() if k != "full"}
                                                                   for o, e in earlier.items()}, related)])]
    for past in history:  # earlier questions on this ticket, so follow-ups make sense
        messages.append(Message(role="user", contents=[past.question]))
        if past.answer:
            messages.append(Message(role="assistant", contents=[past.answer.answer]))
    messages.append(Message(role="user", contents=[question]))
    try:
        for attempt in (1, 2):
            resp = await agent.run(messages)
            turn.reasoning = reasoning_of(resp)[:3000] or turn.reasoning
            try:
                turn.answer = parse(resp.text or "")
                turn.issues = check(turn.answer, r, found, question, related)
            except (ValidationError, ValueError) as exc:
                turn.answer, turn.issues = None, [f"the answer was not valid JSON: {str(exc).splitlines()[0][:200]}"]
            if not turn.issues:
                turn.verified = True
                break
            if attempt == 1:
                messages += [Message(role="assistant", contents=[resp.text or ""]),
                             Message(role="user", contents=["Your answer failed verification:\n- "
                                                            + "\n- ".join(turn.issues)
                                                            + "\nReturn the corrected JSON object only."])]
    except Exception as exc:  # outage, provider error: the analyst sees that the assistant is unavailable
        if "content management policy" in str(exc) or "content_filter" in str(exc):
            # the provider's safety filter blocked the question itself (e.g. an attempt to override the rules)
            turn.blocked, turn.verified = True, True
            turn.answer = AskAnswer(answer="This question was blocked by the AI provider's safety filter, so it was "
                                           "not answered. The case and its suggestion are unchanged.",
                                    scope="out_of_scope")
        else:
            turn.error = str(exc)[:300]
    turn.searches = [{"query": c["arguments"].get("query", ""), "results": c["results"]} for c in trace.calls]
    return turn
