# Data card

What the data is, what we did to it, how good the labels are, and what it cannot tell us. Field positions and
meanings follow NHTSA's own descriptions, kept in [docs/nhtsa/](nhtsa/) (`CMPL.txt`, `RCL.txt`, `INV.txt`, as published
next to the files). NHTSA's import instructions load each file as one flat table; the split into two tables per file
(one row per record, one row per vehicle/component line) is ours, and follows a check of every field: fields that are
the same on every line of a record go in the record's table. Every number here is reproducible:
`python -m app.data.ingest` (database) and `python -m app.eval.build_sets` (evaluation sets; the build gives identical
sets on every run).

## Sources (NHTSA Office of Defects Investigation, public domain)

| File | What it is | Used |
|---|---|---|
| `FLAT_CMPL` | Complaints: one line per complaint × product × component (51 fields); vehicle or product, dates, crash/fire/injury, free text, how it reached NHTSA (`CMPL_TYPE`), product type (`PROD_TYPE`) | 436,710 complaints received 2020-01-01 onward; 16 of 51 fields read |
| `FLAT_RCL_PRE_2010` + `FLAT_RCL_POST_2010` | Recall campaigns, 1966 on: one line per recall × covered vehicle/product × component (29 fields, same in both files; no recall is in both) | 30,476 recalls (15,059 + 15,417), 330,144 lines, 196,174 distinct vehicle/component rows |
| `FLAT_INV` | Defect investigations: one line per investigation × vehicle (11 fields) | 4,082 investigations that name a vehicle |

Every raw line is read (2,268,452 complaint lines, 81,710 + 248,434 recall lines, 154,503 investigation lines; 6
blank lines in the pre-2010 recalls are skipped). Fields are tab-separated and not actually quoted.

## What we changed, and why

- **Text repair only.** 62,742 complaint texts had UTF-8 read as Latin-1 (`â€œ` instead of `“`); repaired so quotes
  can be checked word for word. Nothing else in any text is edited.
- **Who wrote the complaint** comes from NHTSA's documented `CMPL_TYPE` (`complaints.cmpl_type`, kept as published):
  `EVOQ` = taken by NHTSA's hotline, so `complaints.source = 'hotline'` (95,658); everything else (website, app,
  letters) is `'owner'` (341,052). Hotline complaints are written up by NHTSA staff ("The contact owns a 2012 Ford
  Mustang. The contact stated…"), not in the owner's words.
- **The vehicle a complaint is judged on** comes from NHTSA's documented `PROD_TYPE` (V vehicle, T tires, E equipment,
  C child restraint): a complaint has one line per product it names, each with its own make/model/year and components.
  A complaint is judged on its vehicle line (`complaints.prod_type = 'V'`: 434,996) with only that line's components;
  6,483 of those also name tires, equipment or a child seat (`complaints.other_products`). No complaint names two
  vehicles. 1,714 complaints name only a non-vehicle product (child seat 895, equipment 811, tire 2, blank 6) and keep
  that product as make/model.
- **Recall type and advisories** are kept as published: `recalls.recall_type` (`RCLTYPECD`: V 26,493, E 2,877, T 791,
  C 251; also `I` 53 and `X` 11, which `RCL.txt` does not document), `do_not_drive` (213 recalls) and `park_outside`
  (107). They are stored, not yet used by the product.
- **Build dates** (`BGMAN`/`ENDMAN`) are stored per vehicle line (`recall_vehicles.built_from`, `built_to`): 70% of
  vehicle recalls publish them on at least one line (62% of those filed since 2010). A recall usually covers only cars
  built between them, so a model year does not prove a car is covered; only the VIN does, and the data has none. The
  product shows the range for the complaint's model year (earliest start, latest end over the recall's lines) and
  says "may be covered, confirm with the VIN". 271 lines are published with the end before the start; those are
  treated as unpublished. The judge does not see build dates (the evaluated input is unchanged).
