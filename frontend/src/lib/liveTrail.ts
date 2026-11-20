import type { RunEvent } from '../api/types'

const VERDICT: Record<string, string> = { same: 'same failure', partial: 'possibly', different: 'same part, different failure' }

/** The same story while it happens, built from the live progress events of a check. */
export function liveLine(e: RunEvent): { icon: string; text: string } | null {
  switch (e.type) {
    case 'step':
      return e.step === 'intake' ? { icon: '📄', text: 'Reading the complaint…' }
        : e.step === 'evidence' ? { icon: '🗂', text: 'Looking up what was known on that date…' }
        : e.step === 'judge' ? { icon: '💭', text: e.attempt && e.attempt > 1 ? 'Asking the agent to correct its answer…' : 'The agent is comparing the complaint with each recall…' }
        : e.step === 'verify' ? { icon: '✓', text: 'Double-checking every quote against the records…' }
        : { icon: '➜', text: 'Applying the decision rules…' }
    case 'evidence':
      return { icon: '🗂', text: `${e.recalls.length} recall(s) covered this vehicle then; ${e.stats.total} earlier complaints about the same part.` }
    case 'tool_call':
      return { icon: '🔎', text: `The agent decided to search earlier complaints for “${String(e.arguments.query ?? '')}” → ${e.results.length} found.` }
    case 'agent':
      if (e.error) return { icon: '⚠', text: `The agent did not answer: ${e.error}` }
      return e.reasoning ? { icon: '💭', text: `Its reasoning (own summary): ${e.reasoning.replace(/\*\*/g, '').slice(0, 400)}` } : null
    case 'judgment':
      return { icon: '⚖', text: e.checks.length ? e.checks.map(c => `${c.campno.slice(0, 3)}-${c.campno.slice(3, 6)}: ${VERDICT[c.verdict]}`).join(' · ') : 'No recall describes this failure.' }
    case 'verify':
      return e.issues.length ? { icon: '⚠', text: `Check failed: ${e.issues.map(i => i.message).join('; ').slice(0, 200)}` } : { icon: '✓', text: 'Every quote found word for word in its source.' }
    default:
      return null
  }
}
