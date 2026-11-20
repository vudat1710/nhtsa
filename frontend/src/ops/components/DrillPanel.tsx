import { useState } from 'react'
import { ops } from '../../api/client'
import { liveLine } from '../../lib/liveTrail'

const FAULTS: [string, string][] = [
  ['', 'No simulated failure'],
  ['llm_down', 'Model unavailable (fallback to rules)'],
  ['malformed_json', 'AI answers broken JSON once (repair)'],
]

/** Failure drills: run a complaint with the AI on/off or deliberately broken, and watch every step. Runs are stored
 *  under the 'ops' label, so they never change what the analyst sees. */
export function DrillPanel({ odino, onDone }: { odino: number; onDone: (resultId: string) => void }) {
  const [fault, setFault] = useState('')
  const [log, setLog] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const go = async (useLlm: boolean) => {
    setBusy(true); setLog([])
    try {
      await ops.drill(odino, { useLlm, fault: fault || null }, e => {
        if (e.type === 'done') onDone(e.result_id)
        const line = liveLine(e)
        if (line) setLog(l => [...l, `${line.icon} ${line.text}`])
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