- **The recall an investigation led to is per vehicle line** (`investigation_vehicles.campno`): one investigation can
  cover several manufacturers and lead to a recall from each (232 investigations do); the system shows the recall on
  the complaint's own vehicle line. `INV.txt` documents CAMPNO as the 9-character recall number that links to the
  recalls file, but 290 values are published without the trailing `000` (`24V204`); ingest completes them
  (`24V204000`), after which 2,525 of 2,549 distinct values match a recall. The rest are kept as published (23
  sub-numbers such as `02V027001` and one number not in the recall files).
- **Investigations without a vehicle are left out**: 1,278 (mostly 1970s–80s defect petitions) name no vehicle and
  could never match a complaint.
- **Top-level component** (`AIR BAGS:FRONTAL` → `AIR BAGS`) for matching. At full detail there are 719 complaint
  component names and owners mostly stop at the top level (e.g. 25,125 air-bag complaints say just `AIR BAGS`). The
  component only ranks candidate recalls and drives counts; it never excludes a recall (the AI reads all candidates).
- **Recall numbers are masked** at intake (`24V868`, `24V-868`, `24V868000` → `[recall no. removed]`), together with a
  bracketed note right after the number (hotline staff write `NHTSA Campaign Number: 16V248000 (Power Train)`, which
  would still name the recall's component). The same function masks for the product and the evaluation builder
  (`backend/app/pipeline/intake.py`, tested in `tests/test_intake_evidence.py`).
- **Not read:** dealer contact, the vehicle operator's name and the VIN (personal data), and tire, child-seat and
  vehicle-equipment details the product does not use (all listed in `CMPL.txt`).

## No look-ahead

Every evidence query takes the complaint's received date and only returns recalls, investigations and complaints dated
strictly before it (`backend/app/data/queries.py`, tested in `tests/test_queries.py`). A recall filed on the same day
is not visible: NHTSA publishes recalls after the filing date. An investigation opened before the complaint is shown
with its closing date and resulting recall only when those also came before the complaint (an investigation still
open on that date had no outcome yet).

Not fixable from the data: NHTSA publishes each recall's *current* text, so a recall's remedy can mention a later
recall that replaced it (24V204000's remedy names 24V-868). The system only links a replacement when that recall is
itself a candidate (filed before the complaint).

## Evaluation sets (v2, frozen, `data/eval/`)

Every set uses **owner-written complaints about one vehicle**: `source = 'owner'`, not typed in the hotline's transcript
style (1,622 non-hotline complaints are: "The contact…", "TL*…"), and `vehicles = 1`.

| Set | Test / dev | Ground truth |
|---|---|---|
| **A: known recall** | 300 / 100 | The owner cited exactly one recall that covers the vehicle and was filed before the complaint; at least 200 characters after masking; not about parts availability; the text does not say the vehicle is *not* covered by it. Truth = that recall (the owner's belief). |
| **B: no recall yet** | 142 / 50 | No recall on the vehicle + component at the time; one filed within 365 days after and sharing 3+ distinctive words; the vehicle has other (distractor) recalls; the text does not mention "recall". Truth = must not be "known recall". |
| **C: stress** | 26 / 0 | Real A/B complaints with one change: unknown year (5), unknown component (5), injected instruction (6), too-short text (5), vehicle with no recalls (5). Truth = the designed behaviour. |

Set sizes: A pool 3,927 → 400 sampled (1 skipped: its recall fell outside the 15-candidate cap); B pool 2,891 → 457 with
shared wording → 192 after a cap of 3 complaints per recall (so one big recall cannot dominate).

Facts about the test sets: A has a median of 6 candidate recalls per complaint (90th percentile 13). **For 47% the
cited recall is filed under a different top-level component than the owner chose**: NHTSA's category list overlaps
(`ENGINE` vs `ENGINE AND ENGINE COOLING`, `SERVICE BRAKES` vs `SERVICE BRAKES, HYDRAULIC`, `FUEL/PROPULSION SYSTEM` vs
`FUEL SYSTEM, GASOLINE`), and owners tend to pick the broad one while recalls are filed under the specific one. B's
later recall came a median of 102 days after the complaint.

**Label quality.** The v1 sets were hand-checked by a person (A: 14 of 15 sampled were fair matching tests; B: "no
matching recall at the time" held 20 of 20, and the later recall was the same failure in ~13 of 20). The v2 sets have
not been hand-checked yet.

## Evaluation results and how to read them

- **Rules baseline on v2** (`data/eval/reports/20261120-2025-abc-test-baseline.json`, "newest candidate recall on the
  owner's component", no reading of the text): A picks the owner's recall 41% [36–47], names a different recall 21%
  [17–26], escalates 38% (no recall on the owner's chosen component); B never claims a known recall (by
  construction); C 21/26 (it has no rule for too-short text).
- **AI on v2** (`data/eval/reports/20261120-2045-abc-test-ai.json`, prompt v3, run once): A picks the owner's recall
  51% [46–57], names a different recall 8% [5–12], asks for details 22%, escalates 19%; when it answers "known recall"
  it is the owner's recall 86%; B claims a known recall 5% (7/142); C 26/26; every final answer verified (0 repairs,
  0 fallbacks). Trajectory checks: `data/eval/trajectory/20261120-2045-abc-test-ai.json`.
- **Set A measures agreement with the owner, not accuracy.** Owners sometimes cite the wrong recall, and nothing in the
  data (no repair records, no VINs) can settle which recall is right.
- **Prompt changes were made on the dev split only** (v1 → v2 negation rule, v2 → v3 "symptoms, not causes").

### v1 sets (archived in `data/eval/archive_v1/`) and why they were replaced

The v1 sets, their scored runs, reports and the AI-drafted adjudication are kept for the record, but their
label-based numbers are **not valid**:

- **Hotline transcripts were taken for owner-written complaints.** v1 detected hotline complaints by a `TL*` text
  prefix instead of NHTSA's `CMPL_TYPE`; newer transcripts start "The contact…". So 282 of 400 A cases (70%), 119 of
  292 B and 17 of 26 C were NHTSA staff write-ups, which read more cleanly than owners' text.
- **The answer leaked through the mask** in all 282 of those A cases: `[recall no. removed] (Power Train)` still named
  the cited recall's component.
- **16 A labels contradicted their own text** ("The VIN was not included in NHTSA Campaign Number …").
- 4 B cases named more than one vehicle; and the build depended on Python's set order, so it was not reproducible.

What stays valid from the v1 runs is everything that does not depend on labels: every one of the 563 AI answers was
verified (1 repaired, 0 fallbacks), and the workflow's trajectory rules held on every run (`data/eval/trajectory/`,
`app/eval/trajectory.py`). The full run records are in `data/eval/results/`.

## What the data cannot tell us (limitations)

- **Selection bias in A.** Labels exist only where the owner already knew their recall. Masking removes the number but
  every text still says "recall". Complaints from owners who don't know about a recall have no labels.
- **B's "would have caught it early" is noisy** (~65% the same failure on the v1 hand check). B is reliable for "must
  not claim a known recall"; lead time is reported only as an indicative number.
- **No repair records.** We cannot tell whether a car was repaired under a recall, so "complaint after the remedy" means
  "the fix may not hold, or the car was not repaired", never which one.
- **History windows.** Complaints from 2020 only (similar-complaint counts start then); recalls from 2010 only (older
  recalls on old vehicles are invisible).
- **Owner-chosen components are noisy** ("UNKNOWN OR OTHER", or a broader or different category than the recall's),
  so same-component signals (the baseline, "recall filed under a different component", earlier-complaint counts) are
  weak for owner-written complaints. A category crosswalk (e.g. `ENGINE` ↔ `ENGINE AND ENGINE COOLING`) is not built.
- **Multi-vehicle complaints** (1.1%) are judged and counted on their first vehicle only.
- **Hotline complaints** (22% of complaints) are in the database and can be checked in the workspace, but no evaluation
  set covers them.
