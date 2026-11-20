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
    """Set A: the AI's answer differs from the owner's cited recall. Set B: the AI claimed a known recall although
    none existed on the owner's chosen component (it may have found one filed under another component)."""
    rows = [json.loads(x) for x in (EVAL / "runs" / f"{run}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    truth = {c["id"]: c for c in json.loads((EVAL / "set_a.json").read_text(encoding="utf-8"))["cases"]}
    ai = ("ai_verified", "ai_repaired")
    a = [r | {"truth_campno": truth[r["id"]]["truth_campno"]} for r in rows
         if r["set"] == "A" and not r["right"] and r["source"] in ai]
    b = [r | {"truth_campno": None} for r in rows if r["set"] == "B" and r["wrong_known"] and r["source"] in ai]
    return a, b


def case_md(store: Store, r: dict, group: str, later: dict) -> tuple[list[str], dict]:
    res = store.get(r["result_id"])
    c, d = res.complaint, res.decision
    shown = r["truth_campno"] if group == "A" else d.campno
    rec = res.evidence.recall(shown) if shown else None
    check = next((x for x in res.judgment.checks if x.campno == shown), None) if res.judgment and shown else None
    head = (f"**AI:** {d.outcome} {d.campno or ''} ({d.confidence}) · **owner cited:** {r['truth_campno']}"
            if group == "A" else f"**AI:** {d.outcome} {d.campno} ({d.confidence}) · **later recall on the owner's "
                                 f"component:** {later.get('later_campno')} (+{later.get('lead_days')} days)")
    on_it = (f"{check.verdict}: {check.reason} · owner «{check.complaint_quote}» ~ recall «{check.recall_quote}»"
             if check else "(not judged relevant)")
    md = [f"\n## {r['id']} · {c.year} {c.make} {c.model} · complaint {c.odino} · owner chose "
          f"{', '.join(c.comps) or '-'}", head,
          f"\n**Complaint (as the AI saw it):** {textwrap.shorten(res.intake.text, 1500)}",
          f"\n**{'Cited' if group == 'A' else 'Matched'} recall {shown} ({', '.join(rec.comps) if rec else '-'}):** "
          f"{rec.defect if rec else '(not a candidate)'}",
          f"\n**AI on it:** {on_it}",
          f"\n**AI summary:** {res.judgment.summary if res.judgment else ''}"]
    entry = {"id": r["id"], "odino": c.odino, "ai": d.outcome, "ai_campno": d.campno,
             "owner_campno": r["truth_campno"], "verdict": "", "note": ""}
    return md, entry


def export(run: str) -> None:
    store = Store(get_settings().app_db_path)
    dis_a, dis_b = disagreements(run)
    sample_a = sorted(random.Random(SEED).sample(dis_a, min(N, len(dis_a))), key=lambda r: r["id"])
    later = {c["id"]: c for c in json.loads((EVAL / "set_b.json").read_text(encoding="utf-8"))["cases"]}
    md = [f"# Adjudication: {run}\n",
          f"**Set A:** {len(dis_a)} answers differ from the owner's cited recall; {len(sample_a)} sampled (seed "
          f"{SEED}). Verdict: ai_right | owner_right | unclear.\n",
          f"**Set B:** all {len(dis_b)} cases where the AI claimed a known recall although none existed on the owner's "
          "chosen component. Verdict: ai_right (an existing recall really fits) | owner_right (it does not) | "
          "unclear.\n"]
    groups = {}
    for group, rows in (("A", sample_a), ("B", sorted(dis_b, key=lambda r: r["id"]))):
        md.append(f"\n# Set {group}\n")
        entries = []
        for r in rows:
            lines, entry = case_md(store, r, group, later.get(r["id"], {}))
            md += lines
            entries.append(entry)
        groups[group] = {"disagreements": len(dis_a if group == "A" else dis_b), "cases": entries}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{run}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    path = OUT / f"{run}.json"
    if not path.exists():  # never overwrite a person's verdicts
        path.write_text(json.dumps({"run": run, "seed": SEED, "groups": groups}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT / (run + '.md')} and {path}: A {len(sample_a)} of {len(dis_a)}, B {len(dis_b)}")


def summary(run: str) -> dict:
    data = json.loads((OUT / f"{run}.json").read_text(encoding="utf-8"))
    out = {}
    for group, g in data["groups"].items():
        done = [c for c in g["cases"] if c["verdict"]]
        out[group] = {"disagreements": g["disagreements"], "adjudicated": len(done),
                      **{v: sum(c["verdict"] == v for c in done) for v in ("ai_right", "owner_right", "unclear")}}
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--summary", action="store_true")
    a = p.parse_args()
    print(json.dumps(summary(a.run), indent=1)) if a.summary else export(a.run)


if __name__ == "__main__":
    main()
