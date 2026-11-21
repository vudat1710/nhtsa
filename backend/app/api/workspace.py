"""The analyst's workspace: inbox, ticket (what it is, why, what to do), actions, and emerging issues.
No model names, tokens or simulated failures here; those live in the operations portal (ops.py)."""
import json
from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api import deps
from app.api.streaming import stream
from app.ask.service import Turn, ask
from app.config import ROOT
from app.data import queries
from app.models import Complaint
from app.workspace.actions import ActionConflict, ActionError, ActionRequest, apply, same_suggestion
from app.workspace.suggest import Suggestion, related_other_years, suggest
from app.workspace.trail import trail

router = APIRouter()
LABEL = "queue"   # store label for runs made from the workspace


def demo_cases() -> list[dict]:
    return json.loads((ROOT / "data" / "eval" / "demo.json").read_text(encoding="utf-8"))["cases"]


def inbox_ids(limit: int = 15) -> list[int]:
    """Complaints typed in by an analyst (newest first), then the demo complaints, then a slice of real, recent owner
    complaints (a normal morning's inbox)."""
    typed = deps.store().tickets.typed_ids()
    demo = [case["odino"] for case in demo_cases()]
    rows = deps.con().execute(
        """SELECT odino FROM complaints WHERE source = 'owner' AND year != '9999' AND length(text) > 200
           ORDER BY received DESC, odino DESC LIMIT ?""", (limit,)).fetchall()
    recent = [row[0] for row in rows]
    # dict.fromkeys drops a recent complaint that is also a demo one, keeping the order.
    return list(dict.fromkeys(typed + demo + recent))


def related_for(result) -> list[dict]:
    """Recalls of the same part on other model years that share failure words (unmatched complaints only)."""
    if result.decision.outcome not in ("possible_new", "related_different"):
        return []
    complaint = result.complaint
    comps = [comp for comp in complaint.comps if comp != "UNKNOWN OR OTHER"]
    vehicle = queries.Vehicle(complaint.make, complaint.model, complaint.year)
    candidates = queries.recalls_other_years(deps.con(), vehicle, comps, complaint.received)
    return related_other_years(result, candidates)


def suggestion(result) -> Suggestion:
    """The analyst's view of a stored run, with other-year recalls of the same part as context for unmatched ones."""
    return suggest(result, deps.store().tickets, related_for(result), can_recheck=deps.llm() is not None)


def complaint_or_404(odino: int) -> Complaint:
    """An NHTSA complaint, or one typed in by an analyst (negative ticket number)."""
    if odino < 0:
        complaint = deps.store().tickets.typed(odino)
    else:
        complaint = queries.complaint(deps.con(), odino)
    if complaint is None:
        raise HTTPException(404, f"complaint {odino} not found")
    return complaint


class NewComplaint(BaseModel):
    """A complaint typed in by an analyst. The vehicle and component must be NHTSA's own names (see /vehicles)."""
    make: str
    model: str
    year: str
    component: str
    text: str = Field(min_length=1, max_length=5000)
    crash: bool = False
    fire: bool = False
    injured: int = Field(default=0, ge=0, le=99)


@router.get("/vehicles")
def vehicles(make: str | None = None, model: str | None = None) -> list[str]:
    """NHTSA's makes; a make's models; or a model's years (newest first)."""
    catalog = deps.vehicles()
    if make is None:
        return sorted(catalog)
    models = catalog.get(make, {})
    if model is None:
        return sorted(models)
    return models.get(model, [])


@router.get("/components")
def components() -> list[str]:
    return deps.components()


@router.post("/complaints")
def new_complaint(body: NewComplaint) -> dict:
    """Store a typed-in complaint as a new ticket, received today. It is checked like any other ticket: only recalls
    filed before today are candidates."""
    years = deps.vehicles().get(body.make, {}).get(body.model, [])
    if body.year not in years:
        raise HTTPException(422, f"{body.year} {body.make} {body.model} is not in NHTSA's vehicle list: pick the make, "
                                 "model and year from the lists (recalls are matched on NHTSA's exact names)")
    if body.component not in deps.components():
        raise HTTPException(422, f"'{body.component}' is not one of NHTSA's component names")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "the complaint text is empty")
    complaint = Complaint(make=body.make, model=body.model, year=body.year, received=date.today().isoformat(),
                          crash=int(body.crash), fire=int(body.fire), injured=body.injured, text=text,
                          components=[body.component])
    return {"odino": deps.store().tickets.add_typed(complaint)}


