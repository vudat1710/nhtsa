"""LLM-as-judge: blind labels are validated, and the comparison treats a replaced recall as the same failure."""
import asyncio
import json

from test_workflow import GOOD, go

from app.ai.clients import LlmSetup, ScriptedChatClient
from app.eval.llm_judge import compare, judge_message, label_one


def label(con, result, answer):
    client = ScriptedChatClient([json.dumps(answer)])
    return asyncio.run(label_one(LlmSetup(client=client), result)), client


def test_the_judge_is_blind_to_the_answer_and_the_owners_recall(con, iccu_complaint):
    r = go(con, iccu_complaint, [GOOD])[0]
    sent = judge_message(r)
    assert "24V868000" in sent                                 # the candidates are shown
    assert "known_recall" not in sent and "Same ICCU failure." not in sent  # not the system's outcome or reason
    assert "24V-868" not in json.loads(sent)["complaint"]      # the owner's cited number stays masked


def test_a_label_must_be_a_candidate_none_or_unclear(con, iccu_complaint):
    r = go(con, iccu_complaint, [GOOD])[0]
    out, client = label(con, r, {"label": "24V204000", "reason": "Same ICCU failure."})
    assert out == {"label": "24V204000", "reason": "Same ICCU failure.", "error": None}
    assert client.options[0]["response_format"]["json_schema"]["strict"] is True
    assert label(con, r, {"label": "99V999000", "reason": "x"})[0]["error"].startswith("not a candidate")
    assert label(con, r, {"label": "unclear", "reason": "x"})[0]["label"] == "unclear"


def test_comparison_counts_agreement_and_the_costly_error(con, iccu_complaint):
    r = go(con, iccu_complaint, [GOOD])[0]                     # the system says known recall 24V-868
    results = {r.complaint.odino: r}
    replaced = compare(results, [{"odino": r.complaint.odino, "set": "A", "label": "24V204000"}],
                       {r.complaint.odino: "24V868000"})
    assert replaced["system_known"]["judge_agrees"]["k"] == 1  # 24V-204 was replaced by 24V-868: same failure
    assert replaced["judge_vs_owner"]["k"] == 1
    none = compare(results, [{"odino": r.complaint.odino, "set": "B", "label": "none"}], {})
    assert none["system_known"]["judge_says_none"]["k"] == 1 and none["judge_says_none"]["system_said_known"]["k"] == 1
