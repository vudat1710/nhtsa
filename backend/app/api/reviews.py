"""Engineer review: escalated cases wait here until a person confirms, links or dismisses them. Decisions are stored
as rows (not paused workflows) because an engineer may answer days later; they also become future evaluation labels."""
from fastapi import APIRouter, HTTPException

from app.api import deps
from app.api.cases import QUEUE
from app.store.results import Review

router = APIRouter()


@router.get("/reviews")
def review_queue() -> list[dict]:
    """Escalated cases (newest result per complaint), with any review already given."""
    latest = [r for r in deps.store().latest(QUEUE).values() if r.decision.escalate]
    reviews = {v.result_id: v for v in deps.store().reviews([r.id for r in latest])}
    out = []
    for r in sorted(latest, key=lambda r: ("severe" not in r.decision.flags, r.complaint.received)):
        c, d = r.complaint, r.decision
        out.append({"result_id": r.id, "odino": c.odino, "vehicle": f"{c.year} {c.make} {c.model}",
                    "received": c.received, "outcome": d.outcome, "confidence": d.confidence, "flags": d.flags,
                    "reason": d.reasons[0] if d.reasons else "",
                    "review": reviews[r.id].model_dump() if r.id in reviews else None})
    return out


@router.post("/results/{result_id}/review")
def add_review(result_id: str, review: Review) -> dict:
    r = deps.store().get(result_id)
    if r is None:
        raise HTTPException(404, "result not found")
    if review.action in ("link_recall", "override") and not review.campno:
        raise HTTPException(422, f"{review.action} needs a recall number")
    if review.campno and review.action == "link_recall" and r.evidence.recall(review.campno) is None:
        raise HTTPException(422, f"{review.campno} is not one of this case's candidate recalls")
    return deps.store().add_review(review.model_copy(update={"result_id": result_id})).model_dump()
