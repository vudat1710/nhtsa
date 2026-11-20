"""Re-apply the current rules to a stored evaluation run, without calling the model again.

The AI's judgments are stored with every run; the rules (pipeline/decide.py) are pure code. So when a rule changes,
the same AI answers can be re-decided and re-scored, and the report says so:

    uv run python -m app.eval.rescore --run 20261120-1142-abc-test-ai
"""
import argparse
import gzip
import json

from app.eval.run import EVAL, check_injections, load, metrics, score
from app.models import Result
from app.pipeline.decide import decide


def stored_results(run: str) -> dict[str, Result]:
    """Every result of a run, as committed in data/eval/results/<run>.jsonl.gz (no database or model needed)."""
    results = {}
    with gzip.open(EVAL / "results" / f"{run}.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                result = Result.model_validate_json(line)
                results[result.id] = result
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--note", default="", help="what changed in the rules, recorded in the report")
    args = parser.parse_args()
    results = stored_results(args.run)
    report = json.loads((EVAL / "reports" / f"{args.run}.json").read_text(encoding="utf-8"))
    cases = []
    for set_name in report["set"].split(","):
        cases += load(set_name.strip(), report["split"])
    run_lines = (EVAL / "runs" / f"{args.run}.jsonl").read_text(encoding="utf-8").splitlines()
    old_rows = [json.loads(line) for line in run_lines if line]

    rows = []
    changed = 0
    for old in old_rows:
        result = results[old["result_id"]]
        case = next(case for case in cases if case["id"] == old["id"])
        new_decision = decide(result.complaint, result.intake, result.evidence, result.judgment,
                              result.decision.source)
        if new_decision.outcome != result.decision.outcome or new_decision.campno != result.decision.campno:
            changed += 1
        redecided = result.model_copy(update={"decision": new_decision})
        rows.append(score(case, redecided))
    check_injections(rows)

    name = f"{args.run}-rescored"
    report["name"] = name
    report["rescored_from"] = args.run
    report["rescore_note"] = args.note
    report["decisions_changed"] = changed
    report["metrics"] = metrics(rows)
    (EVAL / "runs" / f"{name}.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (EVAL / "reports" / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: {changed} decisions changed")


if __name__ == "__main__":
    main()
