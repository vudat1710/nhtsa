# Recall Match

**A tool for the quality analyst at a car maker.** An owner files a safety complaint. Is it a **known recall** (reply
to the owner), a **possible new safety problem** (send it to engineering), or **too vague** (ask the owner)? Recall
Match suggests the next step, drafts the message, and shows why: every quote it shows is checked word for word against
the original records, and fixed rules, not the AI, make the final call.

Built on public NHTSA data (owner complaints, recalls and defect investigations), Microsoft Agent Framework and Azure
OpenAI (or OpenAI). Runs without an AI model too, using stored results. One-page product brief:
[docs/BRIEF.md](docs/BRIEF.md)

## The key user journey

1. **Open the inbox.** 19 real complaints, the four demo cases (D1–D4) first.
2. **Open a ticket.** D1: a 2024 Hyundai Ioniq 5 showed "Power System Failure" and would not accelerate. The system
   checks it against the recalls that existed for that exact car on that day; with the AI on, each step shows as it
   goes.
3. **See the suggestion and why.** *"Matches recall 24V-868"*, with the owner's words next to the recall's words
   (both checked word for word), the older recall it replaced (24V-204), and 75 complaints that arrived after the fix.
4. **Act in one click.** *"Link to recall 24V-868 and reply to the owner + flag the remedy to engineering."* The reply
   is built from the recall's own text, not written by the AI. The action is saved against the suggestion that was on
   screen.
5. **Escalations collect** on the Emerging issues page for engineers. Operators see every AI run, failure drills and
   the test results at `/ops`.

