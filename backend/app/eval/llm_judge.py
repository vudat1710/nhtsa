"""LLM-as-judge: an approximate accuracy check, NOT human labels.

The same model the product uses (gpt-6.1-sol, the only deployment) labels each complaint of sets A and B blind: it gets
the masked complaint and the candidate recalls the system saw, but not the system's answer, its quotes, or the
owner's recall number. It names the recall that describes the same failure, "none", or "unclear". Its standard is
stricter than the product's (the same failure, not only the same symptoms), so it says "none" or "unclear" more
often. The system's stored answers are then compared with those labels. Being the same model, the judge can share the
system's blind spots, so this is a second opinion, not ground truth; the plan for real accuracy is still two analysts
labelling blind.

    uv run python -m app.eval.llm_judge                  (needs the model: labels every case, ~10 minutes)
    uv run python -m app.eval.llm_judge --report         (rebuild the report from the stored labels, no model)

Writes data/eval/labels/llm-judge-<run>.jsonl.gz (every label and its reason) and
data/eval/reports/llm-judge-<run>.json.
"""
import argparse
import asyncio
import gzip
import json
from collections import Counter

from agent_framework import Message
from pydantic import BaseModel, Field

from app.ai.clients import LlmSetup, setup_from_settings, strict_format
from app.config import get_settings
from app.eval.agreement import test_cases
from app.eval.run import EVAL, rate, stored_results
from app.eval.trajectory import DEFAULT_RUN
from app.models import Evidence, Result

JUDGE_PROMPT_VERSION = "j1"
INSTRUCTIONS = """You are an independent labeller for a car maker's vehicle-safety quality team. You get one owner
complaint and the recalls that covered that exact vehicle when the complaint arrived. Decide which recall, if any,
describes the SAME failure the owner reports.

- label: the campno of that recall; "none" if the complaint describes a real failure that no listed recall covers;
  "unclear" if the complaint is too vague to decide.
- Judge the failure described (what failed and how), not what the owner believes. Recall numbers in the complaint were
  removed on purpose.
- If several recalls describe the same failure, pick the best fit (the newer one if one replaces another).
- reason: one plain sentence.
Answer with JSON only."""


class JudgeLabel(BaseModel):
    label: str = Field(description="a candidate campno, or 'none', or 'unclear'")
    reason: str = Field(description="one plain sentence")


JUDGE_FORMAT = strict_format(JudgeLabel)


def judge_message(result: Result) -> str:
    """What the judge sees: the masked complaint and the candidates. Not the system's answer or the owner's recall."""
    complaint = result.complaint
    case = {
        "vehicle": f"{complaint.year} {complaint.make} {complaint.model}",
        "components_chosen_by_owner": complaint.components or ["(none)"],
        "complaint": result.intake.text,
        "candidate_recalls": [{"campno": recall.campno, "components": recall.components, "defect": recall.defect,
                               "consequence": recall.consequence} for recall in result.evidence.recalls],
    }
    return json.dumps(case, ensure_ascii=False, indent=1)


def valid_label(label: str, evidence: Evidence) -> str | None:
    label = label.strip()
    if label in ("none", "unclear") or evidence.recall(label) is not None:
        return label
    return None


async def label_one(llm: LlmSetup, result: Result, retries: int = 5) -> dict:
    """One blind label. Rate limits (429) are retried with backoff; anything else is recorded as an error."""
    message = Message(role="user", contents=[judge_message(result)])
    for attempt in range(retries + 1):
        try:
            response = await llm.client.get_response(
                [Message(role="system", contents=[INSTRUCTIONS]), message],
                options={"response_format": JUDGE_FORMAT})
            judged = JudgeLabel.model_validate_json(response.text)
            label = valid_label(judged.label, result.evidence)
            if label is None:
                return {"label": None, "reason": judged.reason, "error": f"not a candidate: {judged.label}"}
            return {"label": label, "reason": judged.reason, "error": None}
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, none stops the run
            if "429" in str(exc) and attempt < retries:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            return {"label": None, "reason": "", "error": str(exc)[:300]}
    return {"label": None, "reason": "", "error": "rate limited"}


def same_failure(a: str, b: str, evidence: Evidence) -> bool:
    """The same recall, or one replaced by the other (both describe the same failure)."""
    if a == b:
        return True
    first, second = evidence.recall(a), evidence.recall(b)
    return bool(first and second and (first.replaced_by == b or second.replaced_by == a))


