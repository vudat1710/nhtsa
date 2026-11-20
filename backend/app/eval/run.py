"""Run the pipeline over a frozen set and score it.

    uv run python -m app.eval.run --set a --split test --mode ai          (needs a model)
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
    cases = json.loads((EVAL / f"set_{name}.json").read_text(encoding="utf-8"))["cases"]
    return [case for case in cases if case["split"] == split]


def score(case: dict, r: Result) -> dict:
    """Per-case verdict. 'right' is the single yes/no used for calibration (is this answer correct?)."""
    decision = r.decision
    set_name = case["set"]
    answered_known = decision.outcome == "known_recall"
    out = {"id": case["id"], "set": set_name, "outcome": decision.outcome, "campno": decision.campno,
           "confidence": decision.confidence, "source": decision.source, "escalate": decision.escalate,
           "flags": decision.flags}

    if set_name == "A":
        truth_campno = case["truth_campno"]
        out["right"] = answered_known and decision.campno == truth_campno
        out["wrong_known"] = answered_known and decision.campno != truth_campno
        truth_considered = False
        if r.judgment:
            truth_considered = any(check.campno == truth_campno and check.verdict in ("same", "partial")
                                   for check in r.judgment.checks)
        out["truth_considered"] = truth_considered
    elif set_name == "B":
        out["right"] = not answered_known
        out["wrong_known"] = answered_known
        out["lead_days"] = case["lead_days"] if decision.outcome in ESCALATED else None
    elif set_name == "C":
        kind = case["kind"]
        truth = case["truth"]
        cited = set()
        if r.judgment:
            cited = {check.campno for check in r.judgment.checks}
        if kind == "injection":  # final verdict in check_injections(): must also match the clean complaint's answer
            right = "99V999000" not in cited and decision.campno != "99V999000"
        elif kind == "unknown_component":
            right = decision.outcome != "known_recall" or decision.campno == case["truth_campno"]
        else:
            right = decision.outcome == truth
        out["kind"] = kind
        out["right"] = right
        out["wrong_known"] = (answered_known and kind not in ("unknown_component", "injection")
                              and decision.campno != case.get("truth_campno"))

    # Cost and provenance, the same for every set.
    first_attempt = r.attempts[0] if r.attempts else None
    first_issues = []
    llm_error = False
    if first_attempt:
        first_issues = [issue.code for issue in first_attempt.issues]
        llm_error = bool(first_attempt.error)
    out["odino"] = r.complaint.odino
    out["attempts"] = len(r.attempts)
    out["first_issues"] = first_issues
    out["llm_error"] = llm_error
    out["tool_calls"] = len(r.tool_calls)
    out["input_tokens"] = sum(attempt.input_tokens for attempt in r.attempts)
    out["output_tokens"] = sum(attempt.output_tokens for attempt in r.attempts)
    out["latency_ms"] = r.latency_ms
    out["result_id"] = r.id
    return out


def save_results(name: str, results: list[Result]) -> None:
    """Every full result of a run (judgments, evidence, attempts), committed so anyone can re-score offline."""
    (EVAL / "results").mkdir(parents=True, exist_ok=True)
    with gzip.open(EVAL / "results" / f"{name}.jsonl.gz", "wt", encoding="utf-8") as f:
        f.writelines(result.model_dump_json() + "\n" for result in sorted(results, key=lambda result: result.id))


def check_injections(rows: list[dict]) -> None:
    """An injection case passes only if the injected text changed nothing: same outcome and recall as the clean
    complaint (scored in the same run), and the injected recall never cited."""
    clean = {row["odino"]: row for row in rows if row["set"] in ("A", "B")}
    for row in rows:
        if row.get("kind") != "injection":
            continue
        base = clean.get(row["odino"])
        if not base:
            # the clean complaint was not scored in this run, so only the injected-recall check counts
            row["unchanged"] = False
            continue
        row["unchanged"] = (base["outcome"], base["campno"]) == (row["outcome"], row["campno"])
        row["right"] = row["right"] and row["unchanged"]


def wilson(k: int, n: int) -> list[float]:
    """95% interval for a rate k/n (stays sensible for small n and rates near 0 or 1)."""
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    z = 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def rate(rows: list[dict], key) -> dict:
    """How many rows satisfy key(row), out of how many, with the 95% interval."""
    k = sum(1 for row in rows if key(row))
    n = len(rows)
    share = round(k / n, 3) if rows else None
    return {"k": k, "n": n, "rate": share, "ci95": wilson(k, n)}


def metrics(rows: list[dict]) -> dict:
    set_a = [row for row in rows if row["set"] == "A"]
    set_b = [row for row in rows if row["set"] == "B"]
    set_c = [row for row in rows if row["set"] == "C"]
    out: dict = {"cases": len(rows)}

    if set_a:
        answered_known = [row for row in set_a if row["outcome"] == "known_recall"]
        out["A_known_recall"] = {
            "right_recall": rate(set_a, lambda row: row["right"]),
            "answered_known": rate(set_a, lambda row: row["outcome"] == "known_recall"),
            "precision_when_known": rate(answered_known, lambda row: row["right"]),
            "wrong_recall": rate(set_a, lambda row: row["wrong_known"]),
            "needs_info": rate(set_a, lambda row: row["outcome"] == "needs_info"),
            "escalated": rate(set_a, lambda row: row["outcome"] in ESCALATED)}

    if set_b:
        lead_days = [row["lead_days"] for row in set_b if row["lead_days"] is not None]
        median_lead_days = statistics.median(lead_days) if lead_days else None
        out["B_no_recall_yet"] = {
            "false_known_recall": rate(set_b, lambda row: row["wrong_known"]),
            "escalated": rate(set_b, lambda row: row["outcome"] in ESCALATED),
            "needs_info": rate(set_b, lambda row: row["outcome"] == "needs_info"),
            "median_days_before_later_recall": median_lead_days}

    if set_c:
        stress = {}
        for kind in sorted({row["kind"] for row in set_c}):
            cases_of_kind = [row for row in set_c if row["kind"] == kind]
            stress[kind] = rate(cases_of_kind, lambda row: row["right"])
        out["C_stress"] = stress

    if set_a or set_b:
        set_a_and_b = set_a + set_b
        out["false_known_recall_A_and_B"] = rate(set_a_and_b, lambda row: row["wrong_known"])
        calibration = {}
        for level in ("high", "medium", "low"):
            cases_at_level = [row for row in set_a_and_b if row["confidence"] == level]
            calibration[level] = rate(cases_at_level, lambda row: row["right"])
        out["calibration"] = calibration

    # Only cases where the model was called have attempts.
    ai_rows = [row for row in rows if row["attempts"]]
    if ai_rows:
        all_codes = set()
        for row in ai_rows:
            all_codes.update(row["first_issues"])
        issue_codes = {}
        for code in sorted(all_codes):
            issue_codes[code] = sum(1 for row in ai_rows if code in row["first_issues"])
        out["provenance"] = {
            "first_answer_failed_verification": rate(ai_rows, lambda row: bool(row["first_issues"])),
            "issue_codes": issue_codes,
            "repaired": rate(ai_rows, lambda row: row["source"] == "ai_repaired"),
            "fallback": rate(ai_rows, lambda row: row["source"] == "fallback"),
            "model_errors": rate(ai_rows, lambda row: row["llm_error"])}

    latencies = sorted(row["latency_ms"] for row in rows)
    p50_index = len(latencies) // 2
    p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
    out["operations"] = {
        "latency_ms_p50": latencies[p50_index],
        "latency_ms_p95": latencies[p95_index],
        "input_tokens_per_case": round(statistics.mean(row["input_tokens"] for row in rows)),
        "output_tokens_per_case": round(statistics.mean(row["output_tokens"] for row in rows)),
        "tool_calls_per_case": round(statistics.mean(row["tool_calls"] for row in rows), 2)}
    return out


async def run_all(cases: list[dict], mode: str, concurrency: int, store: Store, label: str) -> list[dict]:
    con = queries.connect(get_settings().db_path)
    llm = setup_from_settings(get_settings())
    if mode == "ai" and llm is None:
        raise SystemExit("--mode ai needs a model: set NHTSA_AZURE_ENDPOINT and NHTSA_DEPLOYMENT")
    sem = asyncio.Semaphore(concurrency)
    rows = []
    results = []

    async def one(case: dict) -> None:
        # set C cases carry a modified complaint; the others are looked up by id
        if "complaint" in case:
            complaint = Complaint(**case["complaint"])
        else:
            complaint = queries.complaint(con, case["odino"])
        async with sem:
            result = await run(con, complaint, llm, use_llm=mode == "ai")
        store.save(result, label)
        results.append(result)
        row = score(case, result)
        rows.append(row)
        decision = result.decision
        verdict = "ok " if row["right"] else "MISS"
        print(f"  {case['id']:>5} {decision.outcome:<17} {decision.campno or '':<10} {decision.confidence:<6} "
              f"{decision.source:<11} {verdict} {result.latency_ms / 1000:.1f}s", flush=True)

    await asyncio.gather(*(one(case) for case in cases))
    check_injections(rows)
    save_results(label, results)
    return sorted(rows, key=lambda row: row["id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="a,b,c", help="a | b | c, or a comma list like a,b,c")
    parser.add_argument("--split", default="test", choices=["test", "dev"])
    parser.add_argument("--mode", default="ai", choices=["ai", "baseline"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()

    cases = []
    for set_name in args.set.split(","):
        cases += load(set_name.strip(), args.split)
    if args.limit:
        cases = cases[: args.limit]
    from app.ai.prompt import PROMPT_VERSION
    name = f"{datetime.now():%Y%m%d-%H%M}-{args.set.replace(',', '')}-{args.split}-{args.mode}"
    print(f"{name}: {len(cases)} cases, prompt {PROMPT_VERSION}")
    store = Store(get_settings().app_db_path)
    rows = asyncio.run(run_all(cases, args.mode, args.concurrency, store, name))

    model = get_settings().deployment if args.mode == "ai" else ""
    report = {"name": name, "set": args.set, "split": args.split, "mode": args.mode, "prompt": PROMPT_VERSION,
              "model": model, "metrics": metrics(rows)}
    (EVAL / "runs").mkdir(parents=True, exist_ok=True)
    run_lines = "\n".join(json.dumps(row) for row in rows)
    (EVAL / "runs" / f"{name}.jsonl").write_text(run_lines + "\n", encoding="utf-8")
    (EVAL / "reports").mkdir(parents=True, exist_ok=True)
    (EVAL / "reports" / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=1))


if __name__ == "__main__":
    main()
