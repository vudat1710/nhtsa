"""Open the workspace database. On a fresh clone (no database yet), every inbox ticket starts with its stored, already
checked AI result (data/inbox_results.jsonl.gz), so the workspace can be tried without a model."""
import gzip
from pathlib import Path

from app.config import ROOT
from app.models import Result
from app.store.results import Store

INBOX_RESULTS = ROOT / "data" / "inbox_results.jsonl.gz"
WORKSPACE_LABEL = "queue"   # the workspace's runs (api/workspace.py LABEL)


def open_store(path: Path, stored_results: Path = INBOX_RESULTS) -> Store:
    """Only a database that does not exist yet is filled: an existing one may have had its runs cleared on purpose
    (a live demo, where every ticket is checked when opened)."""
    fresh = not path.exists()
    store = Store(path)
    if fresh and stored_results.exists():
        with gzip.open(stored_results, "rt", encoding="utf-8") as lines:
            for line in lines:
                if line.strip():
                    store.save(Result.model_validate_json(line), WORKSPACE_LABEL)
    return store
