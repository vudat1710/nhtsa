"""Run one follow-up question: build the agent, ask, verify, repair once. Never raises."""
import sqlite3
from datetime import UTC, datetime

from agent_framework import Agent, Message
from pydantic import BaseModel, ValidationError

from app.ai.clients import LlmSetup, error_kind, no_answer, strict_format
from app.ai.middleware import ToolTraceMiddleware
from app.ai.tools import PREVIEW_CHARS, search_tool
from app.ask.prompt import INSTRUCTIONS, AskAnswer, case_record, parse
from app.ask.verify import check
from app.models import Result

ANSWER_FORMAT = strict_format(AskAnswer)  # the provider constrains completed, non-refusal answers to this schema
BLOCKED = AskAnswer(answer="This question was blocked by the AI provider's safety filter, so it was not answered. "
                           "The case and its suggestion are unchanged.", scope="out_of_scope")


class Turn(BaseModel):
    """One question and its answer, stored on the ticket."""
    question: str
    answer: AskAnswer | None = None
    verified: bool = False
    issues: list[str] = []
    searches: list[dict] = []
    blocked: bool = False             # the provider's safety filter refused the question (answer written by code)
    error: str | None = None
    result_id: str = ""
    at: str = ""


def earlier_complaints(con: sqlite3.Connection, r: Result) -> dict[int, dict]:
    """Earlier complaints the main check cited, with their text (all received before this complaint)."""
    out = {}
    if not r.judgment:
        return out
    for similar in r.judgment.similar:
        row = con.execute("SELECT received, text FROM complaints WHERE odino = ? AND received < ?",
                          (similar.odino, r.complaint.received)).fetchone()
        if row:
            out[similar.odino] = {"received": row[0], "text": row[1][:PREVIEW_CHARS], "full": row[1]}
    return out


async def ask(con: sqlite3.Connection, llm: LlmSetup, r: Result, history: list[Turn], question: str,
              related: list[dict] = ()) -> Turn:
    """related: recalls of the same part on other model years (the same context the analyst sees on the ticket)."""
    turn = Turn(question=question, result_id=r.id, at=datetime.now(UTC).isoformat(timespec="seconds"))
    earlier = earlier_complaints(con, r)
    # Full texts of every complaint the answer may quote; search_complaints adds the ones it finds.
    found: dict[int, str] = {odino: complaint["full"] for odino, complaint in earlier.items()}
    trace = ToolTraceMiddleware()
    agent = Agent(client=llm.client, name="case_assistant", instructions=INSTRUCTIONS,
                  tools=[search_tool(con, r.complaint, found)], middleware=[trace],
                  default_options={"response_format": ANSWER_FORMAT})

    # The case record shows the agent only a preview of each earlier complaint, not the full text.
    earlier_previews = {}
    for odino, complaint in earlier.items():
        earlier_previews[odino] = {key: value for key, value in complaint.items() if key != "full"}
    messages = [Message(role="user", contents=[case_record(r, earlier_previews, related)])]
    for past in history:  # earlier questions on this ticket, so follow-ups make sense
        messages.append(Message(role="user", contents=[past.question]))
        if past.answer:
            messages.append(Message(role="assistant", contents=[past.answer.answer]))
    messages.append(Message(role="user", contents=[question]))

    try:
        for attempt in (1, 2):  # the first answer, and one repair if it fails verification
            resp = await agent.run(messages)
            problem = no_answer(resp)  # refused, cut off or filtered: strict output does not cover these
            if problem and problem.startswith("content_filter"):
                turn.blocked, turn.verified, turn.answer = True, True, BLOCKED
                break
            if problem:
                turn.error = problem
                break
            try:
                turn.answer = parse(resp.text or "")
                turn.issues = check(turn.answer, r, found, question, related)
            except (ValidationError, ValueError) as exc:
                first_error_line = str(exc).splitlines()[0][:200]
                turn.answer = None
                turn.issues = [f"the answer was not valid JSON: {first_error_line}"]
            if not turn.issues:
                turn.verified = True
                break
            if attempt == 1:
                repair_request = ("Your answer failed verification:\n- " + "\n- ".join(turn.issues)
                                  + "\nReturn the corrected JSON object only.")
                messages.append(Message(role="assistant", contents=[resp.text or ""]))
                messages.append(Message(role="user", contents=[repair_request]))
    except Exception as exc:  # outage, provider error: the analyst sees that the assistant is unavailable
        if error_kind(exc) == "content_filter" or "content management policy" in str(exc):
            # the provider's safety filter blocked the question itself (e.g. an attempt to override the rules)
            turn.blocked, turn.verified, turn.answer = True, True, BLOCKED
        else:
            turn.error = str(exc)[:300]
    turn.searches = [{"query": call["arguments"].get("query", ""), "results": call["results"]}
                     for call in trace.calls]
    return turn
