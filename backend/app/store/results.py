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

    def save(self, result: Result, label: str = "") -> None:
        """label groups runs: 'queue' for the workspace, or an evaluation run name."""
        decision = result.decision
        self.con.execute("INSERT INTO results (id, odino, label, created_at, outcome, confidence, escalate, source, "
                         "body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (result.id, result.complaint.odino, label, result.created_at, decision.outcome,
                          decision.confidence, int(decision.escalate), decision.source, result.model_dump_json()))
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
        results = [Result.model_validate_json(row["body"]) for row in rows]
        return {result.complaint.odino: result for result in results}

    def runs(self, limit: int = 200) -> list[dict]:
        """Run summaries for the operations portal, newest first."""
        out = []
        for row in self.con.execute("SELECT label, body FROM results ORDER BY created_at DESC LIMIT ?", (limit,)):
            result = Result.model_validate_json(row["body"])
            complaint = result.complaint
            decision = result.decision
            tokens = sum(attempt.input_tokens + attempt.output_tokens for attempt in result.attempts)
            # What the verifier flagged in the AI's first answer, if there was one.
            first_issues = []
            if result.attempts:
                first_issues = [issue.code for issue in result.attempts[0].issues]
            out.append({"id": result.id,
                        "odino": complaint.odino,
                        "label": row["label"],
                        "created_at": result.created_at,
                        "vehicle": f"{complaint.year} {complaint.make} {complaint.model}",
                        "outcome": decision.outcome,
                        "confidence": decision.confidence,
                        "source": decision.source,
                        "latency_ms": result.latency_ms,
                        "fault": result.fault,
                        "tokens": tokens,
                        "attempts": len(result.attempts),
                        "tool_calls": len(result.tool_calls),
                        "first_issues": first_issues})
        return out
