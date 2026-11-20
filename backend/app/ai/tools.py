"""The one tool the agent may call. Read-only, bounded by as_of, and its results are remembered for the verifier."""
import json
import sqlite3

import agent_framework as af
from pydantic import BaseModel, Field

from app.data import queries
from app.models import Complaint

PREVIEW_CHARS = 600


class SearchArgs(BaseModel):
    query: str = Field(description="a short description of the failure, in your own words")


def search_tool(con: sqlite3.Connection, c: Complaint, found: dict[int, str]) -> af.FunctionTool:
    """Earlier complaints about the same vehicle, received before this one. Full texts go into `found` so the verifier
    can check quotes; the model sees the first PREVIEW_CHARS characters of each."""
    v = queries.Vehicle(c.make, c.model, c.year)

    def search_complaints(query: str) -> str:
        out = []
        for h in queries.search_complaints(con, v, query, c.received, exclude=c.odino):
            text = con.execute("SELECT text FROM complaints WHERE odino = ?", (h["odino"],)).fetchone()[0]
            found[h["odino"]] = text
            out.append({"odino": h["odino"], "received": h["received"], "text": text[:PREVIEW_CHARS]})
        return json.dumps(out or {"result": "no earlier complaints matched"}, ensure_ascii=False)

    return af.tool(search_complaints, name="search_complaints", schema=SearchArgs,
                   description="Search earlier complaints about this same vehicle for a failure description.")
