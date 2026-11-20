"""The analyst's workspace: inbox, ticket (what it is, why, what to do), actions, and emerging issues.
No model names, tokens or simulated failures here; those live in the operations portal (ops.py)."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api import deps
from app.api.streaming import stream
from app.config import ROOT
from app.data import queries
from app.models import Complaint
from app.workspace.actions import ActionError, ActionRequest, apply
from app.workspace.suggest import Suggestion, related_other_years, suggest

router = APIRouter()
LABEL = "queue"   # store label for runs made from the workspace


def demo_cases() -> list[dict]:
    return json.loads((ROOT / "data" / "eval" / "demo.json").read_text(encoding="utf-8"))["cases"]


def inbox_ids(limit: int = 15) -> list[int]:
    """The demo complaints first, then a slice of real, recent owner complaints (a normal morning's inbox)."""
    demo = [d["odino"] for d in demo_cases() if not d.get("fault")]
    rows = deps.con().execute(
        """SELECT odino FROM complaints WHERE source = 'owner' AND year != '9999' AND length(text) > 200
           ORDER BY received DESC, odino DESC LIMIT ?""", (limit,)).fetchall()
    return list(dict.fromkeys([*demo, *[r[0] for r in rows]]))


def suggestion(r) -> Suggestion:
    """The analyst's view of a stored run, with other-year recalls of the same part as context for unmatched ones."""
    c = r.complaint
    missing = [x.campno for x in r.evidence.recalls if not x.model_years]
    if missing:  # runs stored before model years were part of the evidence
        years = queries.recall_model_years(deps.con(), missing, c.make, c.model)
        for x in r.evidence.recalls:
            x.model_years = x.model_years or years.get(x.campno, [])
    related = []
    if r.decision.outcome in ("possible_new", "related_different"):
        comps = [x for x in c.comps if x != "UNKNOWN OR OTHER"]
        related = related_other_years(r, queries.recalls_other_years(
            deps.con(), queries.Vehicle(c.make, c.model, c.year), comps, c.received))
    return suggest(r, deps.store().tickets, related)


def complaint_or_404(odino: int) -> Complaint:
    c = queries.complaint(deps.con(), odino)
    if c is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return c


@router.get("/inbox")
def inbox() -> list[dict]:
    latest, tickets = deps.store().latest(LABEL), deps.store().tickets
    statuses = tickets.statuses()
    demo = {d["odino"]: d["title"] for d in demo_cases() if not d.get("fault")}
    items = []
    for odino in inbox_ids():
        c, r = complaint_or_404(odino), latest.get(odino)
        s = suggestion(r) if r else None
        status = statuses.get(odino, {}).get("status") or ("suggested" if r else "new")
        items.append({"odino": odino, "vehicle": f"{c.year} {c.make.title()} {c.model.title()}",
                      "received": c.received, "snippet": c.text[:160],
                      "severity": [x for x, on in (("crash", c.crash), ("fire", c.fire), ("injury", c.injured)) if on],
                      "status": status, "demo": demo.get(odino),
                      "suggestion": None if s is None else {"outcome": s.outcome, "headline": s.headline,
                                                            "confidence": s.confidence, "check": bool(s.check_note),
                                                            "action": next(a.label for a in s.actions if a.primary)}})
    return items


@router.get("/tickets/{odino}")
def ticket(odino: int) -> dict:
    c, r = complaint_or_404(odino), deps.store().latest(LABEL).get(odino)
    tickets = deps.store().tickets
    status = tickets.status(odino)
    if status["status"] == "new" and r:
        status["status"] = "suggested"
    demo = next((d for d in demo_cases() if d["odino"] == odino and not d.get("fault")), None)
    return {"complaint": c.model_dump(), "status": status, "history": [a.model_dump() for a in tickets.history(odino)],
            "suggestion": suggestion(r).model_dump() if r else None, "demo": demo}


@router.post("/tickets/{odino}/check")
async def check(odino: int) -> StreamingResponse:
    return StreamingResponse(stream(complaint_or_404(odino), LABEL), media_type="text/event-stream")


@router.post("/tickets/{odino}/actions")
def act(odino: int, req: ActionRequest) -> dict:
    r = deps.store().latest(LABEL).get(odino)
    if r is None:
        raise HTTPException(409, "check this ticket first")
    try:
        return apply(deps.store().tickets, r, req)
    except ActionError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/issues")
def issues() -> list[dict]:
    out = []
    for i in deps.store().tickets.issues():
        cs = [queries.complaint(deps.con(), o) for o in i.complaints]
        out.append(i.model_dump() | {"count": len(cs), "severe": sum(bool(c.crash or c.fire or c.injured) for c in cs),
                                     "latest": max((c.received for c in cs), default=None)})
    return out


@router.get("/issues/{issue_id}")
def issue(issue_id: int) -> dict:
    i = deps.store().tickets.issue(issue_id)
    if i is None:
        raise HTTPException(404, "issue not found")
    cs = [queries.complaint(deps.con(), o) for o in i.complaints]
    return i.model_dump() | {"complaint_details": [
        {"odino": c.odino, "vehicle": f"{c.year} {c.make.title()} {c.model.title()}", "received": c.received,
         "text": c.text, "severe": bool(c.crash or c.fire or c.injured)} for c in cs]}
