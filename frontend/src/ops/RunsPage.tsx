import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ops } from '../api/client'
import type { Result, RunSummary } from '../api/types'
import { ISSUE, SOURCE } from '../lib/labels'
import { OutcomeBadge } from '../shared/Badges'
import { AuditTrail } from './components/AuditTrail'
import { ComplaintPanel } from './components/ComplaintPanel'
import { DecisionCard } from './components/DecisionCard'
import { DrillPanel } from './components/DrillPanel'
import { EvidencePanel } from './components/EvidencePanel'
import { RecallChecks } from './components/RecallChecks'

/** Every AI run: what it decided, from what, whether it needed a repair or fell back, how long, how many tokens. */
export function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [label, setLabel] = useState('')
  const nav = useNavigate()
  useEffect(() => { ops.runs().then(setRuns) }, [])
  if (!runs) return <p className="muted">Loading…</p>
  const labels = [...new Set(runs.map(r => r.label))]
  const shown = runs.filter(r => !label || r.label === label)
  const fallback = shown.filter(r => r.source === 'fallback').length
  const repaired = shown.filter(r => r.source === 'ai_repaired').length
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>AI runs</h1>
          <p className="muted">{shown.length} runs · {repaired} repaired after a failed check · {fallback} fell back to rules</p>
        </div>
        <select value={label} onChange={e => setLabel(e.target.value)}>
          <option value="">All sources</option>
          {labels.map(l => <option key={l} value={l}>{l === 'queue' ? 'workspace' : l}</option>)}
        </select>
      </div>
      <table className="queue">
        <thead><tr><th>When</th><th>Complaint</th><th>Outcome</th><th>Path</th><th>First-answer issues</th><th>Tokens</th><th>Time</th><th>Source</th></tr></thead>
        <tbody>
          {shown.map(r => (
            <tr key={r.id} className="clickable" onClick={() => nav(`/ops/runs/${r.id}`)}>
              <td className="small nowrap">{r.created_at.replace('T', ' ').slice(0, 19)}</td>
              <td><span className="mono">{r.odino ?? 'typed'}</span><div className="small muted">{r.vehicle}</div></td>
              <td><OutcomeBadge outcome={r.outcome} confidence={r.confidence} /></td>
              <td className={r.source === 'fallback' ? 'alert-text small' : 'small'}>{SOURCE[r.source].label}{r.fault && ` · drill: ${r.fault}`}</td>
              <td className="small">{r.first_issues.map(i => ISSUE[i] ?? i).join('; ') || '–'}</td>
              <td className="small">{r.tokens.toLocaleString()}</td>
              <td className="small">{(r.latency_ms / 1000).toFixed(1)} s</td>
              <td className="small muted">{r.label === 'queue' ? 'workspace' : r.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

/** One run as the system saw it: decision and rules, each recall compared, evidence, and the full audit trail. */
export function RunPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const [run, setRun] = useState<{ id: string; result: Result } | null>(null)
  const [focused, setFocused] = useState<string | null>(null)
  useEffect(() => { ops.run(id!).then(result => setRun({ id: id!, result })) }, [id])
  const r = run && run.id === id ? run.result : null
  if (!r) return <p className="muted">Loading…</p>
  return (
    <>
      <p><Link to="/ops">← AI runs</Link>{r.complaint.odino && <> · <Link to={`/tickets/${r.complaint.odino}`}>open in the workspace</Link></>}</p>
      <h1>Run {r.id}</h1>
      <p className="muted">Failure drill: re-run this complaint with the AI broken on purpose.</p>
      <DrillPanel target={r.complaint.odino ?? r.complaint} onDone={newId => nav(`/ops/runs/${newId}`)} />
      <div className="case-grid">
        <div>
          <ComplaintPanel complaint={r.complaint} intake={r.intake} judgment={r.judgment} active={focused} />
          <EvidencePanel result={r} />
        </div>
        <div>
          <DecisionCard result={r} />
          <RecallChecks result={r} focused={focused} onFocus={setFocused} />
          <AuditTrail result={r} />
        </div>
      </div>
    </>
  )
}
