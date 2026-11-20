import { useState } from 'react'
import { ops } from '../../api/client'
import type { Complaint, RunEvent } from '../../api/types'
import { ISSUE, STEP } from '../../lib/labels'

const FAULTS: [string, string][] = [
  ['', 'No simulated failure'],
  ['llm_down', 'Model unavailable'],
  ['bad_quote', 'AI misquotes once (repair)'],
  ['unknown_recall', 'AI cites a non-candidate recall once (repair)'],
  ['malformed_json:always', 'AI answers garbage every time (fallback)'],
]

function describe(e: RunEvent): string | null {
  switch (e.type) {
    case 'step': return STEP[e.step] ?? e.step
    case 'evidence': return `${e.recalls.length} candidate recall(s), ${e.stats.total} earlier similar complaints`
    case 'tool_call': return `AI searched earlier complaints for “${String(e.arguments.query ?? '')}” → ${e.results.length} found`
    case 'agent': return e.error ? `AI failed: ${e.error}` : `AI answered (${e.input_tokens + e.output_tokens} tokens)`
    case 'verify': return e.issues.length ? `Verification: ${e.issues.map(i => ISSUE[i.code] ?? i.code).join('; ')} → ${e.result}` : 'Verification passed'
    case 'error': return `Error: ${e.message}`
    default: return null
  }
}

/** Failure drills: run a complaint with the AI on/off or deliberately broken, and watch every step. Runs are stored
 *  under the 'ops' label, so they never change what the analyst sees. */
export function DrillPanel({ target, onDone }: { target: number | Complaint; onDone: (resultId: string) => void }) {
  const [fault, setFault] = useState('')
  const [log, setLog] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const go = async (useLlm: boolean) => {
    setBusy(true); setLog([])
    try {
      await ops.drill(target, { useLlm, fault: fault || null }, e => {
        if (e.type === 'done') onDone(e.result_id)
        const line = describe(e)
        if (line) setLog(l => [...l, line])
      })
    } catch (err) { setLog(l => [...l, `Error: ${String(err)}`]) } finally { setBusy(false) }
  }
  return (
    <section className="card run">
      <div className="run-controls">
        <button disabled={busy} onClick={() => go(true)}>{busy ? 'Running…' : 'Run with AI'}</button>
        <button disabled={busy} className="secondary" onClick={() => go(false)}>Rules only</button>
        <select value={fault} onChange={e => setFault(e.target.value)} disabled={busy} title="Break the AI on purpose">
          {FAULTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      {log.length > 0 && <ol className="progress">{log.map((l, i) => <li key={i}>{l}</li>)}</ol>}
    </section>
  )
}
