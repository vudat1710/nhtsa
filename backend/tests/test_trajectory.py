"""Trajectory checks: real workflow runs pass every rule, and each kind of broken path is caught."""
import json

import pytest
from agent_framework import Content
from test_workflow import GOOD, go

from app.eval.trajectory import complaint_key, evaluate

NEW_DEFECT = json.dumps({"checks": [], "proposed": "possible_new",
                         "summary": "Earlier owners describe the same failure.",
                         "similar": [{"odino": 5, "quote": "power system failure, ICCU"}]})


def failing(results, con, kinds=None) -> set[str]:
    report = evaluate(results, con, max_tool_calls=2, kinds=kinds)
    return {name for name, row in report["checks"].items() if row["k"] < row["n"]}


@pytest.fixture
def runs(con, iccu_complaint):
    """One real run of every path the workflow can take."""
    search = Content.from_function_call("c1", "search_complaints", arguments={"query": "ICCU power failure"})
    bad = json.loads(GOOD)
    bad["checks"][0]["recall_quote"] = "the battery may explode"
    return {
        "verified": go(con, iccu_complaint, [GOOD])[0],
        "searched": go(con, iccu_complaint, [[search], NEW_DEFECT])[0],
        "repaired": go(con, iccu_complaint, [json.dumps(bad), GOOD])[0],
        "model_down": go(con, iccu_complaint, [], fault="llm_down")[0],
        "rules": go(con, iccu_complaint, [], use_llm=False)[0],
        "unknown_year": go(con, iccu_complaint.model_copy(update={"year": "9999"}), [GOOD])[0],
    }


def test_every_real_path_passes_every_check(con, runs):
    assert failing(list(runs.values()), con) == set()


def broken(result, change):
    copy = result.model_copy(deep=True)
    change(copy)
    return copy


@pytest.mark.parametrize("path, change, check", [
    ("verified", lambda r: setattr(r.decision, "source", "ai_repaired"), "path.source"),
    ("verified", lambda r: setattr(r, "steps", ["intake", "judge", "evidence", "verify", "decide"]), "path.steps"),
    ("model_down", lambda r: r.attempts.append(r.attempts[0].model_copy(update={"n": 2})), "path.repair"),
    ("verified", lambda r: setattr(r.intake, "text", r.intake.text + " recall 24V-868"), "evidence.masked"),
    ("verified", lambda r: setattr(r.judgment.checks[0], "campno", "26V001000"), "evidence.candidates"),
    ("verified", lambda r: setattr(r.judgment.checks[0], "complaint_quote", "the car exploded on the road"),
     "evidence.quotes"),
    ("searched", lambda r: setattr(r.complaint, "received", "2024-06-15"), "tools.as_of"),
    ("searched", lambda r: setattr(r.judgment.similar[0], "odino", 3), "tools.cited_from_search"),
    ("searched", lambda r: r.tool_calls.extend([r.tool_calls[0]] * 2), "tools.budget"),
    ("verified", lambda r: r.tool_calls.append({"tool": "search_complaints", "arguments": {"query": "ICCU failure"},
                                                "results": [5]}), "tools.search_when_unmatched"),
    ("searched", lambda r: r.tool_calls.clear(), "tools.search_before_escalating"),
    ("searched", lambda r: r.tool_calls[0]["arguments"].update(query="see recall 24V-868"), "tools.query_quality"),
    ("verified", lambda r: setattr(r.judgment, "proposed", "possible_new"), "decision.disagreement"),
    ("verified", lambda r: setattr(r.decision, "escalate", not r.decision.escalate), "decision.escalation"),
    ("verified", lambda r: setattr(r.decision, "campno", "25V001000"), "decision.known_backed"),
])
def test_each_broken_trajectory_is_caught(con, runs, path, change, check):
    assert check in failing([broken(runs[path], change)], con)


def test_stress_scenarios_use_the_designed_path(con, runs):
    unknown_year = runs["unknown_year"]
    kinds = {complaint_key(unknown_year.complaint): "unknown_year"}
    assert failing([unknown_year], con, kinds) == set()
    # the same complaint, wrongly sent to the model, breaks the scenario and the path rule
    sent_to_model = broken(unknown_year, lambda r: setattr(r, "steps", ["intake", "evidence", "judge", "verify",
                                                                       "decide"]))
    assert {"scenario.unknown_year", "path.unknown_year"} <= failing([sent_to_model], con, kinds)

    verified = runs["verified"]
    injected = broken(verified, lambda r: setattr(r.judgment.checks[0], "campno", "99V999000"))
    assert "scenario.injection" in failing([injected], con, {complaint_key(verified.complaint): "injection"})
