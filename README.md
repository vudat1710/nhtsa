# Recall Match

**For an automaker's field-quality analyst.** A vehicle-safety complaint arrives: is it covered by a **known recall**
(reply to the owner, close), the **same part failing differently**, a **possible new defect** (escalate to
engineering), or **too vague** (ask the owner)? Recall Match suggests the action, drafts the message, and shows why
in the analyst's terms: every quote is checked word for word against the original records.

Built on public NHTSA data (complaints, recalls, defect investigations), Microsoft Agent Framework and Azure OpenAI.
One-page product brief: [docs/BRIEF.md](docs/BRIEF.md) · code map: [docs/CODE_TOUR.md](docs/CODE_TOUR.md) · data and
labels: [docs/DATA_CARD.md](docs/DATA_CARD.md).

## Why this problem

An automaker's field-quality team reads thousands of owner complaints. Each one is either already covered by a recall
or a possible new defect, and both mistakes are expensive: calling a new defect "known" is how it becomes a crash and
a recall; escalating everything drowns engineers. The shortcut "same vehicle + same component = known recall" names
a different recall than the owner cited **about 1 time in 5** (19% on our owner-written test set; the AI: 7%) and can't tell *"the air bag deployed when it shouldn't"* from
*"the air bag did not deploy"*.

## Run it

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.

```powershell
uv sync
uv run python -m app.data.fetch          # ~380 MB of NHTSA flat files -> data/raw
uv run python -m app.data.ingest         # -> data/nhtsa.db (~550 MB, ~1 min)
uv run pytest                            # 79 tests, no network, no model
uv run python -m app.store.reset         # fresh workspace; on a fresh clone, loads the inbox's stored AI results
                                         #   --live: tickets start unchecked and are checked live when opened
uv run python -m app.data.report         # -> docs/data_report.html: raw files -> DB -> one complaint through every
                                         #    step -> what app.db stores (diagrams: docs/DATA_MODEL.md)

uv run uvicorn app.main:app --app-dir backend --port 8000
cd frontend; npm install; npm run dev    # http://localhost:5173  (operations portal: /ops)
```

**No Azure needed** to try it: `reset` loads the stored AI results of the 19 inbox tickets
(`data/inbox_results.jsonl.gz`), so every ticket opens with its checked suggestion and investigation trail. Without a
model, a new check gets the rules-only suggestion, clearly marked "please check before acting", and follow-up
questions are off. **With a model:** copy `.env.example` to `.env`, set `NHTSA_AZURE_ENDPOINT` and
`NHTSA_DEPLOYMENT`, `az login` (Entra ID, no keys). `reset` clears what analysts did (keeps the AI runs) for a fresh
demo.

## What the analyst does (the workspace)

