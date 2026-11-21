# Recall Match

**A tool for the quality analyst at a car maker.** An owner files a safety complaint. Is it:

- a **known recall**? Reply to the owner and close it.
- the **same part failing in a different way**, or a **possible new safety problem**? Send it to engineering.
- **too vague**? Ask the owner for details.

Recall Match suggests the next step, drafts the message, and shows why. Every quote it shows is checked word for word
against the original records.

Built on public NHTSA data (owner complaints, recalls and defect investigations), Microsoft Agent Framework and Azure
OpenAI. One-page product brief: [docs/BRIEF.md](docs/BRIEF.md) · the data and how it's used:
[docs/DATA_CARD.md](docs/DATA_CARD.md).

## Why this problem

A car maker's quality team reads thousands of owner complaints. Each one is either already covered by a recall, or it
might be a new problem. Both mistakes are expensive:

- If you call a new problem "known", nobody investigates it.
- If you send everything to engineering, the engineers drown.

The quick way, "same car, same part, so it's that recall", misses the details. It can't tell *"the air bag opened when
it shouldn't"* from *"the air bag did not open"* (demo D2). Owners also often pick a different part category than the
recall uses: 49% of the time when they name a recall.

## Run it

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```powershell
uv sync
uv run python -m app.data.fetch          # downloads ~380 MB of NHTSA files -> data/raw
uv run python -m app.data.ingest         # builds data/nhtsa.db (~550 MB, about 1 minute)
uv run pytest                            # 126 tests, no network, no AI model needed

uv run uvicorn app.main:app --app-dir backend --port 8000
cd frontend; npm install; npm run dev    # http://localhost:5173  (operations portal: /ops)
```

**No Azure account? It still works.** On first start, the 19 inbox tickets open with their stored AI results
(`data/inbox_results.jsonl.gz`), so you can see each suggestion and how it was reached. A new check without the AI
is labelled "the AI is off": no recall is matched, the recalls on the same part are listed to read first, and follow-up
questions are switched off.

**With the AI:**
1. Copy `.env.example` to `.env`.
2. Set `NHTSA_AZURE_ENDPOINT` and `NHTSA_DEPLOYMENT`.
3. Run `az login` (sign-in with Entra ID, no keys).

## What the analyst sees and does

