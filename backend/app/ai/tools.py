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


def search_tool(con: sqlite3.Connection, complaint: Complaint, found: dict[int, str]) -> af.FunctionTool:
    """Earlier complaints about the same vehicle, received before this one. Full texts go into `found` so the verifier
    can check quotes; the model sees the first PREVIEW_CHARS characters of each."""
    vehicle = queries.Vehicle(complaint.make, complaint.model, complaint.year)

    async def search_complaints(query: str) -> str:
        # async on purpose: MAF runs sync tools in worker threads, and the sqlite connection is shared by concurrent
        # cases on the event loop thread (a sync tool here failed with InterfaceError under concurrency)
        hits = queries.search_complaints(con, vehicle, query, complaint.received, exclude=complaint.odino)
        results = []
        for hit in hits:
            odino = hit["odino"]
            text = con.execute("SELECT text FROM complaints WHERE odino = ?", (odino,)).fetchone()[0]
            found[odino] = text
            results.append({"odino": odino, "received": hit["received"], "text": text[:PREVIEW_CHARS]})
        if not results:
            return json.dumps({"result": "no earlier complaints matched"}, ensure_ascii=False)
        return json.dumps(results, ensure_ascii=False)

    return af.tool(search_complaints, name="search_complaints", schema=SearchArgs,
                   description="Search earlier complaints about this same vehicle for a failure description.")
