"""The operations portal (for the people who build and run the system, not the analyst): every AI run with its audit
trail, failure drills, and the evaluation reports."""
import json
from pathlib import Path

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
    result = deps.store().get(result_id)
    if result is None:
        raise HTTPException(404, "run not found")
    return result.model_dump()


@router.post("/drill/{odino}")
async def drill(odino: int, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    """Run a stored complaint with the AI on/off or deliberately broken."""
    if fault and fault not in FaultMiddleware.MODES:
        raise HTTPException(422, f"fault must be one of {FaultMiddleware.MODES}")
    complaint = queries.complaint(deps.con(), odino)
    if complaint is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return StreamingResponse(stream(complaint, LABEL, use_llm, fault), media_type="text/event-stream")


@router.get("/evals")
def evals() -> list[dict]:
    """Latest report per (sets, split, mode), newest first (a rescored report wins over its original), with the
    adjudication summary attached when one exists."""
    reports_dir = EVAL / "reports"
    files = list(reports_dir.glob("*.json")) if reports_dir.exists() else []

    def newest_first(path: Path) -> tuple[str, bool]:
        # A rescored report sorts just before its original, so it is the one kept below.
        return path.stem.removesuffix("-rescored"), path.stem.endswith("-rescored")

    files.sort(key=newest_first, reverse=True)

    seen = set()
    out = []
    for path in files:
        report = json.loads(path.read_text(encoding="utf-8"))
        key = (report["set"], report["split"], report["mode"])
        if key in seen:
            continue
        seen.add(key)

        adjudication_file = EVAL / "adjudication" / f"{report['name']}.json"
        if adjudication_file.exists():
            data = json.loads(adjudication_file.read_text(encoding="utf-8"))
            summary = {}
            for group, details in data["groups"].items():
                cases = details["cases"]
                counts = {"disagreements": details["disagreements"],
                          "adjudicated": len([case for case in cases if case["verdict"]])}
                for verdict in ("ai_right", "owner_right", "unclear"):
                    counts[verdict] = len([case for case in cases if case["verdict"] == verdict])
                summary[group] = counts
            report["adjudication"] = summary
        out.append(report)
    return out
