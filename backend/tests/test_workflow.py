"""The whole workflow with a scripted model: happy path, tool use, repair, fallback, and AI off."""
import asyncio
import json
from types import SimpleNamespace

from agent_framework import ChatResponse, Content, Message

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.ai.middleware import FaultMiddleware
from app.pipeline.workflow import run

GOOD = json.dumps({
    "checks": [{"campno": "24V868000", "verdict": "same", "complaint_quote": "would not accelerate. The ICCU failed",
                "recall_quote": "stop charging the 12-volt battery", "reason": "Same ICCU failure."}],
    "proposed": "known_recall", "summary": "The complaint matches the ICCU recall."})


def go(con, complaint, turns, fault=None, use_llm=True):
    client = ScriptedChatClient(turns, function_invocation_configuration={"max_function_calls": 2})
    events: list[dict] = []
    result = asyncio.run(run(con, complaint, LlmSetup(client=client), use_llm=use_llm, fault=fault,
                             emit=events.append))
    return result, client, events


def test_happy_path(con, iccu_complaint):
    r, client, events = go(con, iccu_complaint, [GOOD])
    assert r.steps == ["intake", "evidence", "judge", "verify", "decide"]
    assert (r.decision.outcome, r.decision.campno, r.decision.source) == ("known_recall", "24V868000", "ai_verified")
    sent = json.loads(client.seen[0][-1].text.removeprefix("Case:\n"))["complaint"]
    assert "24V-868" not in sent and "[recall no. removed]" in sent  # the AI never sees the cited number
    assert [e["step"] for e in events if e["type"] == "step"] == r.steps


def test_tool_results_can_be_cited(con, iccu_complaint):
    call = Content.from_function_call("c1", "search_complaints", arguments={"query": "ICCU power failure"})
    answer = json.loads(GOOD) | {"similar": [{"odino": 5, "quote": "power system failure, ICCU"}]}
    r, _, events = go(con, iccu_complaint, [[call], json.dumps(answer)])
    assert r.decision.source == "ai_verified" and r.judgment.similar[0].odino == 5
    assert r.tool_calls[0]["tool"] == "search_complaints" and 5 in r.tool_calls[0]["results"]
    assert any(e["type"] == "tool_call" for e in events)


def test_concurrent_cases_share_the_connection_safely(con, iccu_complaint):
    """Regression: a sync tool ran in worker threads and broke the shared sqlite connection under concurrency."""
    async def one():
        call = Content.from_function_call("c1", "search_complaints", arguments={"query": "ICCU power failure"})
        client = ScriptedChatClient([[call], GOOD], function_invocation_configuration={"max_function_calls": 2})
        return await run(con, iccu_complaint, LlmSetup(client=client))

    async def many():
        return await asyncio.gather(*(one() for _ in range(8)))

    results = asyncio.run(many())
    assert all(r.tool_calls[0]["results"] for r in results)
    assert all(r.decision.source == "ai_verified" for r in results)


def test_bad_answer_is_repaired_once(con, iccu_complaint):
    bad = json.loads(GOOD)
    bad["checks"][0]["recall_quote"] = "the battery may explode"
    r, client, _ = go(con, iccu_complaint, [json.dumps(bad), GOOD])
    assert r.steps == ["intake", "evidence", "judge", "verify", "judge", "verify", "decide"]
    assert r.decision.source == "ai_repaired" and r.attempts[0].issues[0].code == "quote_not_found"
    assert "failed verification" in client.seen[1][-1].text


def test_two_bad_answers_fall_back_to_rules(con, iccu_complaint):
    r, _, _ = go(con, iccu_complaint, ["not json", "still not json"])
    assert r.decision.source == "fallback" and r.judgment is None
    assert r.decision.reasons[0].startswith("Not AI-verified")


def test_model_down_falls_back_without_retrying(con, iccu_complaint):
    r, _, _ = go(con, iccu_complaint, [], fault="llm_down")
    assert r.steps == ["intake", "evidence", "judge", "verify", "decide"]
    assert r.decision.source == "fallback" and r.attempts[0].error.startswith("unavailable")


def test_injected_fault_is_caught_by_the_verifier(con, iccu_complaint):
    r, _, _ = go(con, iccu_complaint, [GOOD, GOOD], fault="malformed_json")
    assert r.attempts[0].issues[0].code == "malformed_output" and r.decision.source == "ai_repaired"


def test_injected_fault_keeps_the_conversation_ids():
    """Regression: the drill replaced the whole response, dropping the ids the Responses API session uses, so the
    repair turn reached the model without the case."""
    ctx = SimpleNamespace(result=ChatResponse(messages=[Message(role="assistant", contents=[GOOD])],
                                              response_id="resp_1", conversation_id="resp_1"))

    async def nothing():
        return None

    asyncio.run(FaultMiddleware("malformed_json").process(ctx, nothing))
    assert ctx.result.conversation_id == "resp_1" and ctx.result.response_id == "resp_1"
    assert ctx.result.text == GOOD[: len(GOOD) // 2]


def test_unknown_year_skips_the_ai(con, iccu_complaint):
    r, client, _ = go(con, iccu_complaint.model_copy(update={"year": "9999"}), [GOOD])
    assert "judge" not in r.steps and r.decision.outcome == "needs_info" and client.seen == []


def test_ai_off_uses_the_rules_baseline(con, iccu_complaint):
    r, _, _ = go(con, iccu_complaint, [], use_llm=False)
    assert r.decision.source == "rules" and r.decision.campno == "24V868000"
