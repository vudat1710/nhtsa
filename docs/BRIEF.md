# Recall Match: product brief

**In one line:** for each owner complaint about a vehicle-safety problem, Recall Match tells the quality analyst if
it's a known recall, a possible new problem or too vague, and what to do next, with quotes they can check.

## Target users

- **Quality analysts** at a car maker read hundreds of owner complaints a week and decide what each one is.
- **Safety engineers** receive the ones that may be new problems.

## Pain points

1. **It's slow.** Each complaint must be compared with every recall on that exact car (about 6), written in engineering
   language.
2. **The shortcut is risky.** "Same car, same part, so it's that recall" can't tell an air bag that *didn't* open from
   one that opened when it *shouldn't*. Calling a new problem "known" means nobody investigates it.
3. **AI is hard to trust** when you can't see where each claim comes from.

## Our solution, and why

A work queue that suggests the next action for each complaint. Not a chatbot.

1. **Code finds the evidence:** the recalls on that exact car on the day the complaint arrived, and earlier similar
   complaints.
2. **The AI compares** the complaint with each recall and quotes both.
3. **Code checks every quote and recall** against the records. If the AI fails, the ticket says "not checked by the AI"
   and matches no recall.
4. **Fixed rules decide, and the analyst confirms in one click:** link the recall with a drafted reply to the owner,
   escalate to engineering, or ask the owner. Each action is saved against what the analyst saw.

**Why:** the costly decision stays with rules the team can read and a person who confirms, and every claim can be
checked in seconds.

## Success criteria

Tested on 471 cases from real owner complaints, each replayed as if new. With no answer key yet, today's numbers
compare the AI with what owners believed, not with the truth.

| What we measure | Target | Today |
|---|---|---|
| Every quote and recall shown is real | Always | 459 of 459 AI answers |
| Picks a different recall than the owner named | No target: a comparison | 6%, vs 18% for the "same part" shortcut |
| Agrees with two analysts labelling blind | 95% or more (proposed) | Not measured yet |
| Calls a new problem "known" (blind labels) | 2% or less (proposed) | Not measured yet |

After launch, also tracked: analyst overrides, time per complaint, and escalations confirmed by engineers.

## Assumptions and limitations

- An analyst reviews every suggestion; nothing is closed by the AI alone.
- Public NHTSA data stands in for a car maker's own complaints, and car names follow NHTSA's spelling (in production,
  the VIN would fill them in).
- No accuracy number yet: the only labels are owners' beliefs. Next: a sample labelled blind by two analysts.
- A recall covers certain build dates, so replies say the car *may* be covered; only the VIN can confirm it.
- No repair records: "complaints after the fix" can't tell a fix that fails from a car that was never repaired.
