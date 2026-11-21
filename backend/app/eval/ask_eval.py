"""Evaluate the follow-up assistant on questions about the demo tickets (data/eval/ask_questions.json).

    uv run python -m app.eval.ask_eval                       (needs a model)
    uv run python -m app.eval.ask_eval --report <run name>   (rebuild a stored run's report, no model)

Only what is objective is measured: every quote in an answer is found word for word in its source; the assistant says
"not in the records" for what the data lacks (repair history, crash-event data, VIN); it declines requests that are
not about the case (a provider safety block counts as declining); and it suggests a re-check when the analyst gives a
new fact the decision depends on. Writes data/eval/results/<name>.jsonl (every answer) and
data/eval/reports/<name>.json.
"""
import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime

from app.api import deps
from app.api.workspace import related_for
from app.ask.service import ask
from app.eval.run import EVAL, rate

QUESTIONS = EVAL / "ask_questions.json"


def row_for(question: dict, turn, seconds: float) -> dict:
    answer = turn.answer
    return {"id": question["id"], "odino": question["odino"], "question": question["q"], "blocked": turn.blocked,
            "verified": turn.verified, "scope": answer.scope if answer else None,
            "recheck": answer.recheck if answer else None, "citations": len(answer.citations) if answer else 0,
            "searches": len(turn.searches), "issues": turn.issues, "error": turn.error,
            "answer": answer.answer if answer else None, "seconds": round(seconds, 1)}


def metrics(rows: list[dict], questions: list[dict]) -> dict:
    expect = {question["id"]: question.get("expect") for question in questions}
    def expecting(kind: str) -> list[dict]:
        return [row for row in rows if expect.get(row["id"]) == kind]
    return {
        "verified_when_not_blocked": rate([row for row in rows if not row["blocked"]], lambda row: row["verified"]),
        "says_not_in_records_when_the_data_lacks_it": rate(expecting("not_in_records"),
                                                           lambda row: row["scope"] == "not_in_records"),
        "declines_requests_not_about_the_case": rate(expecting("declines"),
                                                     lambda row: row["blocked"] or row["scope"] == "out_of_scope"),
        "suggests_recheck_when_a_fact_changes": rate(expecting("recheck"), lambda row: bool(row["recheck"])),
        "blocked_by_provider": sum(1 for row in rows if row["blocked"]),
        "seconds_p50": statistics.median(row["seconds"] for row in rows),
    }


def write_report(name: str, model: str, rows: list[dict], questions: list[dict]) -> dict:
    report = {"name": name, "set": "ask", "split": "test", "mode": "ai", "model": model,
              "metrics": metrics(rows, questions)}
    (EVAL / "reports" / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return report


async def run_questions(questions: list[dict]) -> tuple[list[dict], str]:
    latest = deps.store().latest("queue")
    llm = deps.llm()
    if llm is None:
        raise SystemExit("needs a model: set NHTSA_AZURE_ENDPOINT and NHTSA_DEPLOYMENT")
    rows = []
    for question in questions:
        result = latest[question["odino"]]
        started = time.time()
        turn = await ask(deps.con(), llm, result, [], question["q"], related_for(result))
        rows.append(row_for(question, turn, time.time() - started))
        row = rows[-1]
        print(f"  {question['id']} {row['scope']} {'blocked' if row['blocked'] else ''} "
              f"{'verified' if row['verified'] else 'NOT VERIFIED'} {row['seconds']}s | {(row['answer'] or '')[:90]}")
    return rows, llm.model_name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", metavar="RUN", help="rebuild the report of a stored run (no model)")
    args = parser.parse_args()
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.report:
        lines = (EVAL / "results" / f"{args.report}.jsonl").read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines if line.strip()]
        old = json.loads((EVAL / "reports" / f"{args.report}.json").read_text(encoding="utf-8"))
        report = write_report(args.report, old["model"], rows, questions)
    else:
        rows, model = asyncio.run(run_questions(questions))
        name = f"ask-{datetime.now():%Y%m%d-%H%M}"
        (EVAL / "results").mkdir(parents=True, exist_ok=True)
        (EVAL / "results" / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
        report = write_report(name, model, rows, questions)
    print(json.dumps(report["metrics"], indent=1))


if __name__ == "__main__":
    main()
