# Recall Match

**For an automaker's field-quality analyst.** A vehicle-safety complaint arrives: is it covered by a **known recall**
(reply to the owner, close), the **same part failing differently**, a **possible new defect** (escalate to
engineering), or **too vague** (ask the owner)? Recall Match suggests the action, drafts the message, and shows why
in the analyst's terms: every quote is checked word for word against the original records.

Built on public NHTSA data (complaints, recalls, defect investigations), Microsoft Agent Framework and Azure OpenAI.
One-page product brief: [docs/BRIEF.md](docs/BRIEF.md) · data and labels: [docs/DATA_CARD.md](docs/DATA_CARD.md).

## Why this problem

An automaker's field-quality team reads thousands of owner complaints. Each one is either already covered by a recall
or a possible new defect, and both mistakes are expensive: calling a new defect "known" is how it becomes a crash and
a recall; escalating everything drowns engineers. The shortcut "same vehicle + same component = known recall" can't
tell *"the air bag deployed when it shouldn't"* from *"the air bag did not deploy"* (demo D2), and owners often file
under a different component than the recall (in 49% of the complaints that cite a recall).

## Run it

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.

```powershell
uv sync
uv run python -m app.data.fetch          # ~380 MB of NHTSA flat files -> data/raw
uv run python -m app.data.ingest         # -> data/nhtsa.db (~550 MB, ~1 min)
uv run pytest                            # 119 tests, no network, no model

uv run uvicorn app.main:app --app-dir backend --port 8000
cd frontend; npm install; npm run dev    # http://localhost:5173  (operations portal: /ops)
```

**Without Azure** it still runs: on first start the workspace opens with the stored AI results of the 19 inbox tickets
(`data/inbox_results.jsonl.gz`), so every ticket shows its checked suggestion and investigation trail; a new check gets
the rules-only suggestion, clearly marked "please check before acting", and follow-up questions are off. **With a
model:** copy `.env.example` to `.env`, set `NHTSA_AZURE_ENDPOINT` and `NHTSA_DEPLOYMENT`, `az login` (Entra ID, no
keys).

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
this". The API rejects names outside the list. In production the VIN would fill these in.

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
| D2 | 2022 Acura MDX: air bags **did not deploy** in a crash (fire, injury) | **Same part, opposite failure**: the only air bag recall is about deploying when it shouldn't. The same-component shortcut calls it "known" |
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
`judge` calls the model. The workspace layer turns a verified result into the analyst's view.

| Decision | Why | Trade-off |
|---|---|---|
| Candidates come from a query (vehicle + date), not from the AI or a vector search | Median 6 candidates; the AI cannot invent a recall | A recall filed under another vehicle name is missed |
| Quotes, checked word for word, as provenance (and a quote may not drop a "no"/"zero") | The analyst sees *why* in context; code verifies it | Owners' wording is messy; quotes must be ≥ 3 words |
| Rules set the outcome; the AI proposes | Confidence follows written rules, so it means the same every time; the costly decision is made by code | Less flexible |
| Owner replies are templates over the recall's text | A reply can never promise a remedy the recall doesn't state | Less fluent |
| Escalate only with a stated reason | Engineers' time is the scarce resource | Thresholds are judgment calls, not yet tuned (next: on the share of escalations engineers confirm) |
| Analyst workspace and operations portal are separate | Analysts act; builders audit. Different words, different screens | Two UIs to maintain |
| SQLite + full-text search, no vector DB, no multi-agent | One file, reproducible, easy to trace | Similar-complaint search is keyword-based (the AI phrases the query) |

## Evaluation: what is checked

**Only what can be checked objectively is reported**: against the records, against our own specification, or
measured. There is no ground truth for which recall is right (the only labels are the recalls owners cite, owners are
sometimes wrong, and the data has no VINs or repair records), so **no accuracy or agreement number is reported**.

**Test inputs.** 471 real, owner-written NHTSA complaints frozen into sets that cover the situations the product must
handle ([docs/DATA_CARD.md](docs/DATA_CARD.md)): the owner cited a recall (number hidden from the system), no recall
existed yet on that part, and 26 stress cases. Each is replayed through the product's own pipeline as of the day it
arrived and checked by code; no AI grades the AI (prompt v3, run once; `data/eval/reports/20261120-2209-abc-test-ai.json`).