The same journey on harder cases: **D2** same part, opposite failure (air bags that did *not* open) → escalate;
**D3** no recall yet → possible new problem, with earlier owners quoted; **D4** a one-line complaint ("Backup camara
is not working") → ask the owner, and the rules overrule the AI. If the AI fails, the ticket says "not checked by the
AI" and matches nothing.

## Run it

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```powershell
uv sync
uv run python -m app.data.fetch          # downloads ~380 MB of NHTSA files -> data/raw (seconds to minutes)
uv run python -m app.data.ingest         # builds data/nhtsa.db (~560 MB, about 1 minute)
uv run pytest                            # 133 tests, no network, no AI model needed

uv run uvicorn app.main:app --app-dir backend --port 8000
cd frontend; npm install; npm run dev    # http://localhost:5173  (operations portal: /ops)
```

**No Azure account? It still works.** On first start, the 19 inbox tickets open with their stored AI results
(`data/inbox_results.jsonl.gz`), so you can follow the whole journey above. The inbox is pinned to those 19
complaints (`data/inbox.json`), so it is the same whatever day you download NHTSA's files. A new check without the AI
is labelled "the AI is off": no recall is matched, and the recalls on the same part are listed to read first.

**With the AI** (to check tickets live): copy `.env.example` to `.env` and fill in one option.

| Option | Set in `.env` | Sign-in |
|---|---|---|
| Azure OpenAI / Azure AI Foundry | `NHTSA_AZURE_ENDPOINT` (`https://<resource>.services.ai.azure.com/openai/v1` or `https://<resource>.openai.azure.com/`), `NHTSA_DEPLOYMENT` | `az login` (your account needs the **Cognitive Services OpenAI User** role on the resource), or `NHTSA_AZURE_API_KEY` |
| OpenAI | `NHTSA_OPENAI_API_KEY`, `NHTSA_OPENAI_MODEL` | the key |

The model must support tool calling and strict structured output (JSON schema). Tested with `gpt-6.1-sol` on Azure,
with both endpoint forms, signed in with `az login` and with a key. The OpenAI option is checked up to the provider
(requests reach `api.openai.com` and a wrong key is rejected and labelled), not with a real OpenAI key. Keys stay in
`.env`, which git ignores. If the model fails or a key is wrong, tickets say "not checked by the AI" and match nothing.

---

# Details

[Why this problem](#why-this-problem) · [What the analyst sees and does](#what-the-analyst-sees-and-does) ·
[How it works](#how-it-works) · [Testing](#testing-what-is-checked) ·
[Tricky situations](#tricky-situations-it-handles-each-has-a-test-or-a-test-case) · [Limits](#limits) ·
[What's next](#whats-next) · [Data and license](#data-and-license) · the data and how it's used:
[docs/DATA_CARD.md](docs/DATA_CARD.md)

## Why this problem

A car maker's quality team reads thousands of owner complaints. Each one is either already covered by a recall, or it
might be a new problem. Both mistakes are expensive:

- If you call a new problem "known", nobody investigates it.
- If you send everything to engineering, the engineers drown.

The quick way, "same car, same part, so it's that recall", misses the details. It can't tell *"the air bag opened when
it shouldn't"* from *"the air bag did not open"* (demo D2). Owners also often pick a different part category than the
recall uses: 49% of the time when they name a recall.

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
check, step-by-step trail and actions. It is compared with every recall filed before today.

The car's make, model and year are picked from NHTSA's own list (1,905 makes). Recalls are found by exact name, so a
typed "Ioniq5" would find nothing and wrongly look like "no recall covers this". The system rejects names that aren't
on the list. In a real deployment, the VIN would fill these in.

### See how it got there

- **The step-by-step trail.** Every ticket shows what the system did, in order:
  1. read the complaint;
  2. looked up what was known on that date;
  3. *decided to search* earlier complaints for "…" (in the AI's own words), and what it found;
  4. compared the complaint with each recall, with quotes;
  5. checked every quote;
  6. made the decision by the rules.

  While a check runs, the same steps appear live. The trail is built by code from the stored run
  (`workspace/trail.py`), so it shows what really happened, not a story the AI tells afterwards.
- *Why not show the AI's own reasoning?* The AI step uses no reasoning at its tested settings, so there is no
  reasoning summary to show. A trail built from what the system actually did is always there and can be checked. The
  AI's own account of itself is neither.

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

There is no answer key for "which recall is right". The only labels are the recalls owners name, owners are sometimes
wrong, and the data has no VINs or repair records. So **no human-labelled accuracy number is reported**. The testing
is in three parts: how the **AI** does, compared with what owners believed; a **rough accuracy check** with the same
AI model as a blind judge (clearly an LLM-as-judge, not ground truth); and **guardrails**, tests that must hold on
every run.

**What it was tested on.** 471 test cases built from real complaints written by owners, frozen into test sets that
cover the situations the product must handle ([docs/DATA_CARD.md](docs/DATA_CARD.md)):
- 300 where the owner named a recall (the number is hidden from the system);
- 145 where no recall existed yet for that part (one was filed later);
- 26 tricky cases: real complaints with one thing changed on purpose (no model year, a two-word text, a hidden
  instruction, a car with no recalls).

Each complaint is replayed through the real product as if it had just arrived, and the results are checked by code;
only the rough accuracy check below uses an AI as the grader. (Prompt v3, run once on the current code:
`data/eval/reports/20261121-2211-abc-test-ai.json`.)

### How the AI does (agreement with owners, not accuracy)

Compared with the simple rule an analyst might use instead, "pick the newest recall on the same part", on the same
complaints (`app/eval/agreement.py`):

| 300 complaints where the owner named a recall | AI | Simple rule |
|---|---|---|
| Names a different recall than the owner | **6%** (17) | **18%** (55) |
| When it names one, it is the owner's | 89% (137 of 154) | 68% (117 of 172) |
| Asks for more detail instead of guessing | 30% (90) | never |

It disagrees with owners a third as often as the simple rule. The cost: on 30% of those complaints it asks for more
detail instead of guessing. The 145 complaints where no recall on the owner's part existed yet are not scored this
way: the product compares each complaint with every recall on the car, so a recall filed under another part can
rightly match.

### Accuracy, roughly: the same AI model as a blind judge (LLM-as-judge, not human labels)

The only deployed model (`gpt-6.1-sol`, the same one the product uses) labelled 443 of the 445 complaints above
without seeing the system's answer or the owner's recall: which recall describes the same failure, "none", or
"unclear" (`app/eval/llm_judge.py`; every label and its reason is stored in `data/eval/labels/`). Its standard is
stricter than the product's: the same failure, not only the same symptoms.

| | Result |
|---|---|
| When the system says "known recall", the judge names the same recall | **94%** (148 of 158) |
| When the judge says no recall fits, the system still said "known recall" (the costly mistake) | **4%** (8 of 206); in 6 of the 7 with an owner, the owner had named that same recall |
| When the judge names a recall, the system found it / asked for more detail instead | 80% (148 of 186) / 19% (35) |
| The judge agrees with the recall the owner named | 55% (164 of 298): it is stricter than owners |

Being the same model, the judge can share the system's blind spots, and it disagrees with owners almost half the time,
so these numbers are a second opinion, not accuracy. Real accuracy still needs two analysts labelling blind.

When the AI's answer can't be used: its first answer broke a check in **3 of 466** cases (all 3 corrected on the one
retry), and it gave no answer in **7 of 466** (2 blocked by Azure's content filter, 5 Azure rate limits). Those 7 were
labelled "not checked by the AI" and matched nothing. About 5,800 tokens per complaint; half finish within 12 s, 95%
within 43 s.

### Guardrails (tests run on the real AI outputs; a failure would be a bug)

| What must always hold | How | Result |
|---|---|---|
| **Every citation shown is real** | Every recall existed for that car on that date; every quote is in its source word for word; every number in the AI's summary appears in the records | 459 of 459 AI answers |
| **The process runs as designed** | 16 rules: steps in order, one retry then fallback, nothing dated after the complaint, only real recalls, searches limited, the trail matches what ran (`app/eval/trajectory.py`; each rule is tested to fail on a deliberately broken run) | 16 of 16, on every one of the 471 runs each rule applies to |
| **Tricky cases work as designed** | Unknown year → ask, no AI. Too short → ask, never escalate. A hidden instruction changes nothing: the same decision as without it (6 of 6). No recalls → nothing to compare | 21 of 21 |
| **A stored complaint is judged as a brand-new one** | Each complaint's evidence is gathered twice: as stored, and as a brand-new complaint with no id (`app/eval/as_new.py`) | Identical for 490 of 490 (test sets + inbox); none ever found itself |

**What this proves, and what it doesn't.** The guardrails prove that every quote and recall the analyst sees, and every
number in the AI's summary, is real, and that the designed process was followed. (The AI's one-line reason per recall
is shown as its own words; numbers in it are not checked.) They do **not** prove the conclusion: whether the owner's
words and the recall's words describe the same failure is the AI's judgment. Code can't check meaning, so the ticket
says so ("the AI judged it the same problem; please confirm"), the AI's summary is labelled as its own words, and the
analyst confirms before anything is closed. The agreement numbers compare that judgment with owners' beliefs; whether
the AI picks the right recall needs labels we don't have yet (see the plan below).

**Repeat it yourself.** The full results of every run are committed (`data/eval/results/*.jsonl.gz`):
- `uv run python -m app.eval.agreement` recomputes the comparison with owners and with the simple rule (no AI);
- `uv run python -m app.eval.llm_judge --report` rebuilds the LLM-as-judge comparison from the stored labels (no AI;
  without `--report` it labels every case again with the model);
- `uv run python -m app.eval.trajectory --run <name>` re-checks the process rules, without the AI;
- `uv run python -m app.eval.as_new` repeats the "stored complaint judged as a brand-new one" check (no AI, a few
  minutes);
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
  structured output). The cases it doesn't cover are handled in
  code, each with its own label: the AI refuses (`refused`), the answer is cut off (`incomplete`), Azure blocks the
  request (`content_filter`), or the AI is down (`unavailable`). Each is labelled "not checked by the AI", with no retry. The
  content (quotes, recall numbers, the numbers in the AI's summary) is still checked separately.
- **A broken answer, made-up recall or made-up number in the summary** → one retry, then "not checked by the AI": no
  recall is matched, the same-part recalls are listed to read, and a crash, fire or injury still escalates.
- **Looking into the future** → every lookup stops at the complaint's date. A recall filed the same day doesn't count.
- **Old recall texts in ALL CAPS** → shown in normal sentence case, without breaking abbreviations.

## Limits

- **No human-labelled accuracy yet.** The test set's "answer" is the recall the owner named. In the "no recall yet"
  set, the later recall turned out to be the same failure in about 2 of 3 cases (hand check of the first test sets).
  The current sets haven't been hand-checked; the only independent check is the same AI model as a judge.
- **Coverage needs the VIN.** A recall usually covers cars built between two dates (70% of vehicle recalls give
  them). The system finds recalls by model year, shows the build dates on the ticket, and the owner reply says the
  car *may* be covered and how to confirm.
- **A replacement stated only by the newer recall is missed.** "This recall (expands and) replaces NHTSA recall
  number 19V-350" isn't recognised yet. Of the 67 such pairs in NHTSA's recalls, 24 are still linked through the older
  recall's own "replaced by" wording (as with 24V-204 → 24V-868); 43 are not. A complaint matching both recalls of
  such a pair is shown with two matches, without "replaced", so the analyst must pick the newer one. The fix is one
  more wording rule and a test.
- **The quote check is literal.** A dropped negation is caught only when it is the word right before the quote ("Zero
  airbags were deployed" → "airbags were deployed" is rejected; "not that the airbags were deployed" one word further
  back is not). A number in the AI's summary passes if it appears anywhere in the evidence, not necessarily in the
  right place. The fix stays in code: check the whole sentence around the quote.
- **A severe complaint the AI calls only "possibly" a recall isn't escalated.** A crash, fire or injury escalates
  when the AI is unavailable, but when the AI answers "partial" (too vague to tell) the ticket asks the owner without
  escalating. 3 of the 471 test complaints (11479246, 11507897, 11517823). The fix is one rule and a test.
- **"The dealer has no parts" complaints** describe no failure. Today they're escalated or sent back to the owner
  instead of being linked to the recall the owner named.
- **Data shape:**
  - NHTSA's part categories overlap (`ENGINE` vs `ENGINE AND ENGINE COOLING`), so "same part" signals are weak.
  - Hotline write-ups (22% of complaints) are in the database but in no test set.
  - There are no repair records, so "complaints after the fix" can't tell a failed fix from an unrepaired car.
- **Speed.** About 12 seconds per complaint with our current Azure quota.

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