def compare(results: dict[int, Result], labels: list[dict], owners: dict[int, str]) -> dict:
    """labels: {odino, set, label}. owners: set A's owner-named recall per odino (a sanity check of the judge)."""
    rows = [(row, results[row["odino"]]) for row in labels if row["label"] and row["odino"] in results]

    def says_known(result: Result) -> bool:
        return result.decision.outcome == "known_recall"

    system_known = [(row, r) for row, r in rows if says_known(r)]
    judge_recall = [(row, r) for row, r in rows if row["label"] not in ("none", "unclear")]
    judge_none = [(row, r) for row, r in rows if row["label"] == "none"]
    owner_rows = [(row, r) for row, r in rows if row["odino"] in owners and row["set"] == "A"]
    return {
        "labelled": len(rows), "not_labelled": len(labels) - len(rows),
        "judge_labels": dict(Counter(row["label"] if row["label"] in ("none", "unclear") else "a recall"
                                     for row, _ in rows)),
        "system_known": {
            "judge_agrees": rate(system_known, lambda p: p[0]["label"] not in ("none", "unclear")
                                 and same_failure(p[0]["label"], p[1].decision.campno, p[1].evidence)),
            "judge_says_none": rate(system_known, lambda p: p[0]["label"] == "none"),
            "judge_unclear": rate(system_known, lambda p: p[0]["label"] == "unclear"),
        },
        "judge_names_a_recall": {
            "system_found_it": rate(judge_recall, lambda p: says_known(p[1])
                                    and same_failure(p[0]["label"], p[1].decision.campno, p[1].evidence)),
            "system_asked_for_detail": rate(judge_recall, lambda p: p[1].decision.outcome == "needs_info"),
            "system_called_it_new_or_different": rate(judge_recall, lambda p: p[1].decision.outcome in
                                                      ("possible_new", "related_different")),
        },
        "judge_says_none": {
            "system_said_known": rate(judge_none, lambda p: says_known(p[1])),
            # of those: the owner had named that same recall, so the judge disagrees with the owner as well
            "system_said_known_owner_agreed": rate(
                [p for p in judge_none if says_known(p[1]) and p[0]["odino"] in owners],
                lambda p: same_failure(p[1].decision.campno, owners[p[0]["odino"]], p[1].evidence)),
            "system_escalated": rate(judge_none, lambda p: p[1].decision.outcome in
                                     ("possible_new", "related_different")),
        },
        "judge_vs_owner": rate(owner_rows, lambda p: p[0]["label"] not in ("none", "unclear")
                               and same_failure(p[0]["label"], owners[p[0]["odino"]], p[1].evidence)),
    }


async def label_all(results: dict[int, Result], cases: list[dict], concurrency: int) -> list[dict]:
    llm = setup_from_settings(get_settings())
    if llm is None:
        raise SystemExit("needs a model: set the model in .env (see README)")
    sem = asyncio.Semaphore(concurrency)

    async def one(case: dict) -> dict:
        async with sem:
            out = await label_one(llm, results[case["odino"]])
        print(f"  {case['id']:>5} {str(out['label']):<10} {(out['error'] or '')[:80]}", flush=True)
        return {"set": case["set"], "id": case["id"], "odino": case["odino"], **out}

    return await asyncio.gather(*(one(case) for case in cases))


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-as-judge labels (not human labels) and the comparison.")
    parser.add_argument("--run", default=DEFAULT_RUN)
    parser.add_argument("--report", action="store_true", help="rebuild the report from stored labels (no model)")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    results = {result.complaint.odino: result for result in stored_results(args.run)}
    cases = [case for name in "ab" for case in test_cases(name) if case["odino"] in results]
    path = EVAL / "labels" / f"llm-judge-{args.run}.jsonl.gz"
    if not args.report:
        labels = asyncio.run(label_all(results, cases, args.concurrency))
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as out:
            out.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in labels)
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        labels = [json.loads(line) for line in lines if line.strip()]
    owners = {case["odino"]: case["truth_campno"] for case in cases if case["set"] == "A"}
    report = {"name": f"llm-judge-{args.run}", "set": "llm_judge", "split": "test", "mode": "judge", "run": args.run,
              "judge_model": get_settings().deployment or "gpt-6.1-sol", "judge_prompt": JUDGE_PROMPT_VERSION,
              **compare(results, labels, owners)}
    (EVAL / "reports" / f"{report['name']}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("name", "set", "split", "mode")}, indent=1))


if __name__ == "__main__":
    main()
