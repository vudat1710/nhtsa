# Code tour

One page to find your way around. Every folder has one responsibility; every pipeline step is one file.

## Map

```
backend/app/
  config.py              settings from .env (NHTSA_*); nothing secret (Azure auth = az login)
  models.py              the data shapes = the contract between steps:
                         Complaint → Intake → Evidence → Judgment (AI) → Decision, stored together as one Result
  main.py                FastAPI app: /api (workspace) and /api/ops (operations portal)

  data/                  NHTSA data access only. No decisions.
    fetch.py · ingest.py download; flat files → data/nhtsa.db (explicit schema, text repair, full-text index)
    queries.py           read-only queries; the as_of rule (no look-ahead) lives here and only here

  pipeline/              one complaint → one decision (the system's view)
    workflow.py          the MAF graph: order of steps, repair loop, fallback edge. No logic of its own
    intake.py            1 code  mask recall numbers, flag unknown year / component / short text / severity
    evidence.py          2 code  candidate recalls (+ which replaced which, model years), counts, investigations
    judge.py             3 AI    build the agent for one case and ask it (never raises)
    verify.py            4 code  ids exist, quotes word for word (and keep their negation), numbers exist
    decide.py            5 code  outcome + confidence rules; the rules-only baseline / fallback

  ai/                    everything about the model, nothing about recalls
    prompt.py            instructions (versioned, with the reason for each version), case/repair messages, parsing
    tools.py             search_complaints: the agent's only tool (read-only, as_of-bounded, async)
    clients.py           live Azure OpenAI / offline / scripted (tests) clients + LlmSetup
    middleware.py        record/replay (keyed on meaningful fields only), fault injection, tool-call trace

  workspace/             the analyst's view of a decision. Pure code on a stored Result; no model calls
    suggest.py           what it is, why (in field-quality words), pattern, escalation reasons, actions
    messages.py          owner replies and questions: templates over the recall's own text
    actions.py           apply an analyst action (validated against the case's evidence), log it

  store/                 data/app.db
    results.py           every AI run, whole (the audit record)
    tickets.py           what people did: ticket status, actions, emerging issues
    reset.py             clear what people did (keep runs) for a fresh demo

  api/                   HTTP only; calls the layers above
    workspace.py         inbox, ticket, check (live progress), actions, emerging issues
    ops.py               runs, run detail, failure drills, sandbox, evaluation reports
    streaming.py · deps.py

  eval/                  build_sets.py (frozen real-data sets) · run.py (score + report + full results)
                         rescore.py (re-apply rules to stored answers) · adjudicate.py (who was right?)
                         prune_cassettes.py (drop recordings no run uses)

backend/tests/           one file per area; conftest.py is a tiny NHTSA world (same schema)
frontend/src/
  api/                   client.ts (workspace + ops clients, progress stream), types.ts (mirrors models.py)
  workspace/             Inbox, Ticket (SuggestionView + ActionPanel), Emerging issues: the analyst's product
  ops/                   AI runs, run detail (decision, recall checks, evidence, audit trail), drills, sandbox,
                         evaluation: for the people who build and run it
  shared/ · lib/         badges, quote highlighting, plain-word labels
data/eval/               frozen sets, demo.json, runs/ reports/ results/ adjudication/
docs/                    BRIEF.md, DATA_CARD.md, this file
```

## One ticket, traced

The analyst opens the Honda Ridgeline ticket (`/tickets/11443328`):

1. `api/workspace.py: check` streams `pipeline/workflow.py: run`.
2. **intake** masks recall numbers and sets flags. **evidence** asks `queries.recalls_for(vehicle, as_of=2021-12-10)`
   → 4 recalls filed before that date; counts 4 earlier camera complaints; builds the agent.
3. **judge**: the agent reads the masked complaint and the 4 recalls, calls `search_complaints` with its own wording,
   and answers JSON: no recall fits; 3 earlier owners quoted.
4. **verify** checks every id, every quote (in its own source, no dropped negation), every number. Pass.
5. **decide**: no "same" checks → `possible_new`, medium confidence, flag `pattern`.
6. The Result is stored (`store/results.py`). `workspace/suggest.py` turns it into the analyst's view: headline, why
   (the 3 owner quotes), escalation reasons (≥2 earlier owners, ≥3 complaints in 12 months), and actions
   ("open emerging issue …" pre-filled).
7. The analyst confirms → `workspace/actions.py` validates, creates the issue, logs the action → Emerging issues page.

## Where to look when asked…

| Question | File |
|---|---|
| How do you stop look-ahead? | `data/queries.py` (`< as_of` everywhere), `tests/test_queries.py` |
| How do you know a quote is real? | `pipeline/verify.py: quote_problem`, `tests/test_verify_decide.py` |
| Who decides, the AI or code? | `pipeline/decide.py`; the AI only proposes (`Judgment.proposed`) |
| Why didn't this get escalated? | `workspace/suggest.py: escalation_reasons` (thresholds at the top) |
| Can the reply to the owner be wrong? | `workspace/messages.py`: templates over the recall's own remedy text |
| What happens when the model is down / wrong? | `workflow.py` (repair, fallback), `ai/middleware.py: FaultMiddleware`, `tests/test_workflow.py` |
| Can the complaint text steer the AI? | `intake.py` (masking), `ai/prompt.py` rule 2, set C injection cases |
| How is it evaluated, and can I reproduce it? | `eval/run.py`, `eval/rescore.py` (from committed results), `docs/DATA_CARD.md` |
| Why is the search tool async? | `ai/tools.py` + `tests/test_workflow.py::test_concurrent_cases_share_the_connection_safely` |
| Why are recordings keyed on some fields only? | `ai/middleware.py: cassette_key` + `tests/test_replay.py` |