| What is checked | How | Result |
|---|---|---|
| **Every claim is real** | Each recall is a candidate on that date, each quote is in its source word for word, each number exists | 0 of 466 first AI answers failed; 2 fell back to the rules, labelled (the provider's content filter blocked them) |
| **The workflow's rules hold** | 16 rules checked on every stored run: step order, one correction then fallback, nothing dated after the complaint, only candidate recalls, searches bounded, the analyst's trail matches what ran (`app/eval/trajectory.py`; each rule is tested to fail on a broken run) | 16 of 16, on all 471 runs |
| **Stress cases behave as designed** | Unknown year → ask, no AI; too short → ask, never escalate; injected instructions never reach the answer; no recalls → nothing judged | 21 of 21 |
| **No look-ahead, no self-leak** | Each complaint's evidence gathered as stored and as a brand-new complaint with no id (`app/eval/as_new.py`) | Identical for 490 of 490 (test sets + inbox); none ever found itself |
| **Follow-up answers keep to the records** | 21 questions on the demo tickets (`app/eval/ask_eval.py`): every quote found word for word; "not in the records" for what the data lacks (repair history, crash data, VIN); unrelated requests declined; a re-check suggested when the analyst gives a new fact | 20 of 20 answers verified (1 blocked by the provider); 4 of 4; 2 of 2; 1 of 1 |
| **Cost and speed** | Measured | ~5,000 tokens, p50 10 s, p95 35 s per complaint |

**What this proves, and what it doesn't.** Every answer the analyst sees rests on real evidence and follows the
specified workflow. It does **not** prove the judgment is right: that needs labels we don't have yet (see the future
plan). The value of reading the text, rather than matching components, is shown on concrete cases (demo D2).

**Reproduce.** Every run's full results are committed (`data/eval/results/*.jsonl.gz`):
`uv run python -m app.eval.trajectory --run <name>` re-checks the rules without the model;
`uv run python -m app.eval.as_new` repeats the no-look-ahead check (no model, a few minutes);
`uv run python -m app.eval.run` (needs a model) runs it again, `--report <name>` rebuilds a stored run's report without
the model. The sets rebuild identically
(`app.eval.build_sets`).

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

## Limitations

- **No accuracy number.** Set A's key is the owner's citation; set B's later recall is the same failure in roughly 2 of
  3 cases (hand check of the first sets). The current sets are not hand-checked yet.
- **Coverage needs the VIN.** A recall usually covers cars built between two dates (70% of vehicle recalls publish
  them). Candidates are found by model year; the ticket shows the build dates and the owner reply says the car *may*
  be covered and how to confirm it.
- **Remedy-access complaints** ("the dealer has no parts", no failure described) are escalated or sent back instead of
  linked to the recall the owner cited.
- **Data shape.** NHTSA's component categories overlap (`ENGINE` vs `ENGINE AND ENGINE COOLING`), so same-component
  signals are weak; hotline write-ups (22% of complaints) are in the database but not in any test set; no repair
  records, so "complaints after the remedy" cannot tell a failed fix from an unrepaired car.
- **Throughput.** ~10 s per complaint at our quota.

## Future plan

**Evaluation** (in order):
1. **A real accuracy number**: a blind sample labelled by two people (which recall fits, without seeing the AI's
   answer), with their agreement with each other measured as the ceiling; the first ground truth to score against.
2. **Run-to-run stability**: each test case three times; how often the outcome changes.
3. **A slice after the model's training cutoff**, so the model cannot have seen the complaints or recalls.
4. **Production metrics from the workspace's own log** (already stored): override rate and its reasons, time to
   triage, share of escalations engineers confirm. Overrides become the next labels.

**Product:** link remedy-access complaints to the cited recall; VIN decoding (vehicle, build date, open recalls);
cluster escalations; alert when complaints keep coming after a remedy; learn the escalation thresholds from what
engineers confirm; a cheaper first pass for bulk triage.

## Data and license

NHTSA data is public domain (US government work). See [docs/DATA_CARD.md](docs/DATA_CARD.md).
