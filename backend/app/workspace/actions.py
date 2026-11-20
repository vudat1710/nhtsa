"""Apply what the analyst decided on a ticket. Validated against the case's own evidence (you can only link a recall
that covered this vehicle on that date), logged, and reflected in the ticket status and emerging issues."""
from pydantic import BaseModel

from app.models import Result
from app.store.tickets import IssueKind, Tickets
from app.workspace.messages import display_campno
from app.workspace.suggest import ActionId


class ActionRequest(BaseModel):
    action: ActionId
    campno: str | None = None
    issue_id: int | None = None
    issue_title: str | None = None
    issue_kind: IssueKind | None = None
    issue_comp: str | None = None
    message: str | None = None
    reason: str = ""
    disagrees: bool = False          # the analyst chose something other than the suggested action


class ActionError(ValueError):
    pass


def apply(tickets: Tickets, r: Result, req: ActionRequest) -> dict:
    c = r.complaint
    odino = c.odino
    if req.disagrees:
        if not req.reason.strip():
            raise ActionError("say briefly why you disagree with the suggestion (it is how the system learns)")
        tickets.log(odino, "disagreed", f"{req.action}: {req.reason.strip()}", r.id)

    def issue(kind: IssueKind) -> int:
        if req.issue_id is not None:
            if tickets.issue(req.issue_id) is None:
                raise ActionError(f"emerging issue {req.issue_id} does not exist")
            return req.issue_id
        if not (req.issue_title or "").strip():
            raise ActionError("a new emerging issue needs a title")
        comp = req.issue_comp or (c.comps[0] if c.comps else "")
        return tickets.create_issue(req.issue_title.strip(), kind, c.make, c.model, comp, req.campno)

    if req.action == "link_close":
        if not req.campno or r.evidence.recall(req.campno) is None:
            raise ActionError("choose a recall that covered this vehicle when the complaint arrived")
        issue_id = issue("remedy_concern") if req.issue_kind == "remedy_concern" else None
        if issue_id:
            tickets.add_to_issue(issue_id, odino)
        tickets.set(odino, "resolved", campno=req.campno, issue_id=issue_id)
        tickets.log(odino, "linked_recall", display_campno(req.campno) + (f"; flagged to issue {issue_id}"
                                                                          if issue_id else ""), r.id)
        if req.message:
            tickets.log(odino, "replied_to_owner", req.message, r.id)
    elif req.action == "request_info":
        if not (req.message or "").strip():
            raise ActionError("the message to the owner is empty")
        tickets.set(odino, "waiting")
        tickets.log(odino, "asked_owner", req.message.strip(), r.id)
    elif req.action in ("add_to_issue", "new_issue"):
        if req.action == "add_to_issue" and req.issue_id is None:
            raise ActionError("choose an emerging issue")
        issue_id = issue(req.issue_kind or "new_defect")
        tickets.add_to_issue(issue_id, odino)
        tickets.set(odino, "escalated", issue_id=issue_id)
        tickets.log(odino, "escalated", tickets.issue(issue_id).title, r.id)
    elif req.action == "monitor":
        tickets.set(odino, "monitoring")
        tickets.log(odino, "monitoring", req.reason.strip() or "recorded; escalate if more owners report it", r.id)
    else:  # close_no_action
        if not req.reason.strip():
            raise ActionError("say briefly why this is not a safety defect")
        tickets.set(odino, "resolved")
        tickets.log(odino, "closed", req.reason.strip(), r.id)
    return tickets.status(odino)
