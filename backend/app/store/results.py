"""The app's own database (data/app.db, separate from the read-only NHTSA data): one row per run (the full Result as
JSON, the audit record) and one row per engineer review. Reviews are plain status rows, not paused workflows: an
engineer may answer days later."""
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.models import Result

ReviewAction = Literal["confirm_new", "link_recall", "dismiss", "accept", "override"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
  id TEXT PRIMARY KEY, odino INTEGER, label TEXT, created_at TEXT, outcome TEXT, confidence TEXT, escalate INTEGER,
  source TEXT, body TEXT);
CREATE INDEX IF NOT EXISTS ix_results_odino ON results(odino, created_at);
CREATE INDEX IF NOT EXISTS ix_results_label ON results(label);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, result_id TEXT, action TEXT, campno TEXT, note TEXT, reviewer TEXT,
  created_at TEXT);
"""


class Review(BaseModel):
    result_id: str
    action: ReviewAction
    campno: str | None = None     # for link_recall / override
    note: str = ""
    reviewer: str = "analyst"
    created_at: str = ""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    def save(self, r: Result, label: str = "") -> None:
        """label groups runs: 'queue' for the UI, or an evaluation run name."""
        d = r.decision
        self.con.execute("INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    def add_review(self, review: Review) -> Review:
        review.created_at = datetime.now(UTC).isoformat()
        self.con.execute("INSERT INTO reviews (result_id, action, campno, note, reviewer, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (review.result_id, review.action, review.campno, review.note,
                                                       review.reviewer, review.created_at))
        self.con.commit()
        return review

    def reviews(self, result_ids: list[str] | None = None) -> list[Review]:
        sql, args = "SELECT * FROM reviews", ()
        if result_ids is not None:
            sql += f" WHERE result_id IN ({','.join('?' * len(result_ids))})"
            args = tuple(result_ids)
        return [Review(**{k: row[k] for k in Review.model_fields}) for row in self.con.execute(sql + " ORDER BY id",
                                                                                                args)]
