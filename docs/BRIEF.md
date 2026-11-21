# Recall Match: product brief

**In one line:** for every vehicle-safety complaint, Recall Match tells the quality analyst what it is and what to do
next: a known recall, the same part failing in a different way, a possible new safety problem, or too little detail.
Every claim comes with a quote the analyst can check.

## Who it's for, and what hurts today

**Quality analysts** at a car maker or parts supplier read hundreds of owner complaints a week. When something looks
new, they pass it to **safety engineers**.

1. **It's slow.** Each complaint has to be compared with every recall on that exact car (about 6). Recalls are written
   in engineering language; owners describe what they saw and felt.
2. **The quick way is risky.** "Same car, same part, so it's that recall" misses the details. An air bag that *didn't*
   open is not the same problem as one that opened when it *shouldn't*. And owners often pick a different part
   category than the recall uses (49% of the time when they name a recall). The worst mistake is calling a new
   problem "known", because then nobody investigates it.
3. **AI answers are hard to trust** unless the analyst can see where each claim comes from.

## What it does, and why it's built this way

A work queue that suggests **the next action** for each complaint. It is not a chatbot. It works in five steps:

1. **The system finds the evidence:** the recalls that existed for that exact car on the day the complaint arrived,
   and how many similar complaints came before.
2. **The AI reads:** it compares the complaint with each recall, quotes both, and can search earlier complaints.
3. **The system checks:** every quote must match the original text exactly (including small words like "no"), and
   every recall and number must be real. A failed check gets one retry. After that, simple rules answer, clearly
   labelled.
4. **Fixed rules make the final call**, not the AI.
5. **The analyst acts in one click:**
   - link the recall and send a reply written from the recall's own text;
   - flag a fix that doesn't seem to work;
   - escalate with a stated reason;
   - or ask the owner for details.

The analyst can also see each step the system took, ask follow-up questions that are answered only from this case,
and enter a brand-new complaint.

**Why this way:** the expensive decision is made by rules the team can read, not by the AI, and every claim can be
checked in seconds.

## How we'll know it works

There is no answer key yet for "which recall is right": the only labels are the recalls owners name, and owners are
sometimes wrong. So this brief only reports what can be proven by checking. Accuracy is a goal to meet before launch,
not yet measured.

**Tested on** 471 real owner complaints, each replayed as if it had just arrived.

| | What we measure | Goal | Result |
|---|---|---|---|
| **Proven now** | Every quote, recall and number in an answer is real | Always, or a clearly labelled rules answer | Every AI answer passed (464 of 464); 2 blocked by Azure's filter got a labelled rules answer |
| | The process runs correctly (right order, nothing from the future, trail matches what ran) | Every run | 16 of 16 rules held on all 471 runs |
| | Tricky cases (no model year, two-word complaint, hidden instructions, no recalls) | All handled as designed | 21 of 21 |
| **Before launch** | Two analysts label a sample blind: how often they agree with "known recall"; how often a new problem is wrongly called "known" | Agreed with the quality team (proposed: at least 95%; at most 2%) | Not measured yet |
| **After launch** | How often analysts change the suggestion and why, time per complaint, how many escalations engineers confirm | Better than today's manual work | Every action and reason is logged from day one |

## Assumptions and limits

- **Assumes:**
  - car names are spelled the way NHTSA spells them (in production, the VIN fills this in);
  - recall texts describe the failure;
  - an analyst reviews every suggestion.
  
  Public NHTSA data stands in for a car maker's own complaint feeds.
- **No accuracy number yet.** Next: a blind sample labelled by two people. Then check that answers stay the same
  when re-run, and test on complaints newer than the AI model's training data.
- **Coverage needs the VIN.** A recall covers cars built between two dates, so the reply says the car *may* be
  covered and how to confirm with the VIN.
- **Not handled yet:** complaints like "the dealer has no parts for the recall repair" describe no failure. Today
  they are escalated or sent back to the owner instead of linked to the recall.
- **Data gaps:**
  - complaints only from 2020 on (recalls go back to 1966);
  - no repair records;
  - NHTSA's part categories overlap.
