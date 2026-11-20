"""Record/replay: a recorded tool-using conversation must replay exactly (regression: every tool case missed)."""
import asyncio
import json

from agent_framework import Content

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.pipeline.workflow import run

ANSWER = json.dumps({
    "checks": [{"campno": "24V868000", "verdict": "same", "complaint_quote": "would not accelerate. The ICCU failed",
                "recall_quote": "stop charging the 12-volt battery", "reason": "Same ICCU failure."}],
    "similar": [{"odino": 5, "quote": "power system failure, ICCU"}],
    "proposed": "known_recall", "summary": "Matches the ICCU recall."})


def test_tool_conversation_replays_from_recordings(con, iccu_complaint, tmp_path):
    call = Content.from_function_call("c1", "search_complaints", arguments={"query": "ICCU power failure"})
    recorder = ScriptedChatClient([[call], ANSWER], function_invocation_configuration={"max_function_calls": 2})
    recorded = asyncio.run(run(con, iccu_complaint, LlmSetup(client=recorder, cassette_dir=tmp_path,
                                                             cassette_mode="record")))
    assert len(list(tmp_path.glob("*.json"))) == 2  # the tool-call turn and the final answer

    nothing_left = ScriptedChatClient([], function_invocation_configuration={"max_function_calls": 2})
    replayed = asyncio.run(run(con, iccu_complaint, LlmSetup(client=nothing_left, cassette_dir=tmp_path,
                                                             cassette_mode="replay")))
    assert replayed.decision.source == "ai_verified", replayed.attempts
    assert replayed.judgment == recorded.judgment and nothing_left.seen == []
