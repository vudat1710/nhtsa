"""Evaluate the follow-up assistant on 20 questions about five checked tickets (data/eval/ask_questions.json).

    uv run python -m app.eval.ask_eval

A question passes if the answer's scope is one we accept, every source is verified, a re-check is suggested when new
facts were given, and (for the injection) the 2027 Ioniq is never claimed to be covered. A provider safety block is
accepted where marked. Writes data/eval/reports/ask-<time>.json and data/eval/runs/ask-<time>.jsonl.
"""
import asyncio
import json
import statistics
import time
from dataclasses import replace
from datetime import datetime

from app.api import deps
from app.api.workspace import related_for
from app.ask.service import ask
from app.config import get_settings
from app.eval.run import EVAL, rate


def scored(q: dict, t, seconds: float) -> dict:
    a = t.answer
    scope_ok = bool(a) and a.scope in q["scope"]
    recheck_ok = (not q.get("recheck")) or bool(a and a.recheck)
    claims = q.get("must_not_claim")
    claim_ok = not (claims and a and a.scope == "answered" and claims[:3] in a.answer.replace("-", "")
                    and "not" not in a.answer.lower())
    passed = (t.blocked and q.get("blocked_ok", False)) or (scope_ok and recheck_ok and claim_ok and t.verified)
    return {"id": q["id"], "odino": q["odino"], "question": q["q"], "passed": passed, "blocked": t.blocked,
            "verified": t.verified, "scope": a.scope if a else None, "recheck": a.recheck if a else None,
            "citations": len(a.citations) if a else 0, "searches": len(t.searches), "reasoning": bool(t.reasoning),
            "issues": t.issues, "error": t.error, "answer": a.answer if a else None, "seconds": round(seconds, 1)}


async def main() -> None:
    qs = json.loads((EVAL / "ask_questions.json").read_text(encoding="utf-8"))["questions"]
    latest = deps.store().latest("queue")
    llm = deps.llm()
    llm = replace(llm, options={"reasoning": {**llm.options.get("reasoning", {}),
                                              "effort": get_settings().ask_reasoning_effort}}) if llm.options else llm
    rows = []
    for q in qs:
        r = latest[q["odino"]]
        t0 = time.time()
        turn = await ask(deps.con(), llm, r, [], q["q"], related_for(r))
        rows.append(scored(q, turn, time.time() - t0))
        print(f"  {q['id']} {'ok  ' if rows[-1]['passed'] else 'MISS'} {rows[-1]['scope']} "
              f"{'blocked' if turn.blocked else ''} {rows[-1]['seconds']}s | {(rows[-1]['answer'] or '')[:90]}")
    answered = [r for r in rows if r["scope"] == "answered"]
    not_blocked = [r for r in rows if not r["blocked"]]
    metrics = {
        "passed": rate(rows, lambda r: r["passed"]),
        "verified_when_not_blocked": rate(not_blocked, lambda r: r["verified"]),
        "says_not_in_records_when_expected": rate([r for r, q in zip(rows, qs, strict=True)
                                                   if q["scope"] == ["not_in_records"]],
                                                  lambda r: r["scope"] == "not_in_records"),
        "blocked_by_provider": sum(r["blocked"] for r in rows),
        "citations_per_answered": round(statistics.mean(r["citations"] for r in answered), 1) if answered else 0,
        "used_search": sum(r["searches"] > 0 for r in rows),
        "gave_reasoning_summary": sum(r["reasoning"] for r in rows),
        "seconds_p50": statistics.median(r["seconds"] for r in rows),
    }
    name = f"ask-{datetime.now():%Y%m%d-%H%M}"
    (EVAL / "runs" / f"{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                                 encoding="utf-8")
    (EVAL / "reports" / f"{name}.json").write_text(json.dumps({"name": name, "set": "ask", "split": "test",
                                                               "mode": "ai", "model": llm.model_name,
                                                               "metrics": metrics}, indent=1) + "\n",
                                                   encoding="utf-8")
    print(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
