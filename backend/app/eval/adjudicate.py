"""Who was right when the AI disagreed with the owner? (set A labels are the owner's belief, not ground truth)

    uv run python -m app.eval.adjudicate --run <run name>            writes data/eval/adjudication/<run>.md + .json
    (a person fills each case's "verdict": ai_right | owner_right | unclear, with a note, in the .json)
    uv run python -m app.eval.adjudicate --run <run name> --summary  prints the shares

The sample is fixed (seed) and drawn from every disagreement, so the share generalizes to all of them.
"""
import argparse
import json
import random
import textwrap

from app.config import get_settings
from app.eval.run import EVAL
from app.store.results import Store

N, SEED = 30, 11
OUT = EVAL / "adjudication"


def disagreements(run: str) -> list[dict]:
    rows = [json.loads(x) for x in (EVAL / "runs" / f"{run}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    truth = {c["id"]: c for c in json.loads((EVAL / "set_a.json").read_text(encoding="utf-8"))["cases"]}
    return [r | {"truth_campno": truth[r["id"]]["truth_campno"]} for r in rows
            if r["set"] == "A" and not r["right"] and r["source"] in ("ai_verified", "ai_repaired")]


def export(run: str) -> None:
    store, dis = Store(get_settings().app_db_path), disagreements(run)
    sample = sorted(random.Random(SEED).sample(dis, min(N, len(dis))), key=lambda r: r["id"])
    md = [f"# Adjudication: {run}\n", f"{len(dis)} disagreements with the owner's cited recall; {len(sample)} sampled "
          f"(seed {SEED}). For each: is the AI's answer right, or the owner's recall?\n"]
    cases = []
    for r in sample:
        res = store.get(r["result_id"])
        rec = res.evidence.recall(r["truth_campno"])
        check = next((c for c in res.judgment.checks if c.campno == r["truth_campno"]), None) if res.judgment else None
        on_cited = f"{check.verdict}: {check.reason}" if check else "(not judged relevant)"
        md += [f"\n## {r['id']} · {res.complaint.year} {res.complaint.make} {res.complaint.model} · complaint "
               f"{res.complaint.odino}",
               f"**AI:** {res.decision.outcome} {res.decision.campno or ''} ({res.decision.confidence}) · "
               f"**owner cited:** {r['truth_campno']}",
               f"\n**Complaint (as the AI saw it):** {textwrap.shorten(res.intake.text, 1500)}",
               f"\n**Cited recall {r['truth_campno']}:** {rec.defect if rec else '(not a candidate)'}",
               f"\n**AI on the cited recall:** {on_cited}",
               f"\n**AI summary:** {res.judgment.summary if res.judgment else ''}"]
        cases.append({"id": r["id"], "odino": res.complaint.odino, "ai": res.decision.outcome,
                      "ai_campno": res.decision.campno, "owner_campno": r["truth_campno"],
                      "verdict": "", "note": ""})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{run}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    path = OUT / f"{run}.json"
    if not path.exists():  # never overwrite a person's verdicts
        path.write_text(json.dumps({"run": run, "disagreements": len(dis), "seed": SEED, "cases": cases}, indent=1)
                        + "\n", encoding="utf-8")
    print(f"wrote {OUT / (run + '.md')} and {path} ({len(sample)} of {len(dis)} disagreements)")


def summary(run: str) -> dict:
    data = json.loads((OUT / f"{run}.json").read_text(encoding="utf-8"))
    done = [c for c in data["cases"] if c["verdict"]]
    counts = {v: sum(c["verdict"] == v for c in done) for v in ("ai_right", "owner_right", "unclear")}
    return {"run": run, "disagreements": data["disagreements"], "adjudicated": len(done), **counts}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--summary", action="store_true")
    a = p.parse_args()
    print(json.dumps(summary(a.run), indent=1)) if a.summary else export(a.run)


if __name__ == "__main__":
    main()
