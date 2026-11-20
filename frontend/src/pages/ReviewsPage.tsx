import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ReviewItem } from '../api/types'
import { Chip, OutcomeBadge } from '../components/Badges'
import { FLAG } from '../lib/labels'

/** The engineer's queue: everything the system escalated, severe first, with the decision already made. */
export function ReviewsPage() {
  const [items, setItems] = useState<ReviewItem[] | null>(null)
  useEffect(() => { api.reviews().then(setItems) }, [])
  if (!items) return <p className="muted">Loading…</p>
  const open = items.filter(i => !i.review)
  return (
    <>
      <div className="page-head">
        <h1>Engineer review</h1>
        <p className="muted">{open.length} open · {items.length - open.length} reviewed. Possible new issues, related-but-different failures, and complaints that continue after a recall remedy.</p>
      </div>
      <table className="queue">
        <thead><tr><th>Complaint</th><th>Vehicle</th><th>Outcome</th><th>Why</th><th>Review</th></tr></thead>
        <tbody>
          {items.map(i => (
            <tr key={i.result_id}>
              <td>{i.odino ? <Link to={`/case/${i.odino}`} className="mono">{i.odino}</Link> : <Link to={`/result/${i.result_id}`}>typed</Link>}</td>
              <td>{i.vehicle}<div className="muted small">{i.received}</div></td>
              <td><OutcomeBadge outcome={i.outcome} confidence={i.confidence} /><div>{i.flags.map(f => <Chip key={f} tone={f === 'severe' ? 'alert' : ''}>{FLAG[f] ?? f}</Chip>)}</div></td>
              <td className="snippet">{i.reason}</td>
              <td>{i.review ? <span className="ok-text">{i.review.action.replace('_', ' ')}{i.review.campno && ` → ${i.review.campno}`}</span> : <span className="muted">open</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
