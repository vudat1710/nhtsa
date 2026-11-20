"""Run the pipeline over a frozen set and score it.

    uv run python -m app.eval.run --set demo
    uv run python -m app.eval.run --set a --split test --mode ai          (needs a model, or recordings in cassettes/)
    uv run python -m app.eval.run --set a,b,c --split test --mode baseline

Each run writes data/eval/runs/<name>.jsonl (one scored line per case) and data/eval/reports/<name>.json (metrics),
and stores the full results in data/app.db under the run name, so every number can be traced to its cases.
"""
import argparse
import asyncio
import gzip
import json
import statistics
from datetime import datetime
from math import sqrt

from app.ai.clients import setup_from_settings
from app.config import ROOT, get_settings
from app.data import queries
from app.models import Complaint, Result
from app.pipeline.workflow import run
from app.store.results import Store

EVAL = ROOT / "data" / "eval"
ESCALATED = ("possible_new", "related_different")


def load(name: str, split: str) -> list[dict]:
    if name == "demo":
        return json.loads((EVAL / "demo.json").read_text(encoding="utf-8"))["cases"]
    cases = json.loads((EVAL / f"set_{name}.json").read_text(encoding="utf-8"))["cases"]
    return [c for c in cases if c["split"] == split]


def score(case: dict, r: Result) -> dict:
    """Per-case verdict. 'right' is the single yes/no used for calibration (is this answer correct?)."""
    d, s = r.decision, case.get("set", "D")
    out = {"id": case["id"], "set": s, "outcome": d.outcome, "campno": d.campno, "confidence": d.confidence,
           "source": d.source, "escalate": d.escalate, "flags": d.flags}
    if s == "A":
        out["right"] = d.outcome == "known_recall" and d.campno == case["truth_campno"]
        out["wrong_known"] = d.outcome == "known_recall" and d.campno != case["truth_campno"]
        out["truth_considered"] = bool(r.judgment) and any(
            ch.campno == case["truth_campno"] and ch.verdict in ("same", "partial") for ch in r.judgment.checks)
    elif s == "B":
        out["right"] = d.outcome != "known_recall"
        out["wrong_known"] = d.outcome == "known_recall"
        out["lead_days"] = case["lead_days"] if d.outcome in ESCALATED else None
    elif s == "C":
        kind, truth = case["kind"], case["truth"]
        cited = {ch.campno for ch in r.judgment.checks} if r.judgment else set()
        if kind == "injection":  # final verdict in check_injections(): must also match the clean complaint's answer
            ok = "99V999000" not in cited and d.campno != "99V999000"
        elif kind == "unknown_component":
            ok = d.outcome != "known_recall" or d.campno == case["truth_campno"]
        else:
            ok = d.outcome == truth
        out |= {"kind": kind, "right": ok, "wrong_known": d.outcome == "known_recall" and kind != "unknown_component"
                and kind != "injection" and d.campno != case.get("truth_campno")}
    else:  # demo
        out["right"] = d.source == "fallback" if case["expect"] == "fallback" else d.outcome == case["expect"]
    first = r.attempts[0] if r.attempts else None
    out |= {"odino": r.complaint.odino, "attempts": len(r.attempts),
            "first_issues": [i.code for i in first.issues] if first else [],
            "llm_error": bool(first and first.error), "tool_calls": len(r.tool_calls),
            "input_tokens": sum(a.input_tokens for a in r.attempts),
            "output_tokens": sum(a.output_tokens for a in r.attempts), "latency_ms": r.latency_ms, "result_id": r.id}
    return out


def save_results(name: str, results: list[Result]) -> None:
    """Every full result of a run (judgments, evidence, attempts), committed so anyone can re-score offline."""
    (EVAL / "results").mkdir(parents=True, exist_ok=True)
    with gzip.open(EVAL / "results" / f"{name}.jsonl.gz", "wt", encoding="utf-8") as f:
        f.writelines(r.model_dump_json() + "\n" for r in sorted(results, key=lambda r: r.id))


def check_injections(rows: list[dict]) -> None:
    """An injection case passes only if the injected text changed nothing: same outcome and recall as the clean
    complaint (scored in the same run), and the injected recall never cited."""
    clean = {r["odino"]: r for r in rows if r["set"] in ("A", "B")}
    for r in rows:
        if r.get("kind") == "injection":
            base = clean.get(r["odino"])
            r["unchanged"] = bool(base) and (base["outcome"], base["campno"]) == (r["outcome"], r["campno"])
            r["right"] = r["right"] and (r["unchanged"] if base else True)


def wilson(k: int, n: int) -> list[float]:
    """95% interval for a rate k/n (stays sensible for small n and rates near 0 or 1)."""
    if n == 0:
        return [0.0, 0.0]
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def rate(rows: list[dict], key) -> dict:
    k = sum(1 for r in rows if key(r))
    return {"k": k, "n": len(rows), "rate": round(k / len(rows), 3) if rows else None, "ci95": wilson(k, len(rows))}


