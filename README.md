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
the wrong recall **19%** of the time on real data and can't tell *"the air bag deployed when it shouldn't"* from
*"the air bag did not deploy"*.

## Run it

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+.

```powershell
uv sync
uv run python -m app.data.fetch          # ~380 MB of NHTSA flat files -> data/raw
uv run python -m app.data.ingest         # -> data/nhtsa.db (~550 MB, ~1 min)
uv run pytest                            # 55 tests, no network, no model

uv run uvicorn app.main:app --app-dir backend --port 8000
cd frontend; npm install; npm run dev    # http://localhost:5173  (operations portal: /ops)
```

**No Azure needed** to try it: without `.env` the app replays recorded model answers (`cassettes/`) for the demo
complaints; anything not recorded gets the rules-only suggestion, clearly marked "please check before acting".
**With a model:** copy `.env.example` to `.env`, set `NHTSA_AZURE_ENDPOINT` and `NHTSA_DEPLOYMENT`, `az login` (Entra
ID, no keys). `uv run python -m app.store.reset` clears what analysts did (keeps the AI runs) for a fresh demo.

## What the analyst does (the workspace)

| The ticket turns out to be | Suggested action (one click, editable) | Shown as evidence |
|---|---|---|
| **Covered by a recall** | Link to the recall + reply to the owner (drafted **from the recall's own remedy text**, never written by AI) | "This vehicle is covered (2022–2024 Ioniq 5)"; *owner wrote* ↔ *recall says*; replaced recalls |
| …and complaints continue after the fix | Same, **+ flag the remedy** to an emerging issue for engineering | "85 earlier complaints: 10 before the recall, 75 after it" |
| **Same part, different failure** / **no recall fits**, with a reason | Escalate to an emerging issue (existing one suggested, or a new one) | The reason: crash/fire/injury, ≥3 similar complaints in 12 months, ≥2 earlier owners describing the same failure, or **the same failure recalled on other model years** |
| …a single report with none of those reasons | **Record and watch** (no escalation yet) | The counts vs. the escalation thresholds |
| **Too vague** | Ask the owner (drafted with the AI's 1–3 questions) | The probable recall, if any |

Anything other than the suggestion asks for one line of why; that is the feedback signal. Engineers see escalations
grouped on the **Emerging issues** page. The **operations portal** (`/ops`) is for the people running the system: every
AI run with its audit trail, failure drills (break the model on purpose), a sandbox, and the evaluation.

### Demo (real complaints, in the inbox)

| | Complaint | What it shows |
|---|---|---|
| D1 | 2024 Hyundai Ioniq 5 loses drive power (ICCU) | Known recall; the older recall it **replaced** is recognized; **75 complaints after the remedy** → reply + flag to engineering |
| D2 | 2022 Acura MDX: air bags **did not deploy** in a crash (fire, injury) | **Same part, opposite failure**: the only air bag recall is about deploying when it shouldn't. The baseline calls it "known" |
| D3 | 2018 Honda Ridgeline: rear camera dies, tailgate pinches the wiring | **Possible new defect**; the AI finds 3 earlier owners describing it. NHTSA recalled it **348 days later** (hindsight, shown after) |
| D4 | 2019 Ford Mustang: "Backup camara is not working" | **Too vague**: names the probable recall, asks 3 questions |
| D5 | D1 with the model unavailable (ops portal → failure drill) | Rules-only fallback, labelled; never a silent guess |
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

Three frozen test sets built only from real records ([docs/DATA_CARD.md](docs/DATA_CARD.md)); the prompt was tuned
only on a separate dev split; the test sets were run once with prompt v3 (563 AI checks). 95% intervals in brackets.

| | AI (verified) | Rules baseline |
|---|---|---|
| **Set A** (owner cited a recall, number hidden) · names a recall other than the owner's | **7%** [5–10] | 19% [15–24] |
| Set A · when it answers "known recall", it's the owner's recall | **88%** [83–92] | 79% [74–84] |
| Set A · agrees with the owner's recall overall | 54% [48–60] | 72% [67–77] |
| **Set B** (no recall yet on that part) · claims a known recall | 5% [3–9] | 0% (by construction) |
| Set B · escalates or asks for details | 95% | 100% |
| **"High confidence" answers that are right** | **94%** [88–97] (115/123) | – |
| Stress set C (unknown year/component, too short, no recalls, injected instructions) | 25/26 | 21/26 |
| First AI answer failed verification / fell back to rules | 1 of 563 / 0 | – |
| Cost and speed | ~5,400 tokens, p50 13 s (rate-limited quota) | – |

**What it means.** Set A's label is the recall the *owner* cited, so "agreement" is not accuracy: owners are
sometimes wrong. We read a fixed random sample of 30 of the AI's 138 disagreements: **AI right 12, owner right 7,
unclear 11** ([adjudication](data/eval/adjudication/)). **All 7 "owner right" cases describe no failure at all**,
only trouble getting the recall repair done; the AI correctly found nothing to match, but the product then escalated
or asked for details instead of linking the cited recall as a *remedy-access* problem. That is the top next step. In
set B, of the 13 "known recall" claims, a reader judged 6 right (an existing recall on another component really fits),
3 wrong, 4 unclear.

Injected instructions never made the AI cite the injected recall or claim a known recall (6/6); in 5/6 the outcome
was identical to the clean complaint (the 6th moved between two escalation outcomes; run-to-run variation is not yet
measured). One rule bug was found on test set C (a two-word complaint escalated as a new defect) and fixed; the same
stored AI answers were re-decided (`app/eval/rescore.py`, 5 decisions changed), and the report says so.

Reproduce: every run's full results are committed (`data/eval/results/*.jsonl.gz`), so
`uv run python -m app.eval.rescore --run <name>` re-scores without the model. Fresh runs:
`uv run python -m app.eval.run --set a,b,c`.

## Edge cases handled (each has a test or an evaluation case)

- **Owner cites the recall number** → masked before the AI sees it (no leak, no steering).
- **Instructions inside the complaint** → treated as data; any non-candidate recall is rejected by the verifier.
- **Replaced recalls** ("replaced by NHTSA recall number 24V-868") → the newer one is used, not "two matches".
- **Same part, opposite failure** → not "known"; escalated with the difference quoted.
- **A quote that drops "Zero"** ("[Zero] airbags were deployed") → rejected (found in a live run).
- **Complaints continue after a remedy** → reply + flag; the data can't tell a failed fix from an unrepaired car.
- **Same failure recalled on other model years** → flagged as a possible recall-scope gap.
- **Unknown year / unknown component / two words** → ask / search all candidates / ask.
- **Model down, garbage output, invented ids or numbers** → one repair, then labelled rules-only fallback.
- **Look-ahead** → every query is bounded by the complaint date (a recall filed the same day is invisible).
- **ALL-CAPS older recall texts** → shown in sentence case; not mistaken for acronyms.

## Limitations and next steps

- **Remedy-access complaints** ("I have the notice, the dealer can't do the repair") should link the owner's cited
  recall instead of escalating: the adjudication's main finding. Next step.
- **Labels.** Set A only covers owners who knew their recall; B's "would have caught it early" is ~65% the same failure.
  Analyst and engineer actions in the workspace are stored and should become the next labels.
- **Not yet measured:** run-to-run stability (same case 3×), analyst time saved.
- **Coverage.** Complaints from 2020, recalls from 2010; no repair records; vehicle names must match NHTSA's spelling
  (production: VIN decoding).
- **Throughput.** ~13 s per complaint at our quota; bulk triage needs more quota or a cheaper first pass.
- **Next:** cluster escalations automatically; alert when complaints keep coming after a remedy; learn the escalation
  thresholds from engineer confirmations.

## Data and license

NHTSA data is public domain (US government work). See [docs/DATA_CARD.md](docs/DATA_CARD.md).
