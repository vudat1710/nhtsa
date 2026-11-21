"""The operations portal (for the people who build and run the system, not the analyst): every AI run with its audit
trail, failure drills, and the evaluation reports."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.ai.middleware import FaultMiddleware
from app.api import deps
from app.api.streaming import stream
from app.api.workspace import complaint_or_404
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
    result = deps.store().get(result_id)
    if result is None:
        raise HTTPException(404, "run not found")
    return result.model_dump()


@router.post("/drill/{odino}")
async def drill(odino: int, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    """Run a stored complaint with the AI on/off or deliberately broken."""
    if fault and fault not in FaultMiddleware.MODES:
        raise HTTPException(422, f"fault must be one of {FaultMiddleware.MODES}")
    return StreamingResponse(stream(complaint_or_404(odino), LABEL, use_llm, fault), media_type="text/event-stream")


@router.get("/evals")
def evals() -> list[dict]:
    """The latest report of each kind (newest name first), with the workflow-rule checks of that run attached when
    they exist (app/eval/trajectory.py): all of them are invariants, checked objectively against the run records."""
    reports_dir = EVAL / "reports"
    files = sorted(reports_dir.glob("*.json"), key=lambda path: path.stem, reverse=True) if reports_dir.exists() else []

    seen = set()
    out = []
    for path in files:
        report = json.loads(path.read_text(encoding="utf-8"))
        key = (report["set"], report["split"], report["mode"])
        if key in seen:
            continue
        seen.add(key)

        trajectory_file = EVAL / "trajectory" / f"{report['name']}.json"
        if trajectory_file.exists():
            data = json.loads(trajectory_file.read_text(encoding="utf-8"))
            report["rules"] = [{"id": rule_id, "question": check["question"], "k": check["k"], "n": check["n"]}
                               for rule_id, check in data["checks"].items()]
        out.append(report)
    return out
