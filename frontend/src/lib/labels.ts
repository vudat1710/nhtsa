// Plain words for everything the backend returns as a code. One place, so the UI says the same thing everywhere.
import type { Confidence, Decision, Outcome } from '../api/types'

/** NHTSA complaints keep their ODINO; complaints typed in by an analyst have negative ticket numbers. */
export function ticketName(odino: number | null): string {
  if (odino == null) return 'typed in'
  return odino < 0 ? `typed #${-odino}` : String(odino)
}

export const OUTCOME: Record<Outcome, { label: string; tone: string; action: string }> = {
  known_recall: { label: 'Known recall', tone: 'ok', action: 'Point the owner to the recall remedy.' },
  related_different: { label: 'Related, different failure', tone: 'warn', action: 'Escalate to an engineer: a recall covers this part, but not this failure.' },
  possible_new: { label: 'Possible new issue', tone: 'alert', action: 'Escalate to an engineer: no recall describes this failure.' },
  needs_info: { label: 'Needs more information', tone: 'info', action: 'Ask the owner the questions below before deciding.' },
}

export const CONFIDENCE: Record<Confidence, string> = {
  high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence',
}

export const SOURCE: Record<Decision['source'], { label: string; note: string }> = {
  ai_verified: { label: 'AI, verified', note: 'Every quote and number was checked against the source records.' },
  ai_repaired: { label: 'AI, verified after one correction', note: 'The first answer failed a check; the AI corrected it and the correction passed.' },
  fallback: { label: 'Not AI-verified', note: 'The AI failed or its answer failed verification twice; this is the rules-only answer.' },
  rules: { label: 'Rules only', note: 'Run without the AI.' },
}

export const FLAG: Record<string, string> = {
  severe: 'Crash, fire or injury reported',
  after_remedy: 'Complaints continue after the recall remedy',
  superseded: 'An older recall was replaced by a newer one',
  pattern: 'Several similar complaints in the last 12 months',
  ai_disagreed: 'The rules overrode the AI’s proposal',
}

export const INTAKE_FLAG: Record<string, string> = {
  unknown_year: 'Model year unknown',
  unknown_component: 'Owner did not choose a component',
  short_text: 'Very short description',
  severe: 'Crash, fire or injury',
}

export const VERDICT: Record<string, string> = {
  same: 'Same failure', partial: 'Possibly (too vague to tell)', different: 'Same part, different failure',
}

export const STEP: Record<string, string> = {
  intake: 'Intake: mask recall numbers, check for missing details',
  evidence: 'Evidence: recalls, investigations and complaints known on that date',
  judge: 'AI: compare the complaint with each recall',
  verify: 'Verify: every quote, id and number checked',
  decide: 'Decide: rules set the outcome and confidence',
}

export const STATUS: Record<string, string> = {
  new: 'New', suggested: 'To do', waiting: 'Waiting for owner', resolved: 'Resolved', escalated: 'Escalated',
}

export const ISSUE: Record<string, string> = {
  unknown_recall: 'Cited a recall that is not a candidate',
  quote_not_found: 'A quote is not in the source text',
  quote_drops_negation: 'A quote cut off a negation (e.g. “Zero”)',
  unknown_complaint: 'Cited a complaint its search did not return',
  inconsistent: 'Proposal does not match its own checks',
  unsupported_number: 'Stated a number that is not in the evidence',
  malformed_output: 'Answer was not valid JSON',
  duplicate_check: 'Checked the same recall twice',
}
