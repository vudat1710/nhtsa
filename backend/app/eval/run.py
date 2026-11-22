"""Run the pipeline over the frozen test sets and measure what can be measured objectively.

    uv run python -m app.eval.run                          (needs a model: every case of sets a, b, c, test split)
    uv run python -m app.eval.run --report <run name>      (rebuild a stored run's report, no model)

Each run stores every full result in data/eval/results/<name>.jsonl.gz (evidence, judgments, attempts, tool calls,
decision) and a report in data/eval/reports/<name>.json: how many first answers failed a check, repairs, fallbacks,
model errors, time and tokens. The sets' labels are not scored as accuracy (there is no ground truth for which recall is
right; see docs/DATA_CARD.md): agreement with the owners' own recall is in agreement.py, and the workflow's rules are
checked on the stored results by trajectory.py.
"""
import argparse
import asyncio
import gzip
import json
import statistics
from collections import Counter
from datetime import datetime
from math import sqrt

from app.ai.clients import setup_from_settings
from app.config import ROOT, get_settings
from app.data import queries
from app.models import Complaint, Result
from app.pipeline.workflow import run

EVAL = ROOT / "data" / "eval"
ESCALATED = ("possible_new", "related_different")


def load(name: str, split: str) -> list[dict]:
    cases = json.loads((EVAL / f"set_{name}.json").read_text(encoding="utf-8"))["cases"]
    return [case for case in cases if case["split"] == split]


def wilson(k: int, n: int) -> list[float]:
    """95% interval for a rate k/n (stays sensible for small n and rates near 0 or 1)."""
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    z = 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def rate(rows: list, key) -> dict:
    """How many rows satisfy key(row), out of how many, with the 95% interval."""
    k = sum(1 for row in rows if key(row))
    n = len(rows)
    share = round(k / n, 3) if rows else None
    return {"k": k, "n": n, "rate": share, "ci95": wilson(k, n)}


def metrics(results: list[Result]) -> dict:
    """Facts about the runs themselves: no label is involved."""
    ai_runs = [result for result in results if result.attempts]  # unknown-year cases never call the model
    latencies = sorted(result.latency_ms for result in results)
    return {
        "cases": len(results),
        "provenance": {
            "first_answer_failed_verification": rate(ai_runs, lambda r: bool(r.attempts[0].issues)),
            "repaired": rate(ai_runs, lambda r: r.decision.source == "ai_repaired"),
            "fallback": rate(ai_runs, lambda r: r.decision.source == "fallback"),
            "model_errors": rate(ai_runs, lambda r: bool(r.attempts[0].error)),
            # "content_filter: …", "error: Error code: 429 …": the kind is the label before the first colon
            "model_error_kinds": dict(Counter(r.attempts[0].error.split(":")[0] for r in ai_runs
                                              if r.attempts[0].error)),
        },
        "operations": {
            "latency_ms_p50": latencies[len(latencies) // 2],
            "latency_ms_p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
            "input_tokens_per_case": round(statistics.mean(sum(a.input_tokens for a in r.attempts) for r in results)),
            "output_tokens_per_case": round(statistics.mean(sum(a.output_tokens for a in r.attempts) for r in results)),
            "tool_calls_per_case": round(statistics.mean(len(r.tool_calls) for r in results), 2),
        },
    }


def stored_results(name: str) -> list[Result]:
    with gzip.open(EVAL / "results" / f"{name}.jsonl.gz", "rt", encoding="utf-8") as lines:
        return [Result.model_validate_json(line) for line in lines if line.strip()]


def write_report(name: str, sets: str, prompt: str, model: str, results: list[Result]) -> dict:
    report = {"name": name, "set": sets, "split": "test", "mode": "ai", "prompt": prompt, "model": model,
              "metrics": metrics(results)}
    (EVAL / "reports").mkdir(parents=True, exist_ok=True)
    (EVAL / "reports" / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return report


async def run_all(cases: list[dict], concurrency: int) -> list[Result]:
    con = queries.connect(get_settings().db_path)
    llm = setup_from_settings(get_settings())
    if llm is None:
        raise SystemExit("needs a model: set NHTSA_AZURE_ENDPOINT and NHTSA_DEPLOYMENT")
    sem = asyncio.Semaphore(concurrency)
    results = []

    async def one(case: dict) -> None:
        # set C cases carry a modified complaint; the others are looked up by id
        complaint = Complaint(**case["complaint"]) if "complaint" in case else queries.complaint(con, case["odino"])
        async with sem:
            result = await run(con, complaint, llm)
        results.append(result)
        decision = result.decision
        print(f"  {case['id']:>5} {decision.outcome:<17} {decision.campno or '':<10} {decision.confidence:<6} "
              f"{decision.source:<11} {result.latency_ms / 1000:.1f}s", flush=True)

    await asyncio.gather(*(one(case) for case in cases))
    return sorted(results, key=lambda result: result.id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", metavar="RUN", help="rebuild the report of a stored run (no model)")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    from app.ai.prompt import PROMPT_VERSION

    if args.report:
        old = json.loads((EVAL / "reports" / f"{args.report}.json").read_text(encoding="utf-8"))
        report = write_report(args.report, old["set"], old["prompt"], old["model"], stored_results(args.report))
    else:
        cases = [case for name in "abc" for case in load(name, "test")]
        name = f"{datetime.now():%Y%m%d-%H%M}-abc-test-ai"
        print(f"{name}: {len(cases)} cases, prompt {PROMPT_VERSION}")
        results = asyncio.run(run_all(cases, args.concurrency))
        (EVAL / "results").mkdir(parents=True, exist_ok=True)
        with gzip.open(EVAL / "results" / f"{name}.jsonl.gz", "wt", encoding="utf-8") as lines:
            lines.writelines(result.model_dump_json() + "\n" for result in results)
        report = write_report(name, "a,b,c", PROMPT_VERSION, get_settings().deployment, results)
    print(json.dumps(report["metrics"], indent=1))


if __name__ == "__main__":
    main()
