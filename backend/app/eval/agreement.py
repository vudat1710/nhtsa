"""Agreement with what owners believed: the evaluation of the AI's judgment, not of the code (and not accuracy).

Set A's label is the recall the owner named; owners are sometimes wrong. Set B's label is a fact about dates: no recall
on that vehicle + component existed yet. Both are compared on a stored run, for the AI and for the simple rule an
analyst might use instead, "newest recall on the same part" (the first same-component candidate: evidence keeps them
same-part first, newest first), with the same yardstick. No model needed.

    uv run python -m app.eval.agreement                   (the default test run)
    uv run python -m app.eval.agreement --run <name>

Writes data/eval/reports/agreement-<run>.json (shown on the operations portal's Evaluation page).
"""
import argparse
import json

from app.eval.run import ESCALATED, EVAL, rate, stored_results
from app.eval.trajectory import DEFAULT_RUN
from app.models import Result


def shortcut(result: Result) -> str | None:
    """The recall the simple rule would name: the newest candidate on the owner's component, if any."""
    for recall in result.evidence.recalls:
        if recall.same_component:
            return recall.campno
    return None


def agreement(results: list[Result], set_a: list[dict], set_b: list[dict]) -> dict:
    """set_a / set_b: the test cases of sets A and B (their odino and, for A, the owner's recall)."""
    by_odino = {result.complaint.odino: result for result in results}
    a = [(case["truth_campno"], by_odino[case["odino"]]) for case in set_a if case["odino"] in by_odino]
    b = [by_odino[case["odino"]] for case in set_b if case["odino"] in by_odino]

    ai_named = [(owner, result.decision.campno) for owner, result in a if result.decision.outcome == "known_recall"]
    rule_named = [(owner, shortcut(result)) for owner, result in a if shortcut(result)]
    return {
        "a": {
            "ai_names_a_recall": rate(a, lambda row: row[1].decision.outcome == "known_recall"),
            "ai_names_the_owners": rate(ai_named, lambda pair: pair[0] == pair[1]),
            "ai_names_a_different": rate(a, lambda row: row[1].decision.outcome == "known_recall"
                                         and row[1].decision.campno != row[0]),
            "ai_asks_for_detail": rate(a, lambda row: row[1].decision.outcome == "needs_info"),
            "rule_names_a_recall": rate(a, lambda row: shortcut(row[1]) is not None),
            "rule_names_the_owners": rate(rule_named, lambda pair: pair[0] == pair[1]),
            "rule_names_a_different": rate(a, lambda row: shortcut(row[1]) not in (None, row[0])),
        },
        "b": {
            "ai_says_known_recall": rate(b, lambda result: result.decision.outcome == "known_recall"),
            "ai_escalates": rate(b, lambda result: result.decision.outcome in ESCALATED),
        },
    }


def test_cases(name: str) -> list[dict]:
    return [case for case in json.loads((EVAL / f"set_{name}.json").read_text(encoding="utf-8"))["cases"]
            if case["split"] == "test"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Agreement with what owners believed (not accuracy).")
    parser.add_argument("--run", default=DEFAULT_RUN)
    run = parser.parse_args().run
    report = {"name": f"agreement-{run}", "set": "agreement", "split": "test", "mode": "code", "run": run,
              **agreement(stored_results(run), test_cases("a"), test_cases("b"))}
    (EVAL / "reports" / f"{report['name']}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for group in ("a", "b"):
        for key, row in report[group].items():
            print(f"{group}  {key:<24} {row['k']:>3}/{row['n']:<3} = {row['rate']:.0%}  {row['ci95']}")


if __name__ == "__main__":
    main()
