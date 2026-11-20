"""The operations portal (for the people who build and run the system, not the analyst): every AI run with its audit
trail, failure drills, and the evaluation reports."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.middleware import FaultMiddleware
from app.api import deps
from app.api.streaming import stream
from app.data import queries
from app.eval.run import EVAL

router = APIRouter(prefix="/ops")
LABEL = "ops"     # runs made from the portal never change what the analyst sees


@router.get("/health")
def health() -> dict:
    setup = deps.llm()
    return {"model": setup.model_name if setup else None}


@router.get("/runs")
def runs(limit: int = 200) -> list[dict]:
    return deps.store().runs(limit)


@router.get("/runs/{result_id}")
def run_detail(result_id: str) -> dict:
    r = deps.store().get(result_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r.model_dump()


@router.post("/drill/{odino}")
async def drill(odino: int, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    """Run a stored complaint with the AI on/off or deliberately broken."""
    if fault and fault not in FaultMiddleware.MODES:
        raise HTTPException(422, f"fault must be one of {FaultMiddleware.MODES}")
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return StreamingResponse(stream(c, LABEL, use_llm, fault), media_type="text/event-stream")


@router.get("/evals")
def evals() -> list[dict]:
    """Latest report per (sets, split, mode), newest first (a rescored report wins over its original), with the
    adjudication summary attached when one exists."""
    files = list((EVAL / "reports").glob("*.json")) if (EVAL / "reports").exists() else []
    files.sort(key=lambda f: (f.stem.removesuffix("-rescored"), f.stem.endswith("-rescored")), reverse=True)
    seen, out = set(), []
    for f in files:
        rep = json.loads(f.read_text(encoding="utf-8"))
        key = (rep["set"], rep["split"], rep["mode"])
        if key in seen:
            continue
        seen.add(key)
        adj = EVAL / "adjudication" / f"{rep['name']}.json"
        if adj.exists():
            data = json.loads(adj.read_text(encoding="utf-8"))
            verdicts = ("ai_right", "owner_right", "unclear")
            rep["adjudication"] = {
                group: {"disagreements": g["disagreements"],
                        "adjudicated": sum(bool(c["verdict"]) for c in g["cases"]),
                        **{v: sum(c["verdict"] == v for c in g["cases"]) for v in verdicts}}
                for group, g in data["groups"].items()}
        out.append(rep)
    return out
