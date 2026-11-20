# Data model

Two SQLite files, kept apart on purpose:

| File | Written by | What it holds |
|---|---|---|
| `data/nhtsa.db` (~550 MB) | `python -m app.data.ingest`, once | NHTSA's public complaints, recalls and investigations. The app opens it **read-only**. |
| `data/app.db` | the app, at run time | Every AI run (the audit record) and what analysts do with tickets. |

There are no foreign-key constraints across the two files: `app.db` refers to NHTSA records by their public ids
(`odino` for a complaint, `campno` for a recall). Dashed lines below are such references or query-time joins; solid
lines are keys within one file. Samples of every table: `uv run python -m app.data.report` → `docs/data_report.html`
(section 3 and 5).

## nhtsa.db: what was known, and when

```mermaid
%% diagram: nhtsa
erDiagram
    complaints ||--|{ complaint_components : "odino"
    complaints ||--|| complaints_fts : "rowid = odino"
    recalls ||--|{ recall_vehicles : "campno"
    investigations ||--|{ investigation_vehicles : "action"
    investigations }o..o| recalls : "campno (when it matches)"
    complaints }o..o{ recall_vehicles : "candidates: same make+model+year, filed before received"
    complaints }o..o{ investigation_vehicles : "same make+model+year, opened before received"

    complaints {
        INTEGER odino PK "NHTSA complaint id"
        TEXT make
        TEXT model
        TEXT year "9999 = unknown"
        TEXT received "ISO date: the as_of of every query"
        TEXT failed
        INTEGER crash "0 or 1"
        INTEGER fire "0 or 1"
        INTEGER injured
        INTEGER deaths
        REAL miles
        TEXT state
        TEXT source "hotline if cmpl_type = EVOQ, else owner"
        TEXT cmpl_type "NHTSA's CMPL_TYPE, as published"
        INTEGER vehicles "vehicles the complaint named (1.1% more than 1)"
        TEXT text "as published (encoding repaired)"
    }
    complaint_components {
        INTEGER odino FK
        TEXT component "AIR BAGS:FRONTAL"
        TEXT comp "AIR BAGS (top level, used for matching)"
    }
    complaints_fts {
        TEXT text "FTS5 index over complaints.text"
    }
    recalls {
        TEXT campno PK "24V868000"
        TEXT filed "ISO date"
        TEXT influenced_by
        TEXT manufacturer
        REAL units "vehicles affected"
        TEXT defect
        TEXT consequence
        TEXT remedy
    }
    recall_vehicles {
        TEXT campno FK
        TEXT make
        TEXT model
        TEXT year
        TEXT component
        TEXT comp
    }
    investigations {
        TEXT action PK "PE23011"
        TEXT opened
        TEXT closed
        TEXT campno "loose link, often another format"
        TEXT subject
        TEXT summary
    }
    investigation_vehicles {
        TEXT action FK
        TEXT make
        TEXT model
        TEXT year
        TEXT component
        TEXT comp
    }
```

