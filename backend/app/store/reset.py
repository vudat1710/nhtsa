"""Start the workspace fresh for a demo: forget what analysts did (ticket status, actions, emerging issues,
questions). AI runs are kept. If the workspace has no AI runs yet (a fresh clone, no model needed), the inbox's
stored results are loaded from data/inbox_results.jsonl.gz, so every ticket opens with its checked suggestion.

    uv run python -m app.store.reset
"""
import gzip

from app.config import ROOT, get_settings
from app.models import Result
from app.store.results import Store

INBOX_RESULTS = ROOT / "data" / "inbox_results.jsonl.gz"


def main() -> None:
    store = Store(get_settings().app_db_path)
    con = store.con
    for table in ("tickets", "actions", "issue_complaints", "issues", "questions"):
        con.execute(f"DELETE FROM {table}")
    con.execute("DELETE FROM sqlite_sequence WHERE name IN ('issues', 'actions')")
    con.commit()
    print("workspace reset: ticket statuses, actions, emerging issues and questions cleared; AI runs kept")
    if not store.latest("queue"):
        with gzip.open(INBOX_RESULTS, "rt", encoding="utf-8") as f:
            results = [Result.model_validate_json(line) for line in f if line.strip()]
        for r in results:
            store.save(r, "queue")
        print(f"loaded {len(results)} stored inbox results from {INBOX_RESULTS.name}")


if __name__ == "__main__":
    main()
