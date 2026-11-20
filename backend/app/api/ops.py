"""The operations portal (for the people who build and run the system, not the analyst): every AI run with its audit
trail, failure drills, a sandbox for typed complaints, and the evaluation reports."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api import deps
from app.api.streaming import stream
from app.data import queries
from app.eval.run import EVAL
from app.models import Complaint

router = APIRouter(prefix="/ops")
LABEL = "ops"     # runs made from the portal never change what the analyst sees
FAULTS = ("llm_down", "malformed_json", "bad_quote", "unknown_recall", "malformed_json:always")


@router.get("/health")
def health() -> dict:
    setup = deps.llm()
    return {"llm_mode": setup.cassette_mode, "model": setup.model_name or None, "live_model": bool(setup.model_name)}


@router.get("/runs")
def runs(label: str | None = None, limit: int = 200) -> list[dict]:
    return deps.store().runs(label, limit)


@router.get("/runs/{result_id}")
def run_detail(result_id: str) -> dict:
    r = deps.store().get(result_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r.model_dump()


@router.get("/complaints/{odino}")
def complaint(odino: int) -> dict:
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return c.model_dump()


def check_fault(fault: str | None) -> str | None:
    if fault and fault not in FAULTS:
        raise HTTPException(422, f"fault must be one of {FAULTS}")
    return fault


@router.post("/drill/{odino}")
async def drill(odino: int, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    """Run a stored complaint with the AI on/off or deliberately broken."""
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return StreamingResponse(stream(c, LABEL, use_llm, check_fault(fault)), media_type="text/event-stream")


@router.post("/try")
async def try_complaint(c: Complaint, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    """A complaint typed in (not in the NHTSA data). Same pipeline, same rules."""
    if not c.text.strip():
        raise HTTPException(422, "complaint text is empty")
    return StreamingResponse(stream(c.model_copy(update={"odino": None}), LABEL, use_llm, check_fault(fault)),
                             media_type="text/event-stream")


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
        if key in seen or rep["set"] == "demo":
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


@router.get("/evals/{name}/cases")
def eval_cases(name: str) -> list[dict]:
    path = EVAL / "runs" / f"{name}.jsonl"
    if path.parent != EVAL / "runs" or not path.exists():
        raise HTTPException(404, "run not found")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
