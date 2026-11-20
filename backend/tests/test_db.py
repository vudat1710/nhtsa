import sqlite3

import pytest

from app.data import db
from app.data.ingest import SCHEMA

V = db.Vehicle("HYUNDAI", "IONIQ 5", "2024")


@pytest.fixture
def con(tmp_path):
    path = tmp_path / "t.db"
    w = sqlite3.connect(path)
    w.executescript(SCHEMA)
    complaints = [  # odino, received, crash, fire, injured, comp, text
        (1, "2024-01-10", 0, 0, 0, "ELECTRICAL SYSTEM", "ICCU failed, car lost power on the highway"),
        (2, "2024-06-01", 1, 0, 1, "ELECTRICAL SYSTEM", "Stop vehicle immediately warning, ICCU replaced"),
        (3, "2025-02-01", 0, 0, 0, "ELECTRICAL SYSTEM", "ICCU failed again after the recall repair"),
        (4, "2025-02-01", 0, 0, 0, "AIR BAGS", "airbag light on"),
    ]
    for odino, received, crash, fire, injured, comp, text in complaints:
        w.execute("INSERT INTO complaints (odino, make, model, year, received, crash, fire, injured, text) "
                  "VALUES (?, 'HYUNDAI', 'IONIQ 5', '2024', ?, ?, ?, ?, ?)", (odino, received, crash, fire, injured,
                                                                            text))
        w.execute("INSERT INTO complaint_components VALUES (?, ?, ?)", (odino, comp + ":X", comp))
    w.execute("INSERT INTO complaints_fts(rowid, text) SELECT odino, text FROM complaints")
    for campno, filed, comp in [("24V204000", "2024-03-15", "ELECTRICAL SYSTEM"),
                                ("24V868000", "2024-11-18", "ELECTRICAL SYSTEM"),
                                ("25V001000", "2025-01-05", "AIR BAGS"),
                                ("26V001000", "2026-01-01", "ELECTRICAL SYSTEM")]:
        w.execute("INSERT INTO recalls (campno, filed, defect) VALUES (?, ?, 'ICCU may be damaged')", (campno, filed))
        w.execute("INSERT INTO recall_vehicles VALUES (?, 'HYUNDAI', 'IONIQ 5', '2024', ?, ?)", (campno, comp + ":Y",
                                                                                              comp))
    w.execute("INSERT INTO recall_vehicles VALUES ('24V868000', 'HYUNDAI', 'IONIQ 5', '2024', 'POWER TRAIN:A, B', "
              "'POWER TRAIN')")
    w.execute("INSERT INTO investigations VALUES ('PE23011', '2023-06-08', '2024-04-17', '24V204', 'Loss of power', "
              "'')")
    w.execute("INSERT INTO investigation_vehicles VALUES ('PE23011', 'HYUNDAI', 'IONIQ 5', '2024', 'ELECTRICAL', "
              "'ELECTRICAL SYSTEM')")
    w.execute("INSERT INTO investigation_vehicles VALUES ('PE23011', 'HYUNDAI', 'IONIQ 5', '2024', 'POWER TRAIN', "
              "'POWER TRAIN')")
    w.commit()
    w.close()
    return db.connect(path)


def test_recalls_only_before_as_of_and_same_component_first(con):
    recalls, total = db.recalls_for(con, V, "2025-02-01", ["ELECTRICAL SYSTEM"])
    assert [r["campno"] for r in recalls] == ["24V868000", "24V204000", "25V001000"]  # 26V001000 is in the future
    assert total == 3


def test_recall_groups_components_even_with_commas(con):
    recalls, _ = db.recalls_for(con, V, "2025-02-01", ["ELECTRICAL SYSTEM"])
    r = next(r for r in recalls if r["campno"] == "24V868000")
    assert r["components"] == ["ELECTRICAL SYSTEM:Y", "POWER TRAIN:A, B"]
    assert r["comps"] == ["ELECTRICAL SYSTEM", "POWER TRAIN"]


def test_recall_filed_on_complaint_day_is_not_visible(con):
    recalls, _ = db.recalls_for(con, V, "2024-11-18", ["ELECTRICAL SYSTEM"])
    assert "24V868000" not in [r["campno"] for r in recalls]


def test_complaint_counts_exclude_self_future_and_other_components(con):
    c = db.complaint_counts(con, V, ["ELECTRICAL SYSTEM"], as_of="2025-02-01", exclude=3)
    assert (c["total"], c["crash"], c["injury"], c["first"]) == (2, 1, 1, "2024-01-10")
    assert db.complaint_counts(con, V, ["ELECTRICAL SYSTEM"], "2025-03-01", since="2024-11-18")["total"] == 1


def test_search_is_as_of_and_ignores_fts_syntax(con):
    hits = db.search_complaints(con, V, 'ICCU" OR text:* NEAR(', as_of="2025-01-01")
    assert {h["odino"] for h in hits} == {1, 2}
    assert db.search_complaints(con, V, "!!", as_of="2025-01-01") == []


def test_investigations_before_as_of(con):
    assert [i["action"] for i in db.investigations_for(con, V, "2024-01-01")] == ["PE23011"]
    assert db.investigations_for(con, V, "2023-01-01") == []
