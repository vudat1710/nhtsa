"""The whole workflow with a scripted model: happy path, tool use, repair, fallback, and AI off."""
import asyncio
import json
from types import SimpleNamespace

from agent_framework import ChatResponse, Content, Message
from agent_framework.exceptions import ChatClientContentFilterException  # parent of OpenAIContentFilterException

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.ai.middleware import FaultMiddleware
from app.pipeline.workflow import run
from app.store.results import Store
from app.workspace.suggest import suggest

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
    assert r.decision.reasons[0].startswith("The AI could not check")


def test_fallback_never_matches_a_recall_by_component_alone(con, iccu_complaint, tmp_path):
    """Regression (review of 0eb81e1): demo D2 through the fallback became "known recall: link and close", with the
    text "Same problem". An air bag that did not deploy is not the recall about air bags deploying when they
    shouldn't, although both are AIR BAGS."""
    airbag = iccu_complaint.model_copy(update={
        "text": "The air bags did not deploy during the crash and the car caught fire afterwards.",
        "components": ["AIR BAGS"], "crash": 1, "fire": 1})
    r, _, _ = go(con, airbag, ["not json", "still not json"])
    d = r.decision
    assert (d.outcome, d.campno, d.escalate, d.source) == ("needs_info", None, True, "fallback")
    s = suggest(r, Store(tmp_path / "app.db").tickets, can_recheck=True)
    assert s.headline.startswith("Not checked by the AI")
    assert not any("Same problem" in why.text for why in s.why)
    assert [a.id for a in s.actions if a.primary] == ["new_issue"]          # crash + fire: to engineering first
    assert all("after comparing it yourself" in a.label for a in s.actions if a.id == "link_close")


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


def test_judge_asks_for_strict_structured_output(con, iccu_complaint):
    _, client, _ = go(con, iccu_complaint, [GOOD])
    fmt = client.options[0]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert set(fmt["json_schema"]["schema"]["required"]) == {"checks", "similar", "proposed", "summary", "questions"}


# What strict structured output does not cover (OpenAI: "refusals, incomplete responses, and API errors"): each is
# reported with its own kind and falls back to the rules without a retry.
def test_answer_cut_off_at_the_token_limit_falls_back(con, iccu_complaint):
    cut = ChatResponse(messages=[Message(role="assistant", contents=[GOOD[:40]])], finish_reason="length")
    r, client, _ = go(con, iccu_complaint, [cut])
    assert r.decision.source == "fallback" and r.attempts[0].error.startswith("incomplete")
    assert len(client.seen) == 1  # no retry


def test_refusal_falls_back(con, iccu_complaint):
    refusal = Content.from_text("I can't help with that.", additional_properties={"model_output_kind": "refusal"})
    r, _, _ = go(con, iccu_complaint, [[refusal]])
    assert r.decision.source == "fallback" and r.attempts[0].error.startswith("refused: I can't help")


def test_content_filter_block_is_reported_as_such(con, iccu_complaint):
    def blocked(messages):
        raise ChatClientContentFilterException("The response was filtered due to the prompt triggering Azure "
                                               "OpenAI's content management policy.")
    r, client, _ = go(con, iccu_complaint, [blocked])
    assert r.decision.source == "fallback" and r.attempts[0].error.startswith("content_filter")
    assert len(client.seen) == 1


def test_refusal_drill(con, iccu_complaint):
    r, _, _ = go(con, iccu_complaint, [GOOD], fault="refusal")
    assert r.decision.source == "fallback" and r.attempts[0].error.startswith("refused")


def test_incomplete_drill_lowers_the_output_limit(con, iccu_complaint):
    cut = ChatResponse(messages=[Message(role="assistant", contents=["{"])], finish_reason="length")
    r, client, _ = go(con, iccu_complaint, [cut], fault="incomplete")
    assert client.options[0]["max_tokens"] == FaultMiddleware.TINY_OUTPUT_LIMIT
    assert r.decision.source == "fallback" and r.attempts[0].error.startswith("incomplete")


def test_unknown_year_skips_the_ai(con, iccu_complaint):
    r, client, _ = go(con, iccu_complaint.model_copy(update={"year": "9999"}), [GOOD])
    assert "judge" not in r.steps and r.decision.outcome == "needs_info" and client.seen == []


def test_ai_off_uses_the_rules_baseline(con, iccu_complaint):
    r, _, _ = go(con, iccu_complaint, [], use_llm=False)
    assert r.decision.source == "rules" and r.decision.outcome == "needs_info" and r.decision.campno is None

def test_a_cut_candidate_list_never_reads_as_no_recall_covers_this(con, iccu_complaint, tmp_path):
    """Regression (review of 0eb81e1): with 15 of 36 recalls reviewed, the ticket said "No recall covers this"."""
    from app.pipeline.decide import decide

    nothing = json.dumps({"checks": [], "proposed": "possible_new", "summary": "Nothing fits."})
    r, _, _ = go(con, iccu_complaint, [nothing])
    shown = len(r.evidence.recalls)
    cut = r.model_copy(update={"evidence": r.evidence.model_copy(update={"recalls_total": shown + 21})})
    d = decide(cut.complaint, cut.intake, cut.evidence, cut.judgment, "ai_verified")
    assert "incomplete_review" in d.flags and d.confidence == "low"
    s = suggest(cut.model_copy(update={"decision": d}), Store(tmp_path / "app.db").tickets)
    assert s.headline.startswith(f"No match among the {shown} of {shown + 21} recalls reviewed")
    assert any(w.text.startswith("21 more recalls on this vehicle were not reviewed") for w in s.why)
    assert not any("No recall covers this" in w.text for w in s.why)
