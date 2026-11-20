# Data card

What the data is, what we did to it, how good the labels are, and what it cannot tell us. Every number here is
reproducible: `python -m app.data.ingest` and `python -m app.eval.build_sets`.

## Sources (NHTSA Office of Defects Investigation, public domain)

| File | What it is | Rows used |
|---|---|---|
| `FLAT_CMPL` | Consumer safety complaints: vehicle, components, dates, crash/fire/injury, free text | 436,710 complaints received 2020-01-01 onward |
| `FLAT_RCL_POST_2010` | Recall campaigns: covered vehicles, defect, consequence, remedy, who influenced it | 15,417 recalls, 248,434 vehicle rows |
| `FLAT_INV` | Defect investigations: vehicles, open/close dates, subject, summary | 4,082 investigations |

## What we changed

- **Text repair only.** 62,742 complaint texts had UTF-8 read as Latin-1 (`â€œ` instead of `“`); repaired so quotes
  can be checked word for word. Nothing else is edited.
- **Top-level component** (`AIR BAGS:FRONTAL` → `AIR BAGS`) for matching.
- **Recall numbers are masked** at intake (`24V868`, `24V-868`, `24V868000` → `[recall no. removed]`) so the answer
  cannot leak in. The same rule is used by the evaluation builder (`backend/app/text.py`).

## No look-ahead

Every evidence query takes the complaint's received date and only returns recalls, investigations and complaints dated
strictly before it (`backend/app/data/db.py`, tested in `tests/test_db.py`). A recall filed on the same day is not
visible: NHTSA publishes recalls after the filing date.

## Evaluation sets (frozen, `data/eval/`)

| Set | Test / dev | Ground truth | Label quality (hand-checked) |
|---|---|---|---|
| **A: known recall** | 300 / 100 | Owner cited exactly one recall that covers the vehicle and was filed before the complaint; at least 200 characters after masking; not about parts availability | 14 of 15 sampled are fair matching tests; 1 had no symptom (filter tightened, set rebuilt) |
| **B: no recall yet** | 242 / 50 | No recall on the vehicle + component at the time; one filed within 365 days after and sharing 3+ distinctive words; vehicle has other (distractor) recalls; text does not mention "recall" | "No matching recall at the time" held for 20 of 20. The later recall was the same failure in ~13 of 20 (65%), unclear in 3, different in 4 |
| **C: stress** | 26 / 0 | Real complaints with one change: unknown year (5), unknown component (5), injected instruction (6), too-short text (5), vehicle with no recalls (5) | By construction |

Set sizes: A pool 14,704 → 400 sampled; B pool 3,514 → 683 with shared wording → 292 after a cap of 3 complaints per
recall (so one big recall cannot dominate).

Facts about the test sets: A has a median of 6 candidate recalls per complaint (90th percentile 15); for 14% the right
recall is filed under a different component than the owner chose. B's later recall came a median of 137 days after the
complaint.

Baseline (pick the candidate recall with the same component; from the profiling run on all 21,848 clean labels): right
46%, ambiguous 35%, right recall under a different component 21%.

## Evaluation results and how to read them

- **Set A measures agreement with the owner, not accuracy.** Owners sometimes cite the wrong recall (e.g. a "failed
  fast charge" against a "battery overheats while fast charging" recall). A fixed random sample of 30 of the AI's 138
  disagreements was read case by case (`data/eval/adjudication/`): AI right 12, owner right 7, unclear 11. All 7
  owner-right cases describe no failure, only trouble getting the recall repair (a product gap, not a matching error).
- **Set B is easy for the rules baseline by construction** (it requires no recall on the owner's component, and the
  baseline only looks at that component), so B shows whether the AI over-claims on *other* components. Of its 13
  "known recall" claims, 6 were judged right (an existing recall on another component really fits), 3 wrong, 4 unclear.
- **Prompt changes were made on the dev split only** (v1 → v2 negation rule, v2 → v3 "symptoms, not causes"); test sets
  were run once with v3. One rule bug found on test set C was fixed and the stored answers re-decided (5 changed).
- A replay attempt at 12:13 was discarded: a recording-key bug made every tool-using case miss (fixed, regression test).

## What the data cannot tell us (limitations)

- **Selection bias in A.** Labels exist only where the owner already knew their recall. Masking removes the number but
  every text still says "recall". Complaints from owners who don't know about a recall have no labels.
- **B's "would have caught it early" is noisy** (~65% same failure). B is reliable for "must not claim a known recall";
  lead time is reported only as an indicative number.
- **No repair records.** We cannot tell whether a car was repaired under a recall, so "complaint after the remedy" means
  "the fix may not hold, or the car was not repaired", never which one.
- **History windows.** Complaints from 2020 only (similar-complaint counts start then); recalls from 2010 only (older
  recalls on old vehicles are invisible).
- **Owner-chosen components are noisy** ("UNKNOWN OR OTHER", or a different component than the recall's).
- **Hotline transcripts** (`TL*`, written by NHTSA staff) are kept in the database but excluded from A and B.
