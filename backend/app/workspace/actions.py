"""Apply what the analyst decided on a ticket.

Everything is validated first, then the status, the action log and any emerging issue are written in one transaction,
so a rejected action leaves no trace and an accepted one is recorded whole. Each action is tied to the run the analyst
was shown (`result_id`); the caller refuses an action on a run that is no longer the ticket's latest.

Validated against the case's own evidence (you can only link a recall that covered this vehicle on that date), the
ticket's state (a resolved ticket must be reopened first), and the suggestion for that run: choosing anything else
needs a reason, decided here, not by the client.
"""
from pydantic import BaseModel

from app.models import Result
from app.store.tickets import Issue, IssueKind, Tickets
from app.workspace.messages import display_campno
from app.workspace.suggest import ActionId, ActionOption


class SeenSuggestion(BaseModel):
    """The suggested action as the analyst saw it on screen (None: nothing was suggested)."""
    action: ActionId
    campno: str | None = None
    issue_id: int | None = None


class ActionRequest(BaseModel):
    action: ActionId
    result_id: str                   # the run whose suggestion the analyst was looking at
    suggested: SeenSuggestion | None  # required (may be null): what that suggestion was, as shown
    campno: str | None = None
    issue_id: int | None = None
    issue_title: str | None = None
    issue_kind: IssueKind | None = None
    issue_comp: str | None = None
    message: str | None = None
    reason: str = ""


def same_suggestion(seen: SeenSuggestion | None, current: ActionOption | None) -> bool:
    """The suggestion also depends on live state (an emerging issue opened meanwhile turns "open a new issue" into
    "add to the existing one"), so the run id alone doesn't pin what the analyst saw."""
    if seen is None or current is None:
        return seen is None and current is None
    return (seen.action, seen.campno, seen.issue_id) == (current.id, current.campno, current.issue_id)


class ActionError(ValueError):
    """The request is invalid (HTTP 422)."""


class ActionConflict(ActionError):
    """The request doesn't fit the ticket's current state (HTTP 409)."""


# What each action records in the log, the status it leads to, and the statuses it may start from. Drafts are recorded,
# not sent: there is no channel to the owner, so the log says "drafted".
LOGGED = {"link_close": "linked_recall", "request_info": "owner_request_drafted", "add_to_issue": "escalated",
          "new_issue": "escalated", "monitor": "monitoring", "close_no_action": "closed", "reopen": "reopened"}
LEADS_TO = {"link_close": "resolved", "request_info": "waiting", "add_to_issue": "escalated", "new_issue": "escalated",
            "monitor": "monitoring", "close_no_action": "resolved", "reopen": "suggested"}
DECIDE = {"link_close", "request_info", "add_to_issue", "new_issue", "monitor", "close_no_action"}
ALLOWED_FROM = {
    "new": DECIDE, "suggested": DECIDE,
    "waiting": DECIDE | {"reopen"},                       # the owner may answer, or not
    "monitoring": (DECIDE - {"monitor"}) | {"reopen"},
    "resolved": {"reopen"}, "escalated": {"reopen"},      # closed: reopen first, with a reason
}


def disagrees_with(req: ActionRequest, suggested: ActionOption | None) -> bool:
    """Anything other than the suggested action, including linking another recall or another emerging issue."""
    if suggested is None or req.action == "reopen":
        return False
    if req.action != suggested.id:
        return True
    if req.action == "link_close":
        return req.campno != suggested.campno
    if req.action == "add_to_issue":
        return req.issue_id != suggested.issue_id
    return False