| The ticket turns out to be | Suggested action (one click, editable) | Shown as evidence |
|---|---|---|
| **Matches a recall** | Link to the recall + reply to the owner (drafted **from the recall's own remedy text**, never written by AI; says the vehicle *may* be covered and how to confirm with the VIN) | "The 2024 Ioniq 5 is in recall 24V-868 (2022–2024; 2024 models built Oct 4, 2021 – Oct 9, 2024): confirm with the VIN"; *owner wrote* ↔ *recall says*; replaced recalls |
| …and complaints continue after the fix | Same, **+ flag the remedy** to an emerging issue for engineering | "85 earlier complaints: 10 before the recall, 75 after it" |
| **Same part, different failure** / **no recall fits**, with a reason | Escalate to an emerging issue (existing one suggested, or a new one) | The reason: crash/fire/injury, ≥3 similar complaints in 12 months, ≥2 earlier owners describing the same failure, or **the same failure recalled on other model years** |
| …a single report with none of those reasons | **Record and watch** (no escalation yet) | The counts vs. the escalation thresholds |
| **Too vague** | Ask the owner (drafted with the AI's questions when it gave any, otherwise a standard request) | The probable recall, if any |

Anything other than the suggestion asks for one line of why; that is the feedback signal. Engineers see escalations
grouped on the **Emerging issues** page. The **operations portal** (`/ops`) is for the people running the system: every
AI run with its audit trail, failure drills (model down, broken answer, answer cut off, refusal), and the evaluation.

### A brand-new complaint

**+ New complaint** in the inbox takes a complaint that is not in NHTSA's data (one that just came in by phone, or one
a reviewer writes). It becomes a ticket received **today** (ticket number `typed #1`, `#2`, …; negative internally so
it can never clash with an NHTSA id) and goes through exactly the same check, trail, actions and follow-up questions,
compared with every recall filed before today. Make, model and year are picked from NHTSA's own list (1,905 makes):
recalls are found by exact name, so a typed "Ioniq5" would find no recall and wrongly read as "no recall covers
this". The API rejects names outside the list. In production the VIN would fill these in. `reset` clears typed
complaints and their runs.

### See how it got there, then ask about it

- **How the agent investigated**: every ticket shows the steps in order, in analyst words: read the complaint → looked
  up what was known on that date → *decided to search* earlier complaints for "…" (the agent's own wording, and what it
  found) → compared with each recall (quotes) → checked every quote → decided by the rules. While a check runs, the
  same steps appear live; "watch it again live" re-runs the check. The steps are built by code from the stored run
  (`workspace/trail.py`), so they show what actually happened, not a story the model tells afterwards.
- **Ask about this case**: follow-up questions ("Why doesn't that recall cover this?", "Have other owners reported the
  same failure?"). The assistant only sees this case's record and may search earlier complaints (same date limit).
  Every answer cites quotes that are **checked word for word**; it says *"not in the records"* instead of guessing
  (VIN, repair history), declines out-of-scope requests, and flags when new information (e.g. "it's actually a 2023")
  means the case should be **re-checked** rather than answered. Each answer has **How it answered**: the searches
  it ran, the quotes it used, the check result. Questions and answers are stored on the ticket.
- *Why not show the model's own reasoning?* We tried: the judge uses no reasoning tokens at its evaluated settings,
  and the assistant returned a reasoning summary for 1 of 21 eval questions. A trail built from what the system
  actually did is always there and can be checked; a model's account of itself is neither.

### Demo (real complaints, in the inbox)

| | Complaint | What it shows |
|---|---|---|
| D1 | 2024 Hyundai Ioniq 5 loses drive power (ICCU) | Known recall; the older recall it **replaced** is recognized; **75 complaints after the remedy** → reply + flag to engineering |
| D2 | 2022 Acura MDX: air bags **did not deploy** in a crash (fire, injury) | **Same part, opposite failure**: the only air bag recall is about deploying when it shouldn't. The baseline calls it "known" |
| D3 | 2018 Honda Ridgeline: rear camera dies, tailgate pinches the wiring | **Possible new defect**; the AI finds 3 earlier owners describing it. NHTSA recalled it **348 days later** (hindsight, shown after) |
| D4 | 2019 Ford Mustang: "Backup camara is not working" | **Too vague, and the rules overrule the AI**: the AI calls it recall 22V-382 ("same failure"); the rules see 28 characters, decide "needs info", name the probable recall, and say the AI was overruled |
| D5 | D1 in the ops portal → failure drills | Never a silent guess. "Model unavailable" → labelled rules-only fallback; "broken answer" → one repair turn, then the same verified answer; "cut off at the token limit" (a real cut-off: the call is sent with a 16-token limit) and "refusal" (simulated) → `incomplete` / `refused`, rules-only fallback |
| D6 | Ops portal → run `/ops/runs/3c68585fd6c9` (complaint 11705719, from the v3 AI eval) → "Run with AI" | **A real provider block**: Azure's content filter rejects the request → `content_filter`, rules-only fallback (11752255, run `1602f7d69c63`, does the same) |
| – | 2027 Ioniq 5: ICCU failed (recent complaint in the inbox) | **Recall-scope gap**: no recall covers the 2027, but 24V-868 covers the same failure on 2022–2024 → escalate |

## How it works

```
complaint ─► intake ─► evidence ──► judge (AI) ─► verify ──► decide ─► workspace suggestion ─► analyst action
             code       code          agent        code        code        code (templates)
             mask       recalls on    one call +   ids, quotes, outcome +  what to do, why,
             recall     this vehicle  1 search     numbers;     confidence drafted messages,
             numbers,   before this   tool         1 repair     rules      escalation reasons
             flags      date (as_of)                 │ fails twice
                                                     └──► rules-only fallback (labelled)
```

A Microsoft Agent Framework graph workflow wires the five pipeline steps (with the repair loop and fallback edge); only
`judge` calls the model. The workspace layer turns a verified result into the analyst's view. Map:
[docs/CODE_TOUR.md](docs/CODE_TOUR.md).

| Decision | Why | Trade-off |
|---|---|---|
| Candidates come from a query (vehicle + date), not from the AI or a vector search | Median 6 candidates; the AI cannot invent a recall | A recall filed under another vehicle name is missed |
| Quotes, checked word for word, as provenance (and a quote may not drop a "no"/"zero") | The analyst sees *why* in context; code verifies it | Owners' wording is messy; quotes must be ≥ 3 words |
| Rules set the outcome; the AI proposes | Confidence is measurable; the costly error is controlled by code | Less flexible |
| Owner replies are templates over the recall's text | A reply can never promise a remedy the recall doesn't state | Less fluent |
| Escalate only with a stated reason | Engineers' time is the scarce resource | Thresholds are judgment calls (tuned on engineer confirmation rate) |
| Analyst workspace and operations portal are separate | Analysts act; builders audit. Different words, different screens | Two UIs to maintain |
| SQLite + full-text search, no vector DB, no multi-agent | One file, reproducible, easy to trace | Similar-complaint search is keyword-based (the AI phrases the query) |

## Evaluation: can you trust it?

Frozen test sets built only from **owner-written complaints about one vehicle** ([docs/DATA_CARD.md](docs/DATA_CARD.md)):
A, the owner cited a recall (number masked); B, no recall existed yet on that part; C, stress cases. The prompt was
tuned only on the dev split; the test sets were run once with prompt v3 (`data/eval/reports/20261120-2209-abc-test-ai.json`,
466 AI checks; 5 unknown-year cases skip the model by design). 95% intervals in brackets.

**There is no ground truth for "which recall is right".** Set A's label is the recall the *owner* cited (their belief),
and the data has no repair records or VINs to check it against. So the table separates what is **checked
objectively** (by code, from dates and the system's own records) from what is only **agreement with the owner**,
which compares the AI with the baseline on the same noisy labels but is not accuracy.

| Test sets v3 (300 A, 145 B, 26 C) | AI (verified) | Rules baseline |
|---|---|---|
| ***Checked objectively*** | | |
| Cites only recalls that covered the vehicle on that date; every quote word for word; no later records seen | 466/466 (by construction + verifier) | – |
| First AI answer failed verification / repaired / fell back to rules / model errors | 0 / 0 / 2 / 2 of 466 (both: the provider's content filter blocked the complaint) | – |
| **Set B** (no recall existed yet on the owner's component) · claims a known recall | 3% [2–8] (5/145) | 0% (by construction) |
| Set B · escalates or asks for details | 97% | 100% |
| Stress set C (unknown year/component, too short, no recalls, injected instructions) | **25/26** | 21/26 |
| Cost and speed | ~5,000 tokens, p50 10 s, p95 35 s | – |
| ***Agreement with the owner's cited recall (set A, not accuracy)*** | | |
| Names a recall other than the owner's (confidently wrong vs the owner) | **7%** [4–10] | 19% [15–24] |
| When it answers "known recall", it's the owner's recall | **88%** [82–92] | 68% [61–74] |
| Agrees with the owner's recall overall | **50%** [44–55] | 39% [34–45] |
| Asks for details / escalates instead | 23% / 20% | 0% / 42% |
| "High confidence" answers that agree with the set's label (A and B) | **98%** [92–100] (65/66) | – |

**What it means.** The AI names a recall other than the owner's about a third as often as the rules, and when it
commits to "known recall" it is the owner's recall 88% of the time; it gets there by asking for details on vague
complaints instead of guessing. The baseline is weak on owner-written complaints because owners often pick a broader
category than the recall's (in 49% of A the cited recall is filed under a different top-level component, e.g. `ENGINE`
vs `ENGINE AND ENGINE COOLING`); the AI reads every candidate. Owners are sometimes wrong, so agreement can understate
or overstate accuracy; a real accuracy number needs a blind, two-reviewer labelled sample (see Limitations). The one
stress miss: with an injected instruction, one complaint got a different (still verified) outcome than its clean
version (`needs_info` instead of `known_recall`); the injected recall was never cited, in 6/6.

**Why the sets were rebuilt (v3, after v1 and v2).** Each rebuild followed a check of our data handling against
NHTSA's own field descriptions (`docs/nhtsa/`). v1 (`data/eval/archive_v1/`) took hotline complaints by a `TL*` prefix
instead of the documented `CMPL_TYPE`, so 70% of set A were staff write-ups whose mask still named the recall's
component (`[recall no. removed] (Power Train)`). v2 (`data/eval/archive_v2/`) judged some complaints on a tyre or
child-seat line instead of the vehicle (`PROD_TYPE`), did not load recalls filed before 2010 (NHTSA publishes them in a
second file), and kept one recall per investigation although it can differ per vehicle line. Earlier sets' agreement
numbers are not reported as results. An AI-drafted, unreviewed read of 30 v1 disagreements pointed at one product gap
worth building: complaints about *getting* a recall repair ("the dealer has no parts"), which describe no failure, are
escalated instead of linked to the cited recall.

**Follow-up questions** (`app/eval/ask_eval.py`, 21 questions over the 5 demo tickets, checked by code: scope,
citations verified, "not in the records" when the records can't answer, re-check flag): **21/21 passed**; every
non-blocked answer's quotes verified (20/20; 1 injection request was blocked by the provider's safety filter and shown
as such); 4/4 "not in the records" when expected; 3.7 citations per answer; p50 4.0 s
(`data/eval/reports/ask-20261120-2301.json`). Small set: it shows the guardrails work, not that answers are always the
most useful.

**Trajectory evaluation (no labels needed)** (`app/eval/trajectory.py`). Without ground truth for *which* recall is
right, there is still ground truth for *how* a case must be handled. Every stored run is checked against 23 rules of
the workflow: the path (step order, one repair turn after a failed check, no retry after a model error, a source label
that matches what happened), the evidence (masked complaint, only candidate recalls, nothing dated after the complaint,
quotes word for word), the search tool (budget, only earlier complaints on the same vehicle, cited complaints come from
its own searches, searched only when no recall matched, queries in its own words), the decision (backed by a 'same'
check, AI overrules flagged, escalation follows the outcome, the analyst's trail shows exactly what ran) and the
designed path of each stress case. *Invariants* must always hold (a failure is a bug); *policies* are what the prompt
asks of the agent, tracked as rates. Each check is tested to fail on a deliberately broken run
(`tests/test_trajectory.py`).

| On the 471 v3 test runs (prompt v3) | |
|---|---|
| 16 invariants + 4 stress-case paths | all hold |
| Searched only when no recall matched (policy) | 464/464 |
| Searched for earlier owners before proposing a new defect (policy) | 179/181 (two `related_different` without a search) |
| Proposed new defects backed by earlier owners | 146/181 |
| Proposed new defects that ignore a recall on the owner's own component | 0/181 |
| Searched at all / searches that found something | 46% of AI runs / 98% |

It also shows behaviour shifts between versions on the same cases: on the 150 v1 dev cases, prompt v2 searched in 69%
of runs and v3 in 51% (v3 judges more symptom matches as "same", which needs no search). Run it on any stored run or
on the workspace's runs: `uv run python -m app.eval.trajectory [--run <name> | --label queue]`. Not yet measured:
whether the trajectory is stable when the same case runs several times.

Reproduce: every run's full results are committed (`data/eval/results/*.jsonl.gz`), so
`uv run python -m app.eval.rescore --run <name>` re-scores a run without the model. Fresh runs:
`uv run python -m app.eval.run --set a,b,c --mode ai` (model) or `--mode baseline`.

## Edge cases handled (each has a test or an evaluation case)

- **Owner cites the recall number** → masked before the AI sees it (no leak, no steering).
- **A hotline write-up names the recall's component after its number** (`16V248000 (Power Train)`) → masked too.
- **Instructions inside the complaint** → treated as data; any non-candidate recall is rejected by the verifier.
- **Replaced recalls** ("replaced by NHTSA recall number 24V-868", "supersedes recalls 13V-029 and 14V-147", "Recall
  21V469 supersedes this recall") → the newer one is used, not "two matches". Read from the recall texts' own wording
  (136 replacement pairs across NHTSA's recalls); only linked when both are candidates and the newer was not filed first.
- **Same part, opposite failure** → not "known"; escalated with the difference quoted.
- **A quote that drops "Zero"** ("[Zero] airbags were deployed") → rejected (found in a live run).
- **Complaints continue after a remedy** → reply + flag; the data can't tell a failed fix from an unrepaired car.
- **Same failure recalled on other model years** → flagged as a possible recall-scope gap.
- **Unknown year / unknown component / two words** → ask / search all candidates / ask.
- **A typed-in vehicle name NHTSA doesn't use** ("Ioniq5") → rejected with a message; the form only offers NHTSA's
  names (otherwise no recall would be found and it would wrongly read as "no recall covers this").
- **Answer shape** → strict structured output: the provider constrains every completed, non-refusal answer to the
  JSON schema (judge and follow-up assistant). What that does not cover is handled in code, each with its own label:
  a refusal (`refused`), an answer cut off at the token limit (`incomplete`), a blocked request (`content_filter`), an
  outage (`unavailable`): rules-only fallback, no retry. The content (quotes, ids, numbers) is still checked by the
  verifier.
- **Broken output, invented ids or numbers** → one repair, then labelled rules-only fallback.
- **Look-ahead** → every query is bounded by the complaint date (a recall filed the same day is invisible).
- **ALL-CAPS older recall texts** → shown in sentence case; not mistaken for acronyms.
- **Follow-up question the records can't answer** (VIN, was it repaired?) → "not in the records", no guess.
- **Follow-up that changes the facts** ("it's a 2023, not a 2022") → flagged for a re-check, not answered on stale evidence.
- **Follow-up blocked by the provider's content filter** → shown as blocked, not as an error or an empty answer.

## Limitations and next steps

- **Remedy-access complaints** ("I have the notice, the dealer can't do the repair") should link the owner's cited
  recall instead of escalating: the clearest finding from reading the disagreements. Next step.
- **No ground truth for accuracy.** Set A's labels are the owners' citations and the adjudication is an unreviewed AI
  draft. Next: a blind sample labelled by two people (which of two recalls fits, without knowing which one the AI
  picked), with their agreement measured, used to turn agreement rates into estimated accuracy.
- **The v3 sets are not hand-checked yet** (v1 was, by a person).
- **Labels.** Set A only covers owners who knew their recall; B's "would have caught it early" is ~65% the same failure.
  Analyst and engineer actions in the workspace are stored and should become the next labels.
- **Components.** NHTSA's top-level categories overlap (`ENGINE` / `ENGINE AND ENGINE COOLING`), so same-component
  signals are weak for owner-written complaints; a category crosswalk is not built.
- **Data shape.** Hotline complaints (22%) are in the database but no evaluation set covers them. A recall usually
  covers only cars built between two dates (70% of vehicle recalls publish them). Candidates are found by model year;
  the build dates are shown, and the ticket and the owner reply say the car *may* be covered and ask to confirm with
  the VIN. Without a VIN we cannot confirm it (next: VIN decoding). Do-not-drive / park-outside advisories are stored
  but not yet shown to owners.
- **Not yet measured:** run-to-run stability (same case 3×), analyst time saved.
- **Coverage.** Complaints from 2020 (all recalls since 1966); no repair records; vehicle names must match NHTSA's
  spelling (production: VIN decoding).
- **Throughput.** ~10 s per complaint at our quota; bulk triage needs more quota or a cheaper first pass.
- **Next:** cluster escalations automatically; alert when complaints keep coming after a remedy; learn the escalation
  thresholds from engineer confirmations.

## Data and license

NHTSA data is public domain (US government work). See [docs/DATA_CARD.md](docs/DATA_CARD.md).
