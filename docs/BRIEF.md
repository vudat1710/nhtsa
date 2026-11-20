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

An evidence-first assistant, not a chatbot:

- **Code finds the evidence**: only recalls covering that exact vehicle, filed before the complaint arrived; earlier
  complaint counts; investigations. The AI cannot cite anything else.
- **The AI does the reading**: one call compares the complaint with each candidate recall and must back every
  judgment with word-for-word quotes from both. It may search earlier complaints to find a pattern.
- **Code checks everything**: ids, quotes (including that a quote doesn't drop a "no"), numbers. One repair; then a
  labelled rules-only fallback.
- **Rules decide**: outcome, confidence, and escalation follow written rules with plain-language reasons; the AI only
  proposes. Engineer decisions are stored and become labels.

*Why this design:* the costly error is a false "known recall", so control of that decision sits in code, and every
claim is checkable by a person in seconds (highlighted quotes in context).

## Success criteria

| | Metric | Target (prototype) | How measured |
|---|---|---|---|
| Safety | Confidently-wrong "known recall" (sets A+B) | Well below the rules baseline (baseline: RESULT_BASE_WRONG) | Frozen real-data test sets, 95% CI |
| Usefulness | Agreement with the owner's cited recall (set A) | Report, and adjudicate disagreements | Set A + hand-adjudicated sample |
| Escalation | Complaints with no recall yet that are escalated (set B) | ≥ 90% | Set B |
| Trust | Final answers with every quote/id/number verified | 100% (by construction); first-answer failure rate reported | Verifier |
| Calibration | "High confidence" answers that are right | ≥ 90% | By confidence level |
| Operations | Cost and latency per complaint | Report (~6k tokens, ~10 s) | Run logs |
| In production | Analyst override rate; time to triage; share of escalations engineers confirm; new defects found before a recall | Baseline then improve | Review records |

## Assumptions

- Complaints are tagged with make/model/year as NHTSA spells them (production: VIN decode).
- Recall text (defect, consequence, remedy) describes the failure well enough to compare with owner symptoms.
- An analyst reviews every answer; the tool prioritizes and explains, it does not close cases alone.
- Public NHTSA data is a fair stand-in for an automaker's own complaint and warranty feeds.

## Limitations

- **Labels.** "Known recall" labels exist only where the owner cited a recall (owners are sometimes wrong); "new
  defect" labels are noisy (~65% the same failure on hand check). Engineer decisions should replace both.
- **Coverage.** Complaints from 2020, recalls from 2010; no repair records, so "complaints after the remedy" cannot
  distinguish a failed fix from an unrepaired car.
- **Throughput.** ~10 s per complaint at our model quota; bulk triage needs a higher quota or a cheaper first pass.
- **Not built:** clustering escalations into investigations, alerting, multi-language complaints, VIN decoding.
