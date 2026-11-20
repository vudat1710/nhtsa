import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { workspace } from '../api/client'
import type { EmergingIssue } from '../api/types'
import { Chip } from '../shared/Badges'

const KIND = { new_defect: 'Possible new defect', remedy_concern: 'Recall remedy may not be working' }

/** For engineering: escalated complaints grouped into emerging issues, biggest and most severe first. */
export function IssuesPage() {
  const [issues, setIssues] = useState<EmergingIssue[] | null>(null)
  useEffect(() => { workspace.issues().then(setIssues) }, [])
  if (!issues) return <p className="muted">Loading…</p>
  const sorted = issues.slice().sort((a, b) => b.severe - a.severe || b.count - a.count)
  return (
    <>
      <div className="page-head">
        <h1>Emerging issues</h1>
        <p className="muted">Complaints the analysts escalated, grouped by vehicle and part (or by recall when its remedy seems not to hold).</p>
      </div>
      {sorted.length === 0 && <section className="card muted">Nothing escalated yet.</section>}
      <table className="queue">
        <tbody>
          {sorted.map(i => (
            <tr key={i.id}>
              <td><Link to={`/issues/${i.id}`}><strong>{i.title}</strong></Link><div className="muted small">{KIND[i.kind]} · opened {i.created_at.slice(0, 10)}</div></td>
              <td>{i.count} complaint{i.count === 1 ? '' : 's'}</td>
              <td>{i.severe > 0 && <Chip tone="alert">{i.severe} with crash / fire / injury</Chip>}</td>
              <td className="muted small">latest {i.latest}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

export function IssuePage() {
  const id = Number(useParams().id)
  const [issue, setIssue] = useState<EmergingIssue | null>(null)
  useEffect(() => { workspace.issue(id).then(setIssue) }, [id])
  if (!issue) return <p className="muted">Loading…</p>
  return (
    <>
      <p><Link to="/issues">← Emerging issues</Link></p>
      <div className="page-head">
        <h1>{issue.title}</h1>
        <p className="muted">{KIND[issue.kind]} · {issue.make} {issue.model} · {issue.comp.toLowerCase()} · {issue.complaints.length} complaints</p>
      </div>
      {issue.complaint_details?.map(c => (
        <section key={c.odino} className="card">
          <p><Link to={`/tickets/${c.odino}`} className="mono">{c.odino}</Link> · {c.vehicle} · {c.received} {c.severe && <Chip tone="alert">crash / fire / injury</Chip>}</p>
          <p className="quoted">{c.text}</p>
        </section>
      ))}
    </>
  )
}
