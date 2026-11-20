# Code tour

One page to find your way around. Every folder has one responsibility; every pipeline step is one file.

## Map

```
backend/app/
  config.py              settings from .env (NHTSA_*); nothing secret (Azure auth = az login)
  models.py              the data shapes = the contract between steps:
                         Complaint → Intake → Evidence → Judgment (AI) → Decision, all stored as one Result
  main.py                FastAPI app (routes live in api/)

  data/                  NHTSA data access only. No decisions.
    fetch.py             download the flat files
    ingest.py            flat files → data/nhtsa.db (explicit schema, text repair, full-text index)
    queries.py           read-only queries; the as_of rule (no look-ahead) lives here and only here

  pipeline/              one complaint → one decision
    workflow.py          the MAF graph: order of steps, repair loop, fallback edge. No logic of its own
    intake.py            1 code  mask recall numbers, flag unknown year / component / short text / severity
    evidence.py          2 code  candidate recalls (+ which replaced which), investigations, complaint counts
    judge.py             3 AI    build the agent for one case and ask it (never raises)
    verify.py            4 code  ids exist, quotes are word-for-word (and keep their negation), numbers exist
    decide.py            5 code  outcome + confidence rules; the rules-only baseline / fallback

  ai/                    everything about the model, nothing about recalls
    prompt.py            instructions (versioned), case message, repair message, JSON parsing
    tools.py             search_complaints: the agent's only tool (read-only, as_of-bounded)
    clients.py           live Azure OpenAI / offline / scripted (tests) clients + LlmSetup
    middleware.py        record/replay cassettes, fault injection, tool-call trace

  store/results.py       data/app.db: every run (full audit record) and every human review
  api/                   HTTP routes: cases.py (queue, run with live progress), reviews.py, evals.py; deps.py
  eval/                  build_sets.py (frozen real-data test sets), run.py (score + report)

backend/tests/           one file per area; conftest.py is a tiny NHTSA world (same schema)
frontend/src/
  api/                   client.ts (fetch + progress stream), types.ts (mirrors models.py)
  lib/                   labels.ts (plain words for every code), highlight.ts (quote → position in source)
  components/            one piece of the case file each
  pages/                 Queue, Case, Engineer review, New complaint, Can you trust it?
data/eval/               frozen sets (set_a/b/c.json), demo.json, reports/ (metrics per run)
docs/                    BRIEF.md, DATA_CARD.md, this file
```

## One complaint, traced

`POST /api/cases/11443328/run` (the Honda Ridgeline demo):

1. `api/cases.py: run_case` loads the complaint (`queries.complaint`) and streams `pipeline/workflow.py: run`.
2. **intake** (`intake.py`): masks recall numbers, sets flags. No database, no AI.
3. **evidence** (`evidence.py: gather`): `queries.recalls_for(vehicle, as_of=2021-12-10)` returns the 4 recalls filed
   before that date; `link_replacements` marks replaced recalls; complaint counts are computed here. Then
   `judge.build_judge` creates the agent with its tool and middleware.
4. **judge** (`judge.py: ask`): the agent gets `prompt.case_message` (masked text + candidates). It calls
   `search_complaints` once; the tool stores full texts in `found` for the verifier. It answers JSON.
5. **verify** (`verify.py`): parses the JSON, checks every recall id is a candidate, every quote is in its source (and
   does not cut off a "no"/"zero"), every cited complaint came from its own search, every number exists. Issues →
   back to **judge** once with the issue list; twice → fallback.
6. **decide** (`decide.py`): no "same" checks, 4 candidates, 4 complaints in 12 months → `possible_new`, medium,
   flag `pattern`, escalate.
7. The `Result` is stored (`store/results.py`) and streamed to the UI as the last event.

## Where to look when asked…

| Question | File |
|---|---|
| How do you stop look-ahead? | `data/queries.py` (`< as_of` in every query), `tests/test_queries.py` |
| How do you know a quote is real? | `pipeline/verify.py: quote_problem`, `tests/test_verify_decide.py` |
| Who decides the outcome, the AI or code? | `pipeline/decide.py`; the AI only proposes (`Judgment.proposed`) |
| What happens when the model is down / wrong? | `workflow.py` (repair edge, fallback), `ai/middleware.py: FaultMiddleware`, `tests/test_workflow.py` |
| Can the complaint text steer the AI? | `intake.py` (masking), `prompt.py` rule 2, set C "injection" cases |
| Why a replaced recall is not "two matches" | `evidence.py: link_replacements`, `decide.py` (superseded) |
| How is it evaluated? | `eval/build_sets.py`, `eval/run.py`, `docs/DATA_CARD.md` |
| Why is the search tool async? | `ai/tools.py` comment + `tests/test_workflow.py::test_concurrent_cases_share_the_connection_safely` |
| How do tests run without Azure? | `ai/clients.py: ScriptedChatClient`; cassettes replay recorded answers |
