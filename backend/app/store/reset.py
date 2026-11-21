"""Start the workspace fresh for a demo: forget what analysts did (ticket status, actions, emerging issues,
questions, typed-in complaints). AI runs on NHTSA complaints are kept. If the workspace has no AI runs yet (a fresh
clone, no model needed), the inbox's stored results are loaded from data/inbox_results.jsonl.gz, so every ticket opens
with its checked suggestion.

    uv run python -m app.store.reset            # tickets open with their stored, already checked suggestion
    uv run python -m app.store.reset --live     # every ticket starts unchecked and is checked live when opened

Evaluation runs (other labels) are never touched. After --live, a plain reset loads the stored results again.
"""
import argparse
import gzip

from app.config import ROOT, get_settings
from app.models import Result
from app.store.results import Store

INBOX_RESULTS = ROOT / "data" / "inbox_results.jsonl.gz"
WORKSPACE_LABEL = "queue"


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the workspace fresh for a demo.")
    parser.add_argument("--live", action="store_true",
                        help="also forget the workspace's AI runs, so tickets are checked live when opened (needs "
                             "the model)")
    args = parser.parse_args()

    store = Store(get_settings().app_db_path)
    con = store.con
    for table in ("tickets", "actions", "issue_complaints", "issues", "questions"):
        con.execute(f"DELETE FROM {table}")
    con.execute("DELETE FROM sqlite_sequence WHERE name IN ('issues', 'actions')")
    con.commit()
    typed = store.forget_typed()
    print(f"workspace reset: ticket statuses, actions, emerging issues, questions and {typed} typed-in complaints "
          "cleared; AI runs on NHTSA complaints kept")

    if args.live:
        cleared = con.execute("DELETE FROM results WHERE label = ?", (WORKSPACE_LABEL,)).rowcount
        con.commit()
        print(f"live demo: {cleared} workspace AI runs cleared; every inbox ticket is checked when first opened")
        return

    if not store.latest(WORKSPACE_LABEL):
        with gzip.open(INBOX_RESULTS, "rt", encoding="utf-8") as lines:
            results = [Result.model_validate_json(line) for line in lines if line.strip()]
        for result in results:
            store.save(result, WORKSPACE_LABEL)
        print(f"loaded {len(results)} stored inbox results from {INBOX_RESULTS.name}")


if __name__ == "__main__":
    main()
