"""The workspace database: on a fresh clone it opens with the inbox's stored results; an existing one is left alone."""
import gzip

from test_workflow import GOOD, go

from app.store.seed import open_store


def stored_results(tmp_path, con, iccu_complaint):
    path = tmp_path / "inbox.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(go(con, iccu_complaint, [GOOD])[0].model_dump_json() + "\n")
    return path


def test_a_fresh_clone_opens_with_the_stored_results(tmp_path, con, iccu_complaint):
    store = open_store(tmp_path / "app.db", stored_results(tmp_path, con, iccu_complaint))
    assert list(store.latest("queue")) == [100]


def test_an_existing_database_is_never_refilled(tmp_path, con, iccu_complaint):
    """A live demo clears the stored runs on purpose; restarting the server must not bring them back."""
    seed = stored_results(tmp_path, con, iccu_complaint)
    store = open_store(tmp_path / "app.db", seed)
    store.con.execute("DELETE FROM results")
    store.con.commit()
    store.con.close()
    assert open_store(tmp_path / "app.db", seed).latest("queue") == {}
