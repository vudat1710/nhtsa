import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { QueueItem } from '../api/types'
import { OutcomeBadge, Chip } from '../components/Badges'

const FILTERS: [string, string, (q: QueueItem) => boolean][] = [
  ['all', 'All', () => true],
  ['todo', 'Not checked', q => !q.result],
  ['escalate', 'Escalated', q => !!q.result?.escalate],
  ['info', 'Needs info', q => q.result?.outcome === 'needs_info'],
  ['known', 'Known recall', q => q.result?.outcome === 'known_recall' && !q.result.escalate],
]

/** The analyst's morning: incoming complaints, each with its outcome once checked. Severe ones first. */
export function QueuePage() {
  const [items, setItems] = useState<QueueItem[] | null>(null)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState('')
  useEffect(() => { api.queue().then(setItems).catch(e => setError(String(e))) }, [])
  if (error) return <p className="alert-text">{error}</p>
  if (!items) return <p className="muted">Loading…</p>
  const shown = items.filter(FILTERS.find(f => f[0] === filter)![2])
  return (
    <>
      <div className="page-head">
        <h1>Complaint queue</h1>
        <p className="muted">Each complaint is checked against the recalls that covered that exact vehicle on the day it arrived.</p>
      </div>
      <div className="tabs">
        {FILTERS.map(([k, label, f]) => (
          <button key={k} className={filter === k ? 'tab active' : 'tab'} onClick={() => setFilter(k)}>{label} ({items.filter(f).length})</button>
        ))}
      </div>
      <table className="queue">
        <thead><tr><th>Complaint</th><th>Vehicle</th><th>Received</th><th>What the owner says</th><th>Outcome</th></tr></thead>
        <tbody>
          {shown.map(q => (
            <tr key={q.odino}>
              <td><Link to={`/case/${q.odino}`} className="mono">{q.odino}</Link>{q.demo && <div className="demo-tag">{q.demo}</div>}</td>
              <td>{q.vehicle}{q.severe && <> <Chip tone="alert">crash / fire / injury</Chip></>}</td>
              <td className="nowrap">{q.received}</td>
              <td className="snippet">{q.snippet}…</td>
              <td>{q.result
                ? <><OutcomeBadge outcome={q.result.outcome} confidence={q.result.confidence} />{q.result.campno && <div className="mono small">{q.result.campno}</div>}{q.result.source === 'fallback' && <div className="alert-text small">not AI-verified</div>}</>
                : <span className="muted">Not checked</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
