"""Every AI run, stored whole (data/app.db, separate from the read-only NHTSA data): the audit record behind each
suggestion. What people do with tickets lives in tickets.py."""
import sqlite3
from pathlib import Path

from app.models import Result
from app.store.tickets import Tickets

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
  id TEXT PRIMARY KEY, odino INTEGER, label TEXT, created_at TEXT, outcome TEXT, confidence TEXT, escalate INTEGER,
  source TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS ix_results_odino ON results(odino, created_at);
CREATE INDEX IF NOT EXISTS ix_results_label ON results(label, created_at);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.tickets = Tickets(self.con)

    def save(self, r: Result, label: str = "") -> None:
        """label groups runs: 'queue' for the workspace, or an evaluation run name."""
        d = r.decision
        self.con.execute("INSERT INTO results (id, odino, label, created_at, outcome, confidence, escalate, source, "
                         "body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (r.id, r.complaint.odino, label, r.created_at, d.outcome, d.confidence, int(d.escalate),
                          d.source, r.model_dump_json()))
        self.con.commit()

    def get(self, result_id: str) -> Result | None:
        row = self.con.execute("SELECT body FROM results WHERE id = ?", (result_id,)).fetchone()
        return Result.model_validate_json(row["body"]) if row else None

    def latest(self, label: str) -> dict[int, Result]:
        """Newest result per complaint for a label."""
        rows = self.con.execute(
            """SELECT body FROM results r WHERE label = ? AND created_at = (
                 SELECT max(created_at) FROM results r2 WHERE r2.odino IS r.odino AND r2.label = r.label)""",
            (label,)).fetchall()
        out = [Result.model_validate_json(row["body"]) for row in rows]
        return {r.complaint.odino: r for r in out}

    def runs(self, limit: int = 200) -> list[dict]:
        """Run summaries for the operations portal, newest first."""
        out = []
        for row in self.con.execute("SELECT label, body FROM results ORDER BY created_at DESC LIMIT ?", (limit,)):
            r = Result.model_validate_json(row["body"])
            first = r.attempts[0] if r.attempts else None
            out.append({"id": r.id, "odino": r.complaint.odino, "label": row["label"], "created_at": r.created_at,
                        "vehicle": f"{r.complaint.year} {r.complaint.make} {r.complaint.model}",
                        "outcome": r.decision.outcome, "confidence": r.decision.confidence,
                        "source": r.decision.source, "latency_ms": r.latency_ms, "fault": r.fault,
                        "tokens": sum(a.input_tokens + a.output_tokens for a in r.attempts),
                        "attempts": len(r.attempts), "tool_calls": len(r.tool_calls),
                        "first_issues": [i.code for i in first.issues] if first else []})
        return out
