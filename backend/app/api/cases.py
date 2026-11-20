"""The analyst's queue and case files. Running a case streams progress (Server-Sent Events) and stores the result."""
import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api import deps
from app.config import ROOT
from app.data import queries
from app.models import Complaint
from app.pipeline.workflow import run

router = APIRouter()
QUEUE = "queue"   # store label for runs made from the UI
FAULTS = ("llm_down", "malformed_json", "bad_quote", "unknown_recall", "malformed_json:always")


def demo_cases() -> list[dict]:
    return json.loads((ROOT / "data" / "eval" / "demo.json").read_text(encoding="utf-8"))["cases"]


def recent_complaints(limit: int = 15) -> list[int]:
    """A slice of real, recent, owner-written complaints so the queue looks like a normal morning."""
    rows = deps.con().execute(
        """SELECT odino FROM complaints WHERE source = 'owner' AND year != '9999' AND length(text) > 200
           ORDER BY received DESC, odino DESC LIMIT ?""", (limit,)).fetchall()
    return [r[0] for r in rows]


def summary(c: Complaint, result) -> dict:
    d = result.decision if result else None
    return {"odino": c.odino, "vehicle": f"{c.year} {c.make} {c.model}", "received": c.received,
            "components": c.components, "severe": bool(c.crash or c.fire or c.injured), "snippet": c.text[:180],
            "result": None if d is None else {"id": result.id, "outcome": d.outcome, "confidence": d.confidence,
                                              "campno": d.campno, "escalate": d.escalate, "source": d.source,
                                              "flags": d.flags}}


@router.get("/queue")
def queue() -> list[dict]:
    latest = deps.store().latest(QUEUE)
    demo = {c["odino"]: c for c in demo_cases() if not c.get("fault")}
    items = []
    for odino in [*demo, *[o for o in recent_complaints() if o not in demo]]:
        c = queries.complaint(deps.con(), odino)
        items.append(summary(c, latest.get(odino)) | {"demo": demo.get(odino, {}).get("title")})
    return items


@router.get("/complaints/{odino}")
def complaint(odino: int) -> dict:
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return c.model_dump()


@router.get("/cases/{odino}")
def case(odino: int) -> dict:
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    r = deps.store().latest(QUEUE).get(odino)
    demo = next((d for d in demo_cases() if d["odino"] == odino and not d.get("fault")), None)
    return {"complaint": c.model_dump(), "result": r.model_dump() if r else None, "demo": demo,
            "reviews": [v.model_dump() for v in deps.store().reviews([r.id])] if r else []}


@router.get("/results/{result_id}")
def result(result_id: str) -> dict:
    r = deps.store().get(result_id)
    if r is None:
        raise HTTPException(404, "result not found")
    return r.model_dump()


async def stream(complaint: Complaint, use_llm: bool, fault: str | None) -> AsyncIterator[str]:
    """Progress events as they happen, then {"type": "done", "result": ...}. The result is stored before 'done'."""
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(run(deps.con(), complaint, deps.llm(), use_llm=use_llm, fault=fault, emit=q.put_nowait))
    task.add_done_callback(lambda _: q.put_nowait(None))
    while (event := await q.get()) is not None:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    try:
        r = task.result()
    except Exception as exc:  # a bug, not a model failure (those become the fallback inside the workflow)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        return
    deps.store().save(r, QUEUE)
    yield f"data: {json.dumps({'type': 'done', 'result': r.model_dump()}, ensure_ascii=False)}\n\n"


def check_fault(fault: str | None) -> str | None:
    if fault and fault not in FAULTS:
        raise HTTPException(422, f"fault must be one of {FAULTS}")
    return fault


@router.post("/cases/{odino}/run")
async def run_case(odino: int, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return StreamingResponse(stream(c, use_llm, check_fault(fault)), media_type="text/event-stream")


@router.post("/complaints/run")
async def run_typed(c: Complaint, use_llm: bool = True, fault: str | None = None) -> StreamingResponse:
    """A complaint typed into the UI (not in the NHTSA data). Same pipeline, same rules."""
    if not c.text.strip():
        raise HTTPException(422, "complaint text is empty")
    return StreamingResponse(stream(c.model_copy(update={"odino": None}), use_llm, check_fault(fault)),
                             media_type="text/event-stream")