| The complaint turns out to be | Suggested next step (one click, can be edited) | What the analyst is shown |
|---|---|---|
| **A known recall** | Link the recall and reply to the owner. The reply is built **from the recall's own text**, not written by the AI, and says the car *may* be covered and how to confirm with the VIN | "The 2024 Ioniq 5 is in recall 24V-868 (2022–2024; 2024 models built Oct 4, 2021 – Oct 9, 2024): confirm with the VIN"; what the owner wrote next to what the recall says; older recalls it replaced |
| …and complaints keep coming after the fix | The same, **plus a flag to engineering** that the fix may not work | "85 earlier complaints: 10 before the recall, 75 after it" |
| **Same part, different problem**, or **no recall fits**, and there's a reason to worry | Send to engineering as an "emerging issue" (an existing one is suggested, or start a new one) | The reason: a crash, fire or injury; 3+ similar complaints in 12 months; 2+ earlier owners describing the same failure; or **the same failure already recalled on other model years** |
| …a single report with none of those reasons | **Record it and watch** (don't escalate yet) | The counts, next to the thresholds |
| **Too vague** | Ask the owner (using the AI's questions if it had any, otherwise a standard request) | The recall it might be, if any |

**When the AI can't answer** (it's down, refuses, is cut off or blocked, or fails the checks twice), the ticket says
"not checked by the AI" and **no recall is matched**: matching by part alone is exactly the shortcut that confuses
opposite failures. The recalls on the same part are listed to read first, "check it again with the AI" is offered, and
a crash, fire or injury still goes to engineering.

If the analyst picks something other than the suggestion, they write one line saying why. That's how the system
learns. Engineers see escalated complaints grouped on the **Emerging issues** page.

**Every action is tied to what the analyst saw.** The action names the AI run and the suggested action that were on
screen. If either changed since (the ticket was checked again, or a colleague opened a matching emerging issue, which
turns "open a new issue" into "add to the existing one"), it is refused and the new suggestion is shown. One action
at a time, from the first check to the last write; everything is checked first, then the status, the log and any
emerging issue are saved together (all or nothing). Whether the analyst followed the
suggestion is decided by the server, not the browser. A closed ticket must be reopened, with a reason; the same click
sent twice is saved once; and replies are recorded as **drafts** (nothing is sent to the owner).

The **operations portal** (`/ops`) is for the people who run the system. It shows every AI run step by step, failure
drills (AI down, broken answer, answer cut off, AI refuses) and the test results.

### Typing in a brand-new complaint

**+ New complaint** in the inbox accepts a complaint that isn't in NHTSA's data, like one that just came in by phone or
one a reviewer writes. It becomes a ticket dated **today** (shown as `typed #1`, `#2`, …) and gets exactly the same
check, step-by-step trail, actions and follow-up questions. It is compared with every recall filed before today.

The car's make, model and year are picked from NHTSA's own list (1,905 makes). Recalls are found by exact name, so a
typed "Ioniq5" would find nothing and wrongly look like "no recall covers this". The system rejects names that aren't
on the list. In a real deployment, the VIN would fill these in.

### See how it got there, then ask about it

- **The step-by-step trail.** Every ticket shows what the system did, in order:
  1. read the complaint;
  2. looked up what was known on that date;
  3. *decided to search* earlier complaints for "…" (in the AI's own words), and what it found;
  4. compared the complaint with each recall, with quotes;
  5. checked every quote;
  6. made the decision by the rules.

  While a check runs, the same steps appear live. The trail is built by code from the stored run
  (`workspace/trail.py`), so it shows what really happened, not a story the AI tells afterwards.
- **Ask about this case.** For example: "Why doesn't that recall cover this?" or "Have other owners reported the same
  failure?". The assistant only sees this case, and can search earlier complaints (only ones that came before it).
  - Every answer quotes its sources, and each quote is **checked word for word**.
  - If the records don't have the answer (VIN, repair history), it says *"not in the records"* instead of guessing.
  - It turns down unrelated requests.
  - If the analyst adds a new fact ("it's actually a 2023"), it says the case should be **checked again** rather
    than answering on old information.

  Each answer shows **how it answered**: the searches it ran, the quotes it used and the check result.
- *Why not show the AI's own reasoning?* We tried. The main AI step uses no reasoning at its tested settings, and the
  assistant gave a reasoning summary for only 1 of 21 test questions. A trail built from what the system actually did
  is always there and can be checked. The AI's own account of itself is neither.

### Demo (real complaints, in the inbox)

| | Complaint | What it shows |
|---|---|---|
| D1 | 2024 Hyundai Ioniq 5 loses drive power (ICCU) | A known recall. It also spots that an older recall was **replaced** by this one, and that **75 complaints came after the fix** → reply to the owner and flag it to engineering |
| D2 | 2022 Acura MDX: air bags **did not open** in a crash (fire, injury) | **Same part, opposite problem.** The only air-bag recall is about air bags opening when they *shouldn't*. The "same part" shortcut would call it known |
| D3 | 2018 Honda Ridgeline: rear camera dies because the tailgate pinches the wiring | **Possible new problem.** The AI finds 3 earlier owners describing the same thing. NHTSA issued a recall **348 days later** (shown afterwards, as hindsight) |
| D4 | 2019 Ford Mustang: "Backup camara is not working" | **Too vague, and the rules overrule the AI.** The AI says it's recall 22V-382. The rules see only 28 characters, decide "needs more detail", name the likely recall, and say the AI was overruled |
| D5 | D1 in the operations portal → failure drills | **It never guesses quietly.** "AI unavailable" → labelled "not checked by the AI", no recall matched. "Broken answer" → one retry, then the same checked answer. "Cut off at the token limit" (a real cut-off: the request allows only 16 tokens) and "AI refuses" (simulated) → labelled `incomplete` / `refused`, not checked by the AI |
| D6 | Operations portal → run `/ops/runs/3c68585fd6c9` (complaint 11705719) → "Run with AI" | **A real block by Azure:** its content filter rejects the request → labelled `content_filter`, not checked by the AI. Run `1602f7d69c63` (complaint 11752255) does the same |
| – | 2027 Ioniq 5: the same drive-power failure (a recent complaint in the inbox) | **A recall that may need extending.** No recall covers the 2027 model yet, but 24V-868 covers the same failure on 2022–2024 → escalate |

## How it works

```
complaint ─► intake ─► evidence ──► judge (AI) ─► verify ──► decide ─► workspace suggestion ─► analyst action
             code       code          AI           code        code        code (templates)
             hide       recalls on    reads +      checks      rules set   what to do, why,
             recall     this car      quotes;      quotes,     the answer  drafted messages,
             numbers,   before this   1 search     ids,                    reasons to escalate
             flag gaps  date          tool         numbers;
                                                   1 retry
                                                     │ fails twice
                                                     └──► "not checked by the AI" (no recall matched)
```

A Microsoft Agent Framework workflow connects the five steps, including the retry and the fallback. Only the `judge`
step calls the AI. The workspace layer turns a checked result into what the analyst sees.

| Choice | Why | What it costs |
|---|---|---|
| The recalls to compare come from a database query (this car, before this date), not from the AI or a vector search | About 6 per complaint, and the AI can't invent a recall | A recall filed under a different car name is missed |
| Quotes are the evidence, checked word for word (and a quote can't drop a "no" or "zero") | The analyst sees *why*, in context, and code can check it | Owners write messily; quotes must be at least 3 words |
| Rules make the final call; the AI only suggests | Confidence follows written rules, so it means the same thing every time; the costly decision stays in code | Less flexible |
| Owner replies are templates filled from the recall's text | A reply can never promise a fix the recall doesn't offer | Less natural wording |
| Escalate only with a stated reason | Engineers' time is the scarcest resource | The thresholds are judgment calls, not yet tuned (next: tune them on how many escalations engineers confirm) |
| Separate screens for analysts and for operators | Analysts act, builders audit: different words, different screens | Two interfaces to maintain |
| SQLite and full-text search; no vector database, no multiple agents | One file, repeatable, easy to trace | The similar-complaint search is keyword-based (the AI writes the search words) |

## Testing: what is checked

**We only report what can be proven by checking**: against the records, against our own rules, or by measuring.
There is no answer key for "which recall is right". The only labels are the recalls owners name, owners are sometimes
wrong, and the data has no VINs or repair records. So **no accuracy number is reported**.

**What it was tested on.** 471 real complaints written by owners, frozen into test sets that cover the situations the
product must handle ([docs/DATA_CARD.md](docs/DATA_CARD.md)):
- the owner named a recall (the number is hidden from the system);
- no recall existed yet for that part;
- 26 tricky cases.

Each complaint is replayed through the real product as if it had just arrived, and the results are checked by code.
No AI grades the AI. (Prompt v3, run once: `data/eval/reports/20261120-2209-abc-test-ai.json`.)

| What we check | How | Result |
|---|---|---|
| **Every citation is real** | Every recall existed for that car on that date; every quote is in its source word for word; every number exists | Every AI answer passed (464 of 464). 2 more were blocked by Azure's content filter and were labelled "not checked by the AI" |
| **The process runs correctly** | 16 rules checked on every stored run: steps in order, one retry then fallback, nothing dated after the complaint, only real recalls, searches limited, the trail matches what ran (`app/eval/trajectory.py`; each rule is tested to fail on a deliberately broken run) | 16 of 16, on all 471 runs |
| **Tricky cases work as designed** | Unknown year → ask, no AI. Too short → ask, never escalate. Hidden instructions never reach the answer. No recalls → nothing to compare | 21 of 21 |
| **It never sees the future, or itself** | Each complaint's evidence is gathered twice: as stored, and as a brand-new complaint with no id (`app/eval/as_new.py`) | Identical for 490 of 490 (test sets + inbox); none ever found itself |
| **Follow-up answers stick to the records** | 21 questions on the demo tickets (`app/eval/ask_eval.py`) | Quotes checked: 20 of 20 answers (1 more was blocked by Azure). Says "not in the records" when the data lacks it (repair history, crash data, VIN): 4 of 4. Turns down unrelated requests: 2 of 2. Asks for a re-check after a new fact: 1 of 1 |
| **Cost and speed** | Measured | About 5,000 tokens; half finish within 10 s, 95% within 35 s |

**What this proves, and what it doesn't.** The checks prove that every quote, recall and number the analyst sees is
real, and that the designed process was followed. They do **not** prove the conclusion: whether the owner's words and
the recall's words describe the same failure is the AI's judgment. Code can't check meaning, so the ticket says so
("the AI judged it the same problem; please confirm"), the AI's summary is labelled as its own words, and the analyst
confirms before anything is closed. Whether the AI picks the right recall needs labels we don't have yet (see the plan
below). Why reading the text beats matching part names is shown on real cases (demo D2).

**Repeat it yourself.** The full results of every run are committed (`data/eval/results/*.jsonl.gz`):
- `uv run python -m app.eval.trajectory --run <name>` re-checks the process rules, without the AI;
- `uv run python -m app.eval.as_new` repeats the "never sees the future" check (no AI, a few minutes);
- `uv run python -m app.eval.run` runs everything again (needs the AI); `--report <name>` rebuilds a stored run's
  report without the AI;
- the test sets rebuild identically (`app.eval.build_sets`).

## Tricky situations it handles (each has a test or a test case)

- **The owner writes the recall number** → it is hidden before the AI sees it, so the answer can't leak in.
- **A hotline note puts the part name after the number** (`16V248000 (Power Train)`) → hidden too.
- **Instructions hidden in the complaint** → treated as text. Any recall that wasn't on the list is rejected.
- **A recall replaced by a newer one** ("replaced by NHTSA recall number 24V-868", "supersedes recalls 13V-029 and
  14V-147", "Recall 21V469 supersedes this recall") → the newer one is used, not "two matches". Read from the recall
  texts' own wording (136 replacement pairs across NHTSA's recalls). They are only linked when both applied to the car
  on the complaint's date and the newer one wasn't filed first.
- **Same part, opposite problem** → not "known"; escalated, with the difference quoted.
- **A quote that drops "Zero"** ("[Zero] airbags were deployed") → rejected (this happened in a live run).
- **Complaints keep coming after a fix** → reply and flag. The data can't tell a failed fix from a car that was never
  repaired.
- **The same failure was recalled on other model years** → flagged as a recall that may need extending.
- **Unknown year / unknown part / two-word complaint** → ask the owner / compare all recalls / ask the owner.
- **A typed car name NHTSA doesn't use** ("Ioniq5") → rejected with a message. The form only offers NHTSA's names.
- **The answer's format** → Azure is told the exact format and enforces it on every finished answer (strict
  structured output), for the main AI step and the follow-up assistant. The cases that doesn't cover are handled in
  code, each with its own label: the AI refuses (`refused`), the answer is cut off (`incomplete`), Azure blocks the
  request (`content_filter`), or the AI is down (`unavailable`). Each is labelled "not checked by the AI", with no retry. The
  content (quotes, recall numbers, numbers) is still checked separately.
- **A broken answer, made-up recall or made-up number** → one retry, then "not checked by the AI": no recall is
  matched, the same-part recalls are listed to read, and a crash, fire or injury still escalates.
- **Looking into the future** → every lookup stops at the complaint's date. A recall filed the same day doesn't count.
- **Old recall texts in ALL CAPS** → shown in normal sentence case, without breaking abbreviations.
- **A follow-up question the records can't answer** (VIN, was it repaired?) → "not in the records", no guess.
- **A follow-up that changes the facts** ("it's a 2023, not a 2022") → flagged for a re-check, not answered on old
  information.
- **A follow-up blocked by Azure's content filter** → shown as blocked, not as an error or an empty answer.

## Limits

- **No accuracy number yet.** The test set's "answer" is the recall the owner named. In the "no recall yet" set, the
  later recall turned out to be the same failure in about 2 of 3 cases (hand check of the first test sets). The
  current sets haven't been hand-checked yet.
- **Coverage needs the VIN.** A recall usually covers cars built between two dates (70% of vehicle recalls give
  them). The system finds recalls by model year, shows the build dates on the ticket, and the owner reply says the
  car *may* be covered and how to confirm.
- **"The dealer has no parts" complaints** describe no failure. Today they're escalated or sent back to the owner
  instead of being linked to the recall the owner named.
- **Data shape:**
  - NHTSA's part categories overlap (`ENGINE` vs `ENGINE AND ENGINE COOLING`), so "same part" signals are weak.
  - Hotline write-ups (22% of complaints) are in the database but in no test set.
  - There are no repair records, so "complaints after the fix" can't tell a failed fix from an unrepaired car.
- **Speed.** About 10 seconds per complaint with our current Azure quota.

## What's next

**Testing**, in this order:
1. **A real accuracy number:** two people label a sample blind (which recall fits, without seeing the AI's answer).
   How often they agree with each other sets the ceiling, and it becomes the first answer key to score against.
2. **Consistency:** run each test case three times and see how often the answer changes.
3. **Newer complaints:** test on complaints from after the AI model's training data, so it can't have seen them.
4. **Real-use numbers from the workspace's own log (already stored):**
   - how often analysts change the suggestion, and why;
   - time per complaint;
   - how many escalations engineers confirm.

   Analysts' changes become the next labels.

**Product:**
- link "dealer has no parts" complaints to the recall the owner named;
- VIN lookup (car, build date, open recalls);
- group related escalations;
- alert when complaints keep coming after a fix;
- learn the escalation thresholds from what engineers confirm;
- a cheaper first pass for large batches.

## Data and license

NHTSA data is public domain (US government work). See [docs/DATA_CARD.md](docs/DATA_CARD.md).
