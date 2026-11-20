"""Start the workspace fresh for a demo: forget what analysts did (ticket status, actions, emerging issues).
AI runs are kept, so tickets keep their suggestions and nothing has to be re-checked.

    uv run python -m app.store.reset
"""
from app.config import get_settings
from app.store.results import Store


def main() -> None:
    con = Store(get_settings().app_db_path).con
    for table in ("tickets", "actions", "issue_complaints", "issues"):
        con.execute(f"DELETE FROM {table}")
    con.execute("DELETE FROM sqlite_sequence WHERE name IN ('issues', 'actions')")
    con.commit()
    print("workspace reset: ticket statuses, actions and emerging issues cleared; AI runs kept")


if __name__ == "__main__":
    main()
