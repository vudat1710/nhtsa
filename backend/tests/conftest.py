"""A tiny NHTSA world (same schema as the real database) used by every test:

    2024 HYUNDAI IONIQ 5
      recalls  24V204000  2024-03-15  ELECTRICAL SYSTEM  ICCU loss of drive power; remedy: "replaced by ... 24V-868"
               24V868000  2024-11-18  ELECTRICAL SYSTEM  same failure, the current remedy (+ a component with a comma)
               25V001000  2025-01-05  AIR BAGS           seat sensor: air bag deploys when it should be suppressed
               26V001000  2026-01-01  ELECTRICAL SYSTEM  in the future for every test complaint (must stay invisible)
      complaints 1-9 (2024-01 .. 2025-02) about the ICCU, 4 is about the air bag light
      investigation PE23011 opened 2023-06-08
"""
import sqlite3

import pytest

from app.data import queries
from app.data.ingest import SCHEMA
from app.models import Complaint

V = queries.Vehicle("HYUNDAI", "IONIQ 5", "2024")
ICCU = ("The Integrated Charging Control Unit (ICCU) may become damaged and stop charging the 12-volt battery, which "
        "can result in a loss of drive power.")
COMPLAINTS = [  # odino, received, crash, fire, injured, comp, text
    (1, "2024-01-10", 0, 0, 0, "ELECTRICAL SYSTEM", "ICCU failed, car lost power on the highway"),
    (2, "2024-06-01", 1, 0, 1, "ELECTRICAL SYSTEM", "Stop vehicle immediately warning, ICCU replaced"),
    (3, "2025-02-01", 0, 0, 0, "ELECTRICAL SYSTEM",
     "ICCU failed again after the recall repair, the car lost all drive power on the freeway"),
    (4, "2025-02-01", 0, 0, 0, "AIR BAGS", "The airbag warning light came on and stays on, even after restarting"),
    *[(5 + i, f"2024-12-0{i + 1}", 0, 0, 0, "ELECTRICAL SYSTEM", "power system failure, ICCU replaced by dealer")
      for i in range(5)],
]
RECALLS = [  # campno, filed, comp, defect, consequence, remedy
    ("24V204000", "2024-03-15", "ELECTRICAL SYSTEM", ICCU, "A loss of drive power increases the risk of a crash.",
     "This recall is replaced by NHTSA recall number 24V-868. Dealers will inspect and replace the ICCU."),
    ("24V868000", "2024-11-18", "ELECTRICAL SYSTEM", ICCU, "A loss of drive power increases the risk of a crash.",
     "Dealers will inspect and replace the ICCU and its fuse, and update the ICCU software."),
    ("25V001000", "2025-01-05", "AIR BAGS",
     "The front passenger seat weight sensor may crack and short circuit, failing to suppress the air bag as intended.",
     "An air bag that deploys unintentionally during a crash can increase the risk of injury.",
     "Dealers will replace the seat weight sensor."),
    ("26V001000", "2026-01-01", "ELECTRICAL SYSTEM", "A future recall.", "Future.", "Future."),
]


@pytest.fixture
def con(tmp_path):
    path = tmp_path / "t.db"
    w = sqlite3.connect(path)
    w.executescript(SCHEMA)
    for odino, received, crash, fire, injured, comp, text in COMPLAINTS:
        w.execute("INSERT INTO complaints (odino, make, model, year, received, crash, fire, injured, source, text) "
                  "VALUES (?, 'HYUNDAI', 'IONIQ 5', '2024', ?, ?, ?, ?, 'owner', ?)",
                  (odino, received, crash, fire, injured, text))
        w.execute("INSERT INTO complaint_components VALUES (?, ?, ?)", (odino, comp + ":X", comp))
    w.execute("INSERT INTO complaints_fts(rowid, text) SELECT odino, text FROM complaints")
    for campno, filed, comp, defect, consequence, remedy in RECALLS:
        w.execute("INSERT INTO recalls (campno, filed, influenced_by, defect, consequence, remedy) "
                  "VALUES (?, ?, 'ODI', ?, ?, ?)", (campno, filed, defect, consequence, remedy))
        w.execute("INSERT INTO recall_vehicles VALUES (?, 'HYUNDAI', 'IONIQ 5', '2024', ?, ?)", (campno, comp + ":Y",
                                                                                              comp))
    w.execute("INSERT INTO recall_vehicles VALUES ('24V868000', 'HYUNDAI', 'IONIQ 5', '2024', 'POWER TRAIN:A, B', "
              "'POWER TRAIN')")
    w.execute("INSERT INTO investigations VALUES ('PE23011', '2023-06-08', '2024-04-17', '24V204', 'Loss of power', "
              "'')")
    for comp in ("ELECTRICAL SYSTEM", "POWER TRAIN"):
        w.execute("INSERT INTO investigation_vehicles VALUES ('PE23011', 'HYUNDAI', 'IONIQ 5', '2024', ?, ?)",
                  (comp, comp))
    w.commit()
    w.close()
    return queries.connect(path)


@pytest.fixture
def iccu_complaint() -> Complaint:
    return Complaint(odino=100, make="HYUNDAI", model="IONIQ 5", year="2024", received="2025-03-01",
                     components=["ELECTRICAL SYSTEM:ICCU"],
                     text="Car said Stop Vehicle Immediately and would not accelerate. The ICCU failed at 16,000 miles."
                          " Recall 24V-868 was done in January.")
