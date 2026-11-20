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
    run_lines = (EVAL / "runs" / f"{run}.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in run_lines if line]
    set_a_cases = json.loads((EVAL / "set_a.json").read_text(encoding="utf-8"))["cases"]
    truth = {case["id"]: case for case in set_a_cases}
    ai_sources = ("ai_verified", "ai_repaired")
    set_a = []
    set_b = []
    for row in rows:
        if row["set"] == "A" and not row["right"] and row["source"] in ai_sources:
            disagreement = dict(row)
            disagreement["truth_campno"] = truth[row["id"]]["truth_campno"]
            set_a.append(disagreement)
    for row in rows:
        if row["set"] == "B" and row["wrong_known"] and row["source"] in ai_sources:
            disagreement = dict(row)
            disagreement["truth_campno"] = None
            set_b.append(disagreement)
    return set_a, set_b


def case_md(store: Store, row: dict, group: str, later: dict) -> tuple[list[str], dict]:
    """One disagreement as markdown lines for the reader, plus its entry (verdict still empty) for the .json file.
    Set A shows the recall the owner cited; set B shows the recall the AI matched and the later recall."""
    result = store.get(row["result_id"])
    complaint = result.complaint
    decision = result.decision
    judgment = result.judgment
    shown = row["truth_campno"] if group == "A" else decision.campno
    recall = result.evidence.recall(shown) if shown else None
    check = None
    if judgment and shown:
        check = next((x for x in judgment.checks if x.campno == shown), None)

    if group == "A":
        head = (f"**AI:** {decision.outcome} {decision.campno or ''} ({decision.confidence}) · "
                f"**owner cited:** {row['truth_campno']}")
    else:
        head = (f"**AI:** {decision.outcome} {decision.campno} ({decision.confidence}) · "
                f"**later recall on the owner's component:** {later.get('later_campno')} "
                f"(+{later.get('lead_days')} days)")
    if check:
        on_it = (f"{check.verdict}: {check.reason} · owner «{check.complaint_quote}» ~ "
                 f"recall «{check.recall_quote}»")
    else:
        on_it = "(not judged relevant)"
    if recall:
        recall_comps = ", ".join(recall.comps)
        recall_defect = recall.defect
    else:
        recall_comps = "-"
        recall_defect = "(not a candidate)"
    recall_label = "Cited" if group == "A" else "Matched"
    owner_comps = ", ".join(complaint.comps) or "-"
    ai_summary = judgment.summary if judgment else ""

    md = [f"\n## {row['id']} · {complaint.year} {complaint.make} {complaint.model} · complaint {complaint.odino} · "
          f"owner chose {owner_comps}",
          head,
          f"\n**Complaint (as the AI saw it):** {textwrap.shorten(result.intake.text, 1500)}",
          f"\n**{recall_label} recall {shown} ({recall_comps}):** {recall_defect}",
          f"\n**AI on it:** {on_it}",
          f"\n**AI summary:** {ai_summary}"]
    entry = {"id": row["id"], "odino": complaint.odino, "ai": decision.outcome, "ai_campno": decision.campno,
             "owner_campno": row["truth_campno"], "verdict": "", "note": ""}
    return md, entry


def export(run: str) -> None:
    store = Store(get_settings().app_db_path)
    dis_a, dis_b = disagreements(run)
    sample_a = random.Random(SEED).sample(dis_a, min(N, len(dis_a)))
    sample_a = sorted(sample_a, key=lambda row: row["id"])
    set_b_cases = json.loads((EVAL / "set_b.json").read_text(encoding="utf-8"))["cases"]
    later = {case["id"]: case for case in set_b_cases}
    md = [f"# Adjudication: {run}\n",
          f"**Set A:** {len(dis_a)} answers differ from the owner's cited recall; {len(sample_a)} sampled (seed "
          f"{SEED}). Verdict: ai_right | owner_right | unclear.\n",
          f"**Set B:** all {len(dis_b)} cases where the AI claimed a known recall although none existed on the owner's "
          "chosen component. Verdict: ai_right (an existing recall really fits) | owner_right (it does not) | "
          "unclear.\n"]

    cases_by_group = {"A": sample_a, "B": sorted(dis_b, key=lambda row: row["id"])}
    disagreement_counts = {"A": len(dis_a), "B": len(dis_b)}
    groups = {}
    for group, rows in cases_by_group.items():
        md.append(f"\n# Set {group}\n")
        entries = []
        for row in rows:
            lines, entry = case_md(store, row, group, later.get(row["id"], {}))
            md += lines
            entries.append(entry)
        groups[group] = {"disagreements": disagreement_counts[group], "cases": entries}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{run}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    path = OUT / f"{run}.json"
    if not path.exists():  # never overwrite a person's verdicts
        path.write_text(json.dumps({"run": run, "seed": SEED, "groups": groups}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT / (run + '.md')} and {path}: A {len(sample_a)} of {len(dis_a)}, B {len(dis_b)}")


def summary(run: str) -> dict:
    data = json.loads((OUT / f"{run}.json").read_text(encoding="utf-8"))
    out = {}
    for group, group_data in data["groups"].items():
        done = [case for case in group_data["cases"] if case["verdict"]]
        counts = {"disagreements": group_data["disagreements"], "adjudicated": len(done)}
        for verdict in ("ai_right", "owner_right", "unclear"):
            counts[verdict] = sum(1 for case in done if case["verdict"] == verdict)
        out[group] = counts
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if args.summary:
        print(json.dumps(summary(args.run), indent=1))
    else:
        export(args.run)


if __name__ == "__main__":
    main()
