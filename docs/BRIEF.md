# Recall Match: product brief

**One line.** For each vehicle-safety complaint, tell the field-quality analyst whether it is a known recall, a
different failure of the same part, a possible new defect, or too vague, with every claim backed by a checkable quote.

## Target users and pain points

**Field-quality analysts** at an automaker or supplier triage hundreds of owner complaints a week;
**product-safety engineers** receive their escalations.

1. **Matching is slow.** Each complaint must be compared with every recall on that exact vehicle (median 6), written in
   engineering language, while owners describe symptoms.
2. **The shortcut is dangerous.** "Same vehicle + same component = known recall" names a different recall than the
   owner cited 21% of the time on owner-written complaints, and cannot tell opposite failures apart (air bag deploys unexpectedly vs not at all).
   A new defect filed as "known" is the costliest error.
3. **AI answers are hard to trust** without sources the analyst can check.

## Solution and why

A workspace that suggests the **next action** per complaint, not a chatbot. **Code finds the evidence** (only recalls
on that vehicle filed *before* the complaint; earlier complaint counts). **The AI reads**: it compares the complaint
with each candidate recall, quoting both word for word, and may search earlier complaints. **Code checks, rules
decide**: ids, quotes (including a dropped "no") and numbers are verified; one repair turn, then a labelled rules-only
fallback. **The analyst acts in one click** (link the recall with a reply drafted from its own text, flag a failing
remedy, escalate with a stated reason, or ask the owner), sees how the agent investigated, and can ask follow-ups
answered only from the case. *Why:* the costly error stays in code, and every claim is checkable in seconds.

## Success criteria

**No ground truth** says which recall is right (set A's label is the *owner's* citation), so results are split into
objective checks and agreement with the owner (468 frozen owner-written test cases):

| Metric | Target | Result (AI · rules baseline) |
|---|---|---|
| **Objective:** final answers with every id, quote, number verified | 100% | 100% (0 of 463 needed a repair, 0 fallbacks) |
| Objective: workflow rules hold (path, evidence, tool use, trail) | All | 20/20 invariants, all 468 runs; ~10 s each |
| Objective: claims a known recall when none existed on the owner's part | Low | 5% (7/142) · 0% |
| Objective: stress cases (unknown year/part, 2 words, injected instructions) | All | 26/26 · 21/26 |
| **Agreement with owner:** names a recall other than the owner's | Below baseline | **8%** [5–12] · 21% |
| Agreement: "known recall" answers that are the owner's recall | Above baseline | **86%** · 66% |
| Agreement: "high confidence" answers matching the label | ≥ 90% | **95%** (59/62) |
| **In production:** override rate, time to triage, escalations engineers confirm | Improve on baseline | All actions and override reasons logged |

## Assumptions and limitations

- **Assumes** NHTSA make/model/year spelling (production: VIN decode), recall text that describes the failure, and an
  analyst reviewing every suggestion; public NHTSA data stands in for an automaker's own complaint feeds.
- **No accuracy number yet.** Next: a blind sample labelled by two people; analyst overrides as ongoing labels.
- **Next rule:** "dealer can't do the recall repair" complaints (no failure) are escalated, not linked to the recall.
- **Data gaps:** complaints since 2020, recalls since 2010, no repair records; overlapping component categories.
