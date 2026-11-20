"""Evaluation reports for the trust page: the latest report per (sets, split, mode), newest first."""
import json

from fastapi import APIRouter, HTTPException

from app.eval.run import EVAL

router = APIRouter()


def reports() -> list[dict]:
    files = sorted((EVAL / "reports").glob("*.json"), reverse=True) if (EVAL / "reports").exists() else []
    seen, out = set(), []
    for f in files:
        rep = json.loads(f.read_text(encoding="utf-8"))
        key = (rep["set"], rep["split"], rep["mode"])
        if key not in seen and rep["set"] != "demo":
            seen.add(key)
            out.append(rep)
    return out


@router.get("/evals")
def evals() -> list[dict]:
    return reports()


@router.get("/evals/{name}/cases")
def eval_cases(name: str) -> list[dict]:
    path = EVAL / "runs" / f"{name}.jsonl"
    if not path.exists() or path.parent != EVAL / "runs":
        raise HTTPException(404, "run not found")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
