"""Run one complaint through the pipeline and stream progress as Server-Sent Events; store the result before 'done'."""
import asyncio
import json
from collections.abc import AsyncIterator

from app.api import deps
from app.models import Complaint
from app.pipeline.workflow import run


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def stream(complaint: Complaint, label: str, use_llm: bool = True,
                 fault: str | None = None) -> AsyncIterator[str]:
    """Progress events as they happen, then {"type": "done", "result_id": ...}."""
    events: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(run(deps.con(), complaint, deps.llm(), use_llm=use_llm, fault=fault,
                                   emit=events.put_nowait))
    # None marks the end of the run (finished or failed), so the loop below stops.
    task.add_done_callback(lambda _: events.put_nowait(None))
    while (event := await events.get()) is not None:
        yield sse(event)
    try:
        result = task.result()
    except Exception as exc:  # a bug, not a model failure (those become the fallback inside the workflow)
        yield sse({"type": "error", "message": str(exc)})
        return
    deps.store().save(result, label)
    yield sse({"type": "done", "result_id": result.id, "outcome": result.decision.outcome})
