"""What the analyst does with a ticket (data/app.db, next to the runs): ticket status, emerging issues, and an action
log. Kept apart from the AI runs: runs are the audit record of the system, tickets are the work of people."""
import sqlite3
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

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
CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, odino INTEGER, body TEXT, at TEXT);
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

    def status(self, odino: int) -> dict:
        row = self.con.execute("SELECT * FROM tickets WHERE odino = ?", (odino,)).fetchone()
        return dict(row) if row else {"odino": odino, "status": "new", "campno": None, "issue_id": None,
                                      "updated_at": None}

    def statuses(self) -> dict[int, dict]:
        return {r["odino"]: dict(r) for r in self.con.execute("SELECT * FROM tickets")}

    def set(self, odino: int, status: TicketStatus, campno: str | None = None, issue_id: int | None = None) -> None:
        self.con.execute("INSERT OR REPLACE INTO tickets VALUES (?, ?, ?, ?, ?)",
                         (odino, status, campno, issue_id, now()))
        self.con.commit()

    def log(self, odino: int, action: str, detail: str, result_id: str | None, by: str = "analyst") -> None:
        self.con.execute("INSERT INTO actions (odino, action, detail, result_id, by, at) VALUES (?, ?, ?, ?, ?, ?)",
                         (odino, action, detail, result_id, by, now()))
        self.con.commit()

    def history(self, odino: int) -> list[Action]:
        rows = self.con.execute("SELECT * FROM actions WHERE odino = ? ORDER BY id", (odino,))
        return [Action(**{k: r[k] for k in Action.model_fields}) for r in rows]

    # ---------- follow-up questions (ask/service.py Turn, stored as JSON) ----------

    def add_question(self, odino: int, turn_json: str) -> None:
        self.con.execute("INSERT INTO questions (odino, body, at) VALUES (?, ?, ?)", (odino, turn_json, now()))
        self.con.commit()

    def questions(self, odino: int) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT body FROM questions WHERE odino = ? ORDER BY id", (odino,))]

    # ---------- emerging issues ----------

    def create_issue(self, title: str, kind: IssueKind, make: str, model: str, comp: str,
                     campno: str | None) -> int:
        cur = self.con.execute("INSERT INTO issues (title, kind, make, model, comp, campno, status, created_at) "
                               "VALUES (?, ?, ?, ?, ?, ?, 'open', ?)", (title, kind, make, model, comp, campno, now()))
        self.con.commit()
        return cur.lastrowid

    def add_to_issue(self, issue_id: int, odino: int) -> None:
        self.con.execute("INSERT OR IGNORE INTO issue_complaints VALUES (?, ?, ?)", (issue_id, odino, now()))
        self.con.commit()

    def issue(self, issue_id: int) -> Issue | None:
        row = self.con.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if row is None:
            return None
        odinos = [r[0] for r in self.con.execute(
            "SELECT odino FROM issue_complaints WHERE issue_id = ? ORDER BY added_at", (issue_id,))]
        return Issue(**dict(row), complaints=odinos)

    def issues(self) -> list[Issue]:
        return [self.issue(r[0]) for r in self.con.execute("SELECT id FROM issues ORDER BY id DESC")]

    def matching_issue(self, kind: IssueKind, make: str, model: str, comp: str, campno: str | None) -> Issue | None:
        """An open issue this complaint belongs to: same recall (remedy concern) or same model + part (new defect)."""
        if kind == "remedy_concern":
            row = self.con.execute("SELECT id FROM issues WHERE kind = ? AND campno = ? AND status = 'open'",
                                   (kind, campno)).fetchone()
        else:
            row = self.con.execute("SELECT id FROM issues WHERE kind = ? AND make = ? AND model = ? AND comp = ? "
                                   "AND status = 'open'", (kind, make, model, comp)).fetchone()
        return self.issue(row[0]) if row else None
