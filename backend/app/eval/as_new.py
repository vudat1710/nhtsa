"""Is a stored complaint judged exactly as a brand-new one? (No look-ahead, no self-leak.)

Every complaint in the test sets and the inbox is gathered twice: as stored in the database, and as a brand-new
complaint with no id. Evidence must be identical, and a search with the complaint's own words must return the same
earlier complaints with or without excluding its id, and never the complaint itself. No model needed.

    uv run python -m app.eval.as_new          (a few minutes: two evidence gatherings per complaint)
"""
import gzip
import json
from datetime import datetime

from app.config import ROOT
from app.data import queries
from app.eval.run import EVAL
from app.models import Complaint, Result
from app.pipeline.evidence import gather
from app.pipeline.intake import intake

SOURCES = [EVAL / "results" / "20261121-2211-abc-test-ai.jsonl.gz", ROOT / "data" / "inbox_results.jsonl.gz"]


def complaints() -> list[Complaint]:
    out = []
    for path in SOURCES:
        with gzip.open(path, "rt", encoding="utf-8") as lines:
            out += [Result.model_validate_json(line).complaint for line in lines if line.strip()]
    return out


def main() -> None:
    con = queries.connect()
    cases = complaints()
    same_evidence = same_search = found_itself = 0
    for complaint in cases:
        fresh = complaint.model_copy(update={"odino": None})
        stored_evidence = gather(con, complaint, intake(complaint)).model_dump_json()
        fresh_evidence = gather(con, fresh, intake(fresh)).model_dump_json()
        same_evidence += stored_evidence == fresh_evidence
        vehicle = queries.Vehicle(complaint.make, complaint.model, complaint.year)
        query = " ".join(complaint.text.split()[:12])  # the complaint's own words: the most likely way to find itself
        excluded = queries.search_complaints(con, vehicle, query, complaint.received, exclude=complaint.odino)
        not_excluded = queries.search_complaints(con, vehicle, query, complaint.received, exclude=None)
        same_search += [hit["odino"] for hit in excluded] == [hit["odino"] for hit in not_excluded]
        found_itself += any(hit["odino"] == complaint.odino for hit in not_excluded)
    report = {"name": f"as_new-{datetime.now():%Y%m%d-%H%M}", "set": "as_new", "split": "test", "mode": "code",
              "cases": len(cases), "evidence_identical": same_evidence, "search_identical": same_search,
              "found_itself": found_itself}
    (EVAL / "reports" / f"{report['name']}.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