def apply(tickets: Tickets, result: Result, req: ActionRequest, suggested: ActionOption | None) -> dict:
    """suggested: the primary action of the suggestion for `result` (None when nothing was suggested)."""
    complaint = result.complaint
    odino = complaint.odino
    reason = req.reason.strip()
    message = (req.message or "").strip()

    # ---------- validate: nothing is written until the whole request is known to be good ----------
    if req.action == "recheck":
        raise ActionError("checking again is done with the check, not as an action")

    # The same action on the same run, sent twice (a double click, a retry): already done, nothing to write.
    current = tickets.status(odino)
    last = tickets.last_action(odino, set(LOGGED.values()))
    if (last and last["result_id"] == result.id and last["action"] == LOGGED[req.action]
            and current["status"] == LEADS_TO[req.action]
            and (req.action != "link_close" or current["campno"] == req.campno)):
        return current

    status = "suggested" if current["status"] == "new" else current["status"]  # checked, nobody acted yet
    if req.action not in ALLOWED_FROM.get(status, set()):
        if req.action == "reopen":
            raise ActionConflict("this ticket is open already")
        raise ActionConflict(f"this ticket is {status}: reopen it first (with a reason)")

    disagrees = disagrees_with(req, suggested)
    if disagrees and not reason:
        raise ActionError("say briefly why you chose something other than the suggestion (it is how the system "
                          "learns)")
    if req.action == "reopen" and not reason:
        raise ActionError("say briefly why the ticket is reopened")

    issue: Issue | None = None
    new_issue_title = None
    kind: IssueKind | None = None
    if req.action in ("add_to_issue", "new_issue") or (req.action == "link_close" and req.issue_kind):
        kind = req.issue_kind or ("remedy_concern" if req.action == "link_close" else "new_defect")
        if req.action == "add_to_issue" and req.issue_id is None:
            raise ActionError("choose an emerging issue")
        if req.issue_id is not None:
            issue = tickets.issue(req.issue_id)
            if issue is None:
                raise ActionError(f"emerging issue {req.issue_id} does not exist")
            # An issue groups one model's complaints (and, for a remedy concern, one recall): another vehicle or
            # recall needs a stated reason, which is logged
            other_vehicle = (issue.make, issue.model) != (complaint.make, complaint.model)
            other_recall = issue.kind == "remedy_concern" and req.action == "link_close" and issue.campno != req.campno
            if (other_vehicle or other_recall) and not reason:
                what = f"{issue.make.title()} {issue.model.title()}" if other_vehicle else \
                    f"recall {display_campno(issue.campno or '')}"
                raise ActionError(f"emerging issue {issue.id} is about the {what}: say why this complaint belongs "
                                  "there")
        else:
            new_issue_title = (req.issue_title or "").strip()
            if not new_issue_title:
                raise ActionError("a new emerging issue needs a title")

    if req.action == "link_close":
        if not req.campno or result.evidence.recall(req.campno) is None:
            raise ActionError("choose a recall that covered this vehicle when the complaint arrived")
        if not message and not reason:
            raise ActionError("add the reply to the owner, or say why there is none")
    if req.action == "request_info" and not message:
        raise ActionError("the message to the owner is empty")
    if req.action == "close_no_action" and not reason:
        raise ActionError("say briefly why this is not a safety defect")

    # ---------- write: all of it, or none of it ----------
    with tickets.transaction():
        if disagrees:
            tickets.log(odino, "disagreed", f"{req.action}: {reason}", result.id)
        issue_id = issue.id if issue else None
        if new_issue_title:
            comp = req.issue_comp or (complaint.comps[0] if complaint.comps else "")
            issue_id = tickets.create_issue(new_issue_title, kind, complaint.make, complaint.model, comp, req.campno)
        if issue_id is not None:
            tickets.add_to_issue(issue_id, odino)

        if req.action == "link_close":
            tickets.set(odino, "resolved", campno=req.campno, issue_id=issue_id)
            detail = display_campno(req.campno) + (f"; flagged to issue {issue_id}" if issue_id else "")
            tickets.log(odino, "linked_recall", detail, result.id)
            if message:
                tickets.log(odino, "reply_drafted", message, result.id)
            else:
                tickets.log(odino, "no_reply", reason, result.id)
        elif req.action == "request_info":
            tickets.set(odino, "waiting")
            tickets.log(odino, "owner_request_drafted", message, result.id)
        elif req.action in ("add_to_issue", "new_issue"):
            tickets.set(odino, "escalated", issue_id=issue_id)
            title = issue.title if issue else new_issue_title
            tickets.log(odino, "escalated", title, result.id)
        elif req.action == "monitor":
            tickets.set(odino, "monitoring")
            tickets.log(odino, "monitoring", reason or "recorded; escalate if more owners report it", result.id)
        elif req.action == "close_no_action":
            tickets.set(odino, "resolved")
            tickets.log(odino, "closed", reason, result.id)
        else:  # reopen
            tickets.set(odino, "suggested")
            tickets.log(odino, "reopened", reason, result.id)
    return tickets.status(odino)
