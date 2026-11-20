# Recall Match: product brief

**One line.** For each vehicle-safety complaint, tell the field-quality analyst whether it is a known recall, the same
part failing differently, a possible new defect, or too vague, with every claim traced to a checked quote.

## Target users

- **Field-quality analyst (primary)** at an automaker or large supplier: triages hundreds of owner complaints a week
  (NHTSA receives ~100,000 a year).
- **Product-safety engineer (secondary)**: receives escalations; decides whether to open an investigation.
- **Safety/compliance lead**: needs to trust that nothing new is being missed, and to show regulators why.

## Pain points

1. **Matching is slow and inconsistent.** Each complaint must be compared against every recall on that exact vehicle
   (median 6, up to 40+), written in engineering language, while owners describe symptoms ("lost power", "light came
   on").
2. **The easy shortcut is dangerous.** "Same vehicle + same component = known recall" is confidently wrong about 1 in
   5 times on real data, and cannot tell opposite failures apart (air bag *deploys unexpectedly* vs *does not deploy*).
   A new defect wrongly filed as "known" is the costliest error: it is the one that becomes a crash and a recall.
3. **Signals hide in the noise.** Complaints that continue after a remedy, or a cluster of similar complaints with no
   recall, are what engineering needs to see first, and they are buried.
4. **AI answers are hard to trust.** A fluent summary without checkable sources is not usable for safety decisions.

## Solution and why

A workspace that suggests the **next action** for each complaint (not a chatbot), backed by checkable evidence:

- **Code finds the evidence**: only recalls covering that exact vehicle, filed before the complaint arrived; earlier
  complaint counts; investigations. The AI cannot cite anything else.
- **The AI does the reading**: it compares the complaint with each candidate recall and must back every judgment with
  word-for-word quotes from both. It may search earlier complaints for the same failure.
- **Code checks everything** (ids, quotes, that a quote doesn't drop a "no", numbers), then **rules decide** the
  outcome and confidence. One repair, then a labelled rules-only fallback.
- **The analyst acts in one click**: link the recall and send a reply drafted *from the recall's own text*; flag a
  remedy that isn't holding; escalate to an emerging issue *only with a stated reason*; record and watch single
  reports; or ask the owner the AI's questions. Disagreeing asks for one line of why. Builders audit every run in a
  separate operations portal.

*Why this design:* the costly error is a false "known recall", so that decision sits in code; every claim is
checkable in seconds; engineers' time is protected by escalating only with a reason.

## Success criteria

| | Metric | Target | Prototype result (frozen real-data test sets) |
|---|---|---|---|
| Safety | Names a recall other than the owner's (set A) | Well below the rules baseline (19%) | **7%** [5–10] |
| Usefulness | "Known recall" answers that match the owner's recall | > baseline (79%) | **88%** [83–92] |
| Trust | "High confidence" answers that are right | ≥ 90% | **94%** [88–97] |
| Trust | Final answers with every quote/id/number verified | 100% | 100% by construction; 1 of 563 first answers needed a repair |
| Escalation | No-recall-yet complaints escalated or sent back to the owner (set B) | ≥ 90% | 95% |
| Robustness | Stress cases (unknown year/part, two words, injected instructions) | All | 25/26 |
| Cost | Per complaint | Report | ~5,400 tokens, ~13 s |
| In production | Analyst override rate · time to triage · share of escalations engineers confirm · new defects found before a recall | Baseline, then improve | Logged from day one (every action stored) |

Hand check of disagreements: in 30 sampled cases where the AI disagreed with the owner, the AI was right 12 times,
the owner 7, unclear 11; all 7 owner-right cases were "can't get the recall repair" complaints (next step below).

## Assumptions

- Complaints are tagged with make/model/year as NHTSA spells them (production: VIN decode).
- Recall text (defect, consequence, remedy) describes the failure well enough to compare with owner symptoms.
- An analyst reviews every answer; the tool prioritizes and explains, it does not close cases alone.
- Public NHTSA data is a fair stand-in for an automaker's own complaint and warranty feeds.

## Limitations

- **Remedy-access complaints** ("dealer can't do the recall repair", no failure described) are escalated or sent back
  instead of linked to the cited recall: the main finding of the hand check, and the next thing to build.
- **Labels.** "Known recall" labels exist only where the owner cited a recall (owners are sometimes wrong); "new
  defect" labels are noisy (~65% the same failure on hand check). Analyst and engineer actions should replace both.
- **Coverage.** Complaints from 2020, recalls from 2010; no repair records, so "complaints after the remedy" cannot
  distinguish a failed fix from an unrepaired car.
- **Throughput.** ~13 s per complaint at our model quota; bulk triage needs a higher quota or a cheaper first pass.
- **Not built:** automatic clustering of escalations, alerting, multi-language complaints, VIN decoding; run-to-run
  stability not yet measured.