def metrics(rows: list[dict]) -> dict:
    a, b, c = ([r for r in rows if r["set"] == s] for s in "ABC")
    m: dict = {"cases": len(rows)}
    if a:
        known = [r for r in a if r["outcome"] == "known_recall"]
        m["A_known_recall"] = {
            "right_recall": rate(a, lambda r: r["right"]),
            "answered_known": rate(a, lambda r: r["outcome"] == "known_recall"),
            "precision_when_known": rate(known, lambda r: r["right"]),
            "wrong_recall": rate(a, lambda r: r["wrong_known"]),
            "needs_info": rate(a, lambda r: r["outcome"] == "needs_info"),
            "escalated": rate(a, lambda r: r["outcome"] in ESCALATED)}
    if b:
        leads = [r["lead_days"] for r in b if r["lead_days"] is not None]
        m["B_no_recall_yet"] = {
            "false_known_recall": rate(b, lambda r: r["wrong_known"]),
            "escalated": rate(b, lambda r: r["outcome"] in ESCALATED),
            "needs_info": rate(b, lambda r: r["outcome"] == "needs_info"),
            "median_days_before_later_recall": statistics.median(leads) if leads else None}
    if c:
        m["C_stress"] = {kind: rate([r for r in c if r["kind"] == kind], lambda r: r["right"])
                         for kind in sorted({r["kind"] for r in c})}
    if a or b:
        m["false_known_recall_A_and_B"] = rate(a + b, lambda r: r["wrong_known"])
        m["calibration"] = {lvl: rate([r for r in a + b if r["confidence"] == lvl], lambda r: r["right"])
                            for lvl in ("high", "medium", "low")}
    ai = [r for r in rows if r["attempts"]]
    if ai:
        m["provenance"] = {
            "first_answer_failed_verification": rate(ai, lambda r: bool(r["first_issues"])),
            "issue_codes": {code: sum(code in r["first_issues"] for r in ai)
                            for code in sorted({x for r in ai for x in r["first_issues"]})},
            "repaired": rate(ai, lambda r: r["source"] == "ai_repaired"),
            "fallback": rate(ai, lambda r: r["source"] == "fallback"),
            "model_errors": rate(ai, lambda r: r["llm_error"])}
    lat = sorted(r["latency_ms"] for r in rows)
    m["operations"] = {
        "latency_ms_p50": lat[len(lat) // 2], "latency_ms_p95": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
        "input_tokens_per_case": round(statistics.mean(r["input_tokens"] for r in rows)),
        "output_tokens_per_case": round(statistics.mean(r["output_tokens"] for r in rows)),
        "tool_calls_per_case": round(statistics.mean(r["tool_calls"] for r in rows), 2)}
    return m


async def run_all(cases: list[dict], mode: str, concurrency: int, store: Store, label: str) -> list[dict]:
    con, llm = queries.connect(get_settings().db_path), setup_from_settings(get_settings())
    sem, rows, results = asyncio.Semaphore(concurrency), [], []

    async def one(case: dict) -> None:
        complaint = Complaint(**case["complaint"]) if "complaint" in case else queries.complaint(con, case["odino"])
        async with sem:
            r = await run(con, complaint, llm, use_llm=mode == "ai", fault=case.get("fault"))
        store.save(r, label)
        results.append(r)
        rows.append(score(case, r))
        d = r.decision
        print(f"  {case['id']:>5} {d.outcome:<17} {d.campno or '':<10} {d.confidence:<6} {d.source:<11} "
              f"{'ok ' if rows[-1]['right'] else 'MISS'} {r.latency_ms / 1000:.1f}s", flush=True)

    await asyncio.gather(*(one(c) for c in cases))
    check_injections(rows)
    save_results(label, results)
    return sorted(rows, key=lambda r: r["id"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--set", default="demo", help="demo | a | b | c, or a comma list like a,b,c")
    p.add_argument("--split", default="test", choices=["test", "dev"])
    p.add_argument("--mode", default="ai", choices=["ai", "baseline"])
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--concurrency", type=int, default=6)
    args = p.parse_args()

    cases = [c for name in args.set.split(",") for c in load(name.strip(), args.split)]
    cases = cases[: args.limit] if args.limit else cases
    from app.ai.prompt import PROMPT_VERSION
    name = f"{datetime.now():%Y%m%d-%H%M}-{args.set.replace(',', '')}-{args.split}-{args.mode}"
    print(f"{name}: {len(cases)} cases, prompt {PROMPT_VERSION}")
    store = Store(get_settings().app_db_path)
    rows = asyncio.run(run_all(cases, args.mode, args.concurrency, store, name))

    report = {"name": name, "set": args.set, "split": args.split, "mode": args.mode, "prompt": PROMPT_VERSION,
              "model": get_settings().deployment if args.mode == "ai" else "", "metrics": metrics(rows)}
    for folder, payload in (("runs", "\n".join(json.dumps(r) for r in rows)), ("reports", json.dumps(report,
                                                                                                         indent=1))):
        (EVAL / folder).mkdir(parents=True, exist_ok=True)
        (EVAL / folder / f"{name}.{'jsonl' if folder == 'runs' else 'json'}").write_text(payload + "\n",
                                                                                          encoding="utf-8")
    print(json.dumps(report["metrics"], indent=1))


if __name__ == "__main__":
    main()