@router.get("/inbox")
def inbox() -> list[dict]:
    latest = deps.store().latest(LABEL)
    tickets = deps.store().tickets
    statuses = tickets.statuses()
    demo_titles = {case["odino"]: case["title"] for case in demo_cases()}
    items = []
    for odino in inbox_ids():
        complaint = complaint_or_404(odino)
        result = latest.get(odino)

        # A ticket nobody has acted on yet shows as "suggested" once the system has checked it.
        status = statuses.get(odino, {}).get("status")
        if not status:
            status = "suggested" if result else "new"

        severity = []
        if complaint.crash:
            severity.append("crash")
        if complaint.fire:
            severity.append("fire")
        if complaint.injured:
            severity.append("injury")

        summary = None
        if result:
            suggested = suggestion(result)
            primary_action = next((action.label for action in suggested.actions if action.primary), None)
            summary = {"outcome": suggested.outcome, "headline": suggested.headline,
                       "confidence": suggested.confidence, "check": bool(suggested.check_note),
                       "action": primary_action}

        items.append({"odino": odino,
                      "vehicle": f"{complaint.year} {complaint.make.title()} {complaint.model.title()}",
                      "received": complaint.received,
                      "snippet": complaint.text[:160],
                      "severity": severity,
                      "status": status,
                      "demo": demo_titles.get(odino),
                      "suggestion": summary})
    return items


@router.get("/tickets/{odino}")
def ticket(odino: int) -> dict:
    complaint = complaint_or_404(odino)
    result = deps.store().latest(LABEL).get(odino)
    tickets = deps.store().tickets
    status = tickets.status(odino)
    if status["status"] == "new" and result:
        status["status"] = "suggested"

    demo = None
    for case in demo_cases():
        if case["odino"] == odino:
            demo = case
            break

    if result:
        suggested = suggestion(result).model_dump()
        steps = [step.model_dump() for step in trail(result)]
    else:
        suggested = None
        steps = []
    history = [action.model_dump() for action in tickets.history(odino)]
    questions = [json.loads(turn) for turn in tickets.questions(odino)]
    return {"complaint": complaint.model_dump(), "status": status, "history": history, "suggestion": suggested,
            "demo": demo, "trail": steps, "questions": questions}


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


@router.post("/tickets/{odino}/ask")
async def ask_about(odino: int, q: Question) -> dict:
    """A follow-up question about this checked complaint, answered with verified citations (app/ask)."""
    result = deps.store().latest(LABEL).get(odino)
    if result is None:
        raise HTTPException(409, "check this ticket first")
    llm = deps.llm()
    if llm is None:
        raise HTTPException(503, "no model configured (NHTSA_AZURE_ENDPOINT), so follow-up questions are off")
    tickets = deps.store().tickets
    earlier_turns = [Turn.model_validate_json(body) for body in tickets.questions(odino)]
    history = earlier_turns[-6:]
    turn = await ask(deps.con(), llm, result, history, q.question.strip(), related_for(result))
    tickets.add_question(odino, turn.model_dump_json())
    return turn.model_dump()


@router.post("/tickets/{odino}/check")
async def check(odino: int) -> StreamingResponse:
    return StreamingResponse(stream(complaint_or_404(odino), LABEL), media_type="text/event-stream")


@router.post("/tickets/{odino}/actions")
def act(odino: int, req: ActionRequest) -> dict:
    store = deps.store()
    # One action at a time, from the first check to the last write: a re-check or another analyst's action can't land
    # between checking what the analyst saw and saving what they did (new runs are saved under the same lock)
    with store.tickets.lock:
        result = store.latest(LABEL).get(odino)
        if result is None:
            raise HTTPException(409, "check this ticket first")
        if req.result_id != result.id:
            # The ticket was checked again after the analyst opened it: the action would be logged against a
            # suggestion they never saw
            raise HTTPException(409, "this ticket was checked again since you opened it: review the new suggestion")
        suggested = next((action for action in suggestion(result).actions if action.primary), None)
        if not same_suggestion(req.suggested, suggested):
            raise HTTPException(409, "the suggestion changed since you opened this ticket: review it")
        try:
            return apply(store.tickets, result, req, suggested)
        except ActionConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ActionError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.get("/issues")
def issues() -> list[dict]:
    out = []
    for emerging in deps.store().tickets.issues():
        complaints = [complaint_or_404(odino) for odino in emerging.complaints]
        severe = 0
        for complaint in complaints:
            if complaint.crash or complaint.fire or complaint.injured:
                severe += 1
        summary = emerging.model_dump()
        summary["count"] = len(complaints)
        summary["severe"] = severe
        summary["latest"] = max((complaint.received for complaint in complaints), default=None)
        out.append(summary)
    return out


@router.get("/issues/{issue_id}")
def issue(issue_id: int) -> dict:
    emerging = deps.store().tickets.issue(issue_id)
    if emerging is None:
        raise HTTPException(404, "issue not found")
    details = []
    for odino in emerging.complaints:
        complaint = complaint_or_404(odino)
        details.append({"odino": complaint.odino,
                        "vehicle": f"{complaint.year} {complaint.make.title()} {complaint.model.title()}",
                        "received": complaint.received,
                        "text": complaint.text,
                        "severe": bool(complaint.crash or complaint.fire or complaint.injured)})
    out = emerging.model_dump()
    out["complaint_details"] = details
    return out
