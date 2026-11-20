# Recall Match

Matches a vehicle safety complaint to known recalls and says one of four things, with every claim traced to a quoted
source: **known recall**, **related but different failure**, **possible new defect (escalate)**, or **needs info**.

Built for an automaker's field-quality analyst, on public NHTSA data (complaints, recalls, investigations).

> Work in progress. Sections below are filled in as each part lands.

## Run it

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run python -m app.data.fetch     # ~380 MB of NHTSA flat files -> data/raw
uv run python -m app.data.ingest    # -> data/nhtsa.db (~550 MB, ~1 min)
uv run pytest
```

## Data

| Source (NHTSA, public domain) | Used for |
|---|---|
| Complaints (`FLAT_CMPL`), received 2020+ | The input "tickets" and similar-complaint counts |
| Recalls (`FLAT_RCL_POST_2010`) | Known issues: defect, consequence, remedy, covered vehicles |
| Investigations (`FLAT_INV`) | Context: what NHTSA was already looking at |

Every evidence query only sees records that existed before the complaint was received (`as_of`), see
`backend/app/data/db.py`.
