"""What the analyst does with a ticket (data/app.db, next to the runs): ticket status, emerging issues, an action log,
and complaints typed in by an analyst. Kept apart from the AI runs: runs are the audit record of the system, tickets
are the work of people.

Status, action log and emerging issues are written together inside `transaction()`: all of an action, or none of it."""
import sqlite3
import threading
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from app.models import Complaint

TicketStatus = Literal["new", "suggested", "waiting", "resolved", "escalated", "monitoring"]
IssueKind = Literal["new_defect", "remedy_concern"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (odino INTEGER PRIMARY KEY, status TEXT, campno TEXT, issue_id INTEGER,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, kind TEXT, make TEXT, model TEXT,
  comp TEXT, campno TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS issue_complaints (issue_id INTEGER, odino INTEGER, added_at TEXT,
  PRIMARY KEY (issue_id, odino));
CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY AUTOINCREMENT, odino INTEGER, action TEXT, detail TEXT,
  result_id TEXT, by TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS typed_complaints (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT, at TEXT);
"""


class Issue(BaseModel):
    id: int
    title: str
    kind: IssueKind
    make: str
    model: str
    comp: str
    campno: str | None
    status: str
    created_at: str
    complaints: list[int] = []


class Action(BaseModel):
    odino: int
    action: str
    detail: str
    result_id: str | None
    by: str
    at: str


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Tickets:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.con.executescript(SCHEMA)
        # The API serves requests on several threads over this one connection: one action's writes at a time.
        self.lock = threading.RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Everything written inside is committed together, or rolled back together if anything fails."""
        with self.lock, self.con:
            yield

    def status(self, odino: int) -> dict:
        row = self.con.execute("SELECT * FROM tickets WHERE odino = ?", (odino,)).fetchone()
        if row:
            return dict(row)
        # Nobody has acted on this ticket yet.
        return {"odino": odino, "status": "new", "campno": None, "issue_id": None, "updated_at": None}

    def statuses(self) -> dict[int, dict]:
        return {row["odino"]: dict(row) for row in self.con.execute("SELECT * FROM tickets")}

    # set, log, create_issue and add_to_issue don't commit: call them inside transaction().

    def set(self, odino: int, status: TicketStatus, campno: str | None = None, issue_id: int | None = None) -> None:
        self.con.execute("INSERT OR REPLACE INTO tickets VALUES (?, ?, ?, ?, ?)",
                         (odino, status, campno, issue_id, now()))

    def log(self, odino: int, action: str, detail: str, result_id: str | None, by: str = "analyst") -> None:
        self.con.execute("INSERT INTO actions (odino, action, detail, result_id, by, at) VALUES (?, ?, ?, ?, ?, ?)",
                         (odino, action, detail, result_id, by, now()))

    def last_action(self, odino: int, kinds: Collection[str]) -> dict | None:
        """The ticket's latest log entry of one of these kinds."""
        marks = ",".join("?" * len(kinds))
        row = self.con.execute(f"SELECT * FROM actions WHERE odino = ? AND action IN ({marks}) "
                               "ORDER BY id DESC LIMIT 1", (odino, *kinds)).fetchone()
        return dict(row) if row else None

    def history(self, odino: int) -> list[Action]:
        rows = self.con.execute("SELECT * FROM actions WHERE odino = ? ORDER BY id", (odino,))
        history = []
        for row in rows:
            fields = {name: row[name] for name in Action.model_fields}  # leaves out the table's own id column
            history.append(Action(**fields))
        return history

    # ---------- complaints typed in by an analyst ----------
    # Their ticket number is negative (-1, -2, ...), so it can never collide with an NHTSA complaint id (ODINO).

    def add_typed(self, complaint: Complaint) -> int:
        cur = self.con.execute("INSERT INTO typed_complaints (body, at) VALUES ('', ?)", (now(),))
        odino = -cur.lastrowid
        self.con.execute("UPDATE typed_complaints SET body = ? WHERE id = ?",
                         (complaint.model_copy(update={"odino": odino}).model_dump_json(), cur.lastrowid))
        self.con.commit()
        return odino

    def typed(self, odino: int) -> Complaint | None:
        row = self.con.execute("SELECT body FROM typed_complaints WHERE id = ?", (-odino,)).fetchone()
        return Complaint.model_validate_json(row[0]) if row else None

    def typed_ids(self) -> list[int]:
        """Newest first."""
        return [-row[0] for row in self.con.execute("SELECT id FROM typed_complaints ORDER BY id DESC")]

    # ---------- emerging issues ----------

    def create_issue(self, title: str, kind: IssueKind, make: str, model: str, comp: str,
                     campno: str | None) -> int:
        cur = self.con.execute("INSERT INTO issues (title, kind, make, model, comp, campno, status, created_at) "
                               "VALUES (?, ?, ?, ?, ?, ?, 'open', ?)", (title, kind, make, model, comp, campno, now()))
        return cur.lastrowid

    def add_to_issue(self, issue_id: int, odino: int) -> None:
        self.con.execute("INSERT OR IGNORE INTO issue_complaints VALUES (?, ?, ?)", (issue_id, odino, now()))

    def issue(self, issue_id: int) -> Issue | None:
        row = self.con.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            return None
        rows = self.con.execute("SELECT odino FROM issue_complaints WHERE issue_id = ? ORDER BY added_at", (issue_id,))
        odinos = [row[0] for row in rows]
        return Issue(**dict(row), complaints=odinos)

    def issues(self) -> list[Issue]:
        rows = self.con.execute("SELECT id FROM issues ORDER BY id DESC")
        return [self.issue(row[0]) for row in rows]

    def matching_issue(self, kind: IssueKind, make: str, model: str, comp: str, campno: str | None) -> Issue | None:
        """An open issue this complaint belongs to: same recall (remedy concern) or same model + part (new defect)."""
        if kind == "remedy_concern":
            row = self.con.execute("SELECT id FROM issues WHERE kind = ? AND campno = ? AND status = 'open'",
                                   (kind, campno)).fetchone()
        else:
            row = self.con.execute("SELECT id FROM issues WHERE kind = ? AND make = ? AND model = ? AND comp = ? "
                                   "AND status = 'open'", (kind, make, model, comp)).fetchone()
        return self.issue(row[0]) if row else None
