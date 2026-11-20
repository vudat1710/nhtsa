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
    with gzip.open(EVAL / "results" / f"{run}.jsonl.gz", "rt", encoding="utf-8") as f:
        return {r.id: r for r in (Result.model_validate_json(line) for line in f if line.strip())}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--note", default="", help="what changed in the rules, recorded in the report")
    a = p.parse_args()
    results = stored_results(a.run)
    report = json.loads((EVAL / "reports" / f"{a.run}.json").read_text(encoding="utf-8"))
    cases = [c for name in report["set"].split(",") for c in load(name.strip(), report["split"])]
    old_rows = [json.loads(x) for x in (EVAL / "runs" / f"{a.run}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    rows, changed = [], 0
    for old in old_rows:
        r = results[old["result_id"]]
        case = next(c for c in cases if c["id"] == old["id"])
        new_decision = decide(r.complaint, r.intake, r.evidence, r.judgment, r.decision.source)
        changed += new_decision.outcome != r.decision.outcome or new_decision.campno != r.decision.campno
        rows.append(score(case, r.model_copy(update={"decision": new_decision})))
    check_injections(rows)
    name = f"{a.run}-rescored"
    report |= {"name": name, "rescored_from": a.run, "rescore_note": a.note, "decisions_changed": changed,
               "metrics": metrics(rows)}
    (EVAL / "runs" / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (EVAL / "reports" / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{name}: {changed} decisions changed")


if __name__ == "__main__":
    main()