- **One row per complaint, recall or investigation**, plus one row per component (complaints: only the components of
  the complaint's own, first-named vehicle) or per covered make × model × year × component (recalls, investigations).
  Field meanings follow NHTSA's descriptions in `data/raw/CMPL.txt`, `RCL.txt`, `INV.txt`. Component names can contain commas, so grouping happens
  in Python, not with SQL `group_concat`.
- **The dashed joins are the core of the product.** A complaint's candidate recalls are the `recall_vehicles` rows with
  the same make, model and year whose recall was filed *strictly before* the complaint was received
  (`queries.recalls_for`). Every evidence query has that `as_of` rule; it lives only in `app/data/queries.py`.
- **Indexes:** `complaints(make, model, year, received)`, `complaint_components(odino)`,
  `recall_vehicles(make, model, year)` and `(campno)`, `investigation_vehicles(make, model, year)`.

## app.db: what the system did, and what people did with it

```mermaid
%% diagram: app
erDiagram
    results }o..|| NHTSA_COMPLAINT : "odino"
    tickets |o..|| NHTSA_COMPLAINT : "odino"
    tickets }o..o| NHTSA_RECALL : "campno: linked recall"
    tickets }o--o| issues : "issue_id: escalated to"
    issues ||--|{ issue_complaints : "id = issue_id"
    issue_complaints }o..|| NHTSA_COMPLAINT : "odino"
    issues }o..o| NHTSA_RECALL : "campno: remedy concern"
    actions }o..|| NHTSA_COMPLAINT : "odino"
    actions }o--o| results : "result_id: the run the analyst saw"
    questions }o..|| NHTSA_COMPLAINT : "odino"
    questions }o--o| results : "body.result_id"

    results {
        TEXT id PK "12 hex chars"
        INTEGER odino "null if typed in"
        TEXT label "queue, ops or an eval run"
        TEXT created_at
        TEXT outcome "copy of body field"
        TEXT confidence
        INTEGER escalate
        TEXT source "how the answer was made"
        TEXT body "the whole Result as JSON"
    }
    tickets {
        INTEGER odino PK
        TEXT status "no row = new"
        TEXT campno
        INTEGER issue_id FK
        TEXT updated_at
    }
    issues {
        INTEGER id PK
        TEXT title
        TEXT kind "new_defect, remedy_concern"
        TEXT make
        TEXT model
        TEXT comp
        TEXT campno
        TEXT status "open"
        TEXT created_at
    }
    issue_complaints {
        INTEGER issue_id PK
        INTEGER odino PK
        TEXT added_at
    }
    actions {
        INTEGER id PK
        INTEGER odino
        TEXT action "what was done"
        TEXT detail "recall, message or reason"
        TEXT result_id FK
        TEXT by
        TEXT at
    }
    questions {
        INTEGER id PK
        INTEGER odino
        TEXT body "a follow-up Turn as JSON"
        TEXT at
    }
```

- **`results` is append-only**: every check (workspace, ops drill, evaluation) adds a row; the newest row per complaint
  and label is what the analyst sees. The listing columns are copies of fields in `body` so the ops portal can list
  runs without parsing JSON.
- **Values:** `results.source` is `ai_verified`, `ai_repaired`, `fallback` or `rules`; `tickets.status` is `waiting`,
  `resolved`, `escalated` or `monitoring` (no row = new); `actions.action` is `linked_recall`, `replied_to_owner`,
  `asked_owner`, `escalated`, `monitoring`, `closed` or `disagreed`.
- **People's work is separate from the AI's**: `tickets`, `issues`, `issue_complaints`, `actions` and `questions` are
  cleared by `python -m app.store.reset`; AI runs are kept. `actions` is an append-only log, including every
  "disagreed" with its reason: the feedback signal.

## results.body: one run, end to end

The `body` column holds a `Result` (`app/models.py`), in the order a complaint flows through the pipeline:

```mermaid
%% diagram: result
classDiagram
    direction TB
    class Result {
        id
        created_at
        latency_ms
        model
        fault
        steps[]
        tool_calls[]
    }
    class Complaint {
        odino
        make, model, year
        received
        crash, fire, injured
        components[]
        text
    }
    class Intake {
        text
        masked
        flags[]
    }
    class Evidence {
        recalls_total
    }
    class RecallItem {
        campno, filed
        units
        components[], comps[]
        defect
        consequence
        remedy
        same_component
        replaced_by
        complaints_since
        model_years[]
    }
    class Stats {
        total
        crash, fire, injury
        first, last
        last_12_months
    }
    class InvestigationItem {
        action, opened
        campno, subject
    }
    class Judgment {
        proposed
        summary
        questions[]
    }
    class RecallCheck {
        campno
        verdict
        complaint_quote
        recall_quote
        reason
    }
    class SimilarComplaint {
        odino
        quote
    }
    class Attempt {
        n
        raw, error
        input_tokens
        output_tokens
    }
    class Issue {
        code
        message
    }
    class Decision {
        outcome
        confidence
        campno
        escalate
        source
        flags[]
        reasons[]
    }
    Result *-- Complaint : input
    Result *-- Intake : 1 code
    Result *-- Evidence : 2 code
    Evidence *-- "0..15" RecallItem
    Evidence *-- Stats
    Evidence *-- "0..*" InvestigationItem
    Result *-- "0..1" Judgment : 3 AI, if verified
    Judgment *-- "0..*" RecallCheck
    Judgment *-- "0..*" SimilarComplaint
    Result *-- "0..2" Attempt : each model answer
    Attempt *-- "0..*" Issue : 4 verifier
    Result *-- Decision : 5 rules
```

Everything an analyst or reviewer sees (the suggestion, the "how the agent investigated" trail, the ops audit page,
the evaluation scores) is computed from this one stored record, so it can be re-shown, re-scored with changed rules
(`app/eval/rescore.py`) or re-checked (`app/eval/trajectory.py`) without calling the model again.
