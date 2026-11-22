"""The investigation trail: what the system did, in order, built from the stored run."""
import asyncio
import json

from agent_framework import Content

from app.ai.clients import LlmSetup, ScriptedChatClient
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


def test_trail_tells_the_investigation_in_order(con, iccu_complaint):
    r = checked_result(con, iccu_complaint)
    steps = trail(r)
    assert [s.kind for s in steps] == ["read", "look", "search", "compare", "check", "decide"]
    assert steps[0].lines[1].startswith("1 recall number(s) the owner cited were hidden")
    assert "ICCU power failure" in steps[2].title and "complaint 5" in steps[2].lines[1]
    assert steps[3].lines[0].startswith("24V-868: same failure") and "24V-204" in steps[3].lines[-1]
    assert steps[4].status == "ok"
