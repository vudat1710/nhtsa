"""Ask about this case (verified follow-up answers) and the investigation trail."""
import asyncio
import json

from agent_framework import ChatResponse, Content, Message
from agent_framework.exceptions import ChatClientContentFilterException

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.ask.service import ask
from app.pipeline.workflow import run
from app.workspace.trail import trail

CHECKED = json.dumps({
    "checks": [{"campno": "24V868000", "verdict": "same", "complaint_quote": "would not accelerate. The ICCU failed",
                "recall_quote": "stop charging the 12-volt battery", "reason": "Same ICCU failure."}],
    "similar": [{"odino": 5, "quote": "power system failure, ICCU"}],
    "proposed": "known_recall", "summary": "Matches the ICCU recall."})


def checked_result(con, complaint):
    call = Content.from_function_call("c1", "search_complaints", arguments={"query": "ICCU power failure"})
    client = ScriptedChatClient([[call], CHECKED], function_invocation_configuration={"max_function_calls": 2})
    return asyncio.run(run(con, complaint, LlmSetup(client=client)))


def answer(text, citations, scope="answered", recheck=False):
    return json.dumps({"answer": text, "citations": citations, "scope": scope, "recheck": recheck})


def go(con, r, turns, question="Why this recall?", history=()):
    client = ScriptedChatClient(turns, function_invocation_configuration={"max_function_calls": 2})
    return asyncio.run(ask(con, LlmSetup(client=client), r, list(history), question)), client


def test_answer_with_verified_citations(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    good = answer("The owner's loss of acceleration matches the ICCU recall.", [
        {"kind": "complaint", "id": "100", "quote": "would not accelerate. The ICCU failed"},
        {"kind": "recall", "id": "24V-868", "quote": "may become damaged and stop charging"},
        {"kind": "earlier_complaint", "id": "5", "quote": "power system failure, ICCU"}])
    turn, client = go(con, r, [good])
    assert turn.verified and turn.issues == []
    assert "Case record" in client.seen[0][0].text  # the agent sees the case record first


def test_invented_quote_is_sent_back_once_then_flagged(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    bad = answer("It exploded.", [{"kind": "complaint", "id": "100", "quote": "the car exploded on the highway"}])
    turn, client = go(con, r, [bad, bad])
    assert not turn.verified and "not found word for word" in turn.issues[0]
    assert "failed verification" in client.seen[1][-1].text


def test_sources_outside_the_case_and_invented_numbers_are_rejected(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    future = answer("A newer recall exists.", [{"kind": "recall", "id": "26V001000", "quote": "A future recall"}])
    turn, _ = go(con, r, [future, future])
    assert "not a source of this case" in turn.issues[0]
    numbers = answer("There were 4,812 similar complaints.", [
        {"kind": "complaint", "id": "100", "quote": "would not accelerate. The ICCU failed"}])
    turn, _ = go(con, r, [numbers, numbers])
    assert any("4,812" in i for i in turn.issues)
    uncited = answer("It is the ICCU recall.", [])
    turn, _ = go(con, r, [uncited, uncited])
    assert "needs at least one citation" in turn.issues[0]


def test_saying_the_records_dont_hold_it_needs_no_citation(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    turn, _ = go(con, r, [answer("The records contain no repair history.", [], scope="not_in_records")],
                 question="Was the car repaired under the recall?")
    assert turn.verified and turn.answer.scope == "not_in_records"


def test_follow_ups_see_earlier_questions(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    first, _ = go(con, r, [answer("No repair history in the records.", [], scope="not_in_records")])
    second, client = go(con, r, [answer("As said, not in the records.", [], scope="not_in_records")],
                        question="And the dealer notes?", history=[first])
    texts = [m.text for m in client.seen[0]]
    assert "Why this recall?" in texts and "No repair history in the records." in texts and second.verified


def test_assistant_asks_for_strict_output_and_reports_what_it_does_not_cover(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    turn, client = go(con, r, [answer("No repair history in the records.", [], scope="not_in_records")])
    assert client.options[0]["response_format"]["json_schema"]["strict"] is True and turn.verified

    refusal = Content.from_text("I can't help with that.", additional_properties={"model_output_kind": "refusal"})
    turn, client = go(con, r, [[refusal]])
    assert turn.error.startswith("refused") and not turn.verified and len(client.seen) == 1
    cut = ChatResponse(messages=[Message(role="assistant", contents=['{"answer": "The'])], finish_reason="length")
    turn, _ = go(con, r, [cut])
    assert turn.error.startswith("incomplete")
    filtered = ChatResponse(messages=[Message(role="assistant", contents=[""])], finish_reason="content_filter")
    turn, _ = go(con, r, [filtered])
    assert turn.blocked and turn.answer.scope == "out_of_scope"

    def blocked(messages):
        raise ChatClientContentFilterException("filtered by the content management policy")
    turn, _ = go(con, r, [blocked])
    assert turn.blocked and turn.error is None


def test_trail_tells_the_investigation_in_order(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    steps = trail(r)
    assert [s.kind for s in steps] == ["read", "look", "search", "compare", "check", "decide"]
    assert steps[0].lines[1].startswith("1 recall number(s) the owner cited were hidden")
    assert "ICCU power failure" in steps[2].title and "complaint 5" in steps[2].lines[1]
    assert steps[3].lines[0].startswith("24V-868: same failure") and "24V-204" in steps[3].lines[-1]
    assert steps[4].status == "ok"
