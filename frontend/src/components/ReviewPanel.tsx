import { useState } from 'react'
import { api } from '../api/client'
import type { Result, Review } from '../api/types'

const ACTIONS: Record<Review['action'], string> = {
  accept: 'Accept the match', override: 'Wrong recall: pick another', confirm_new: 'Confirm: new issue to investigate',
  link_recall: 'Link to an existing recall', dismiss: 'Dismiss (not a defect)',
}

/** A person closes the loop. Escalations get engineer actions; matches get accept/override. Stored as labels. */
export function ReviewPanel({ result, reviews, onSaved }: { result: Result; reviews: Review[]; onSaved: (r: Review) => void }) {
  const d = result.decision
  const actions: Review['action'][] = d.escalate || d.outcome !== 'known_recall'
    ? ['confirm_new', 'link_recall', 'dismiss'] : ['accept', 'override']
  const [action, setAction] = useState<Review['action']>(actions[0])
  const [campno, setCampno] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const needsRecall = action === 'link_recall' || action === 'override'
  const save = async () => {
    setError('')
    try {
      onSaved(await api.review(result.id, { action, campno: needsRecall ? campno : null, note }))
      setNote('')
    } catch (e) { setError(String(e)) }
  }
  return (
    <section className="card">
      <h3>{d.escalate ? 'Engineer review' : 'Analyst feedback'}</h3>
      {reviews.map((r, i) => (
        <p key={i} className="review-done">✔ {ACTIONS[r.action]}{r.campno && ` → ${r.campno}`}{r.note && `: “${r.note}”`} <span className="muted small">({r.reviewer}, {r.created_at.slice(0, 16).replace('T', ' ')})</span></p>
      ))}
      <div className="review-form">
        <select value={action} onChange={e => setAction(e.target.value as Review['action'])}>
          {actions.map(a => <option key={a} value={a}>{ACTIONS[a]}</option>)}
        </select>
        {needsRecall && (
          <select value={campno} onChange={e => setCampno(e.target.value)}>
            <option value="">Choose a candidate recall…</option>
            {result.evidence.recalls.filter(r => r.campno !== d.campno).map(r => <option key={r.campno} value={r.campno}>{r.campno}: {r.defect.split('. ').slice(-1)[0].slice(0, 70)}</option>)}
          </select>
        )}
        <input placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)} />
        <button onClick={save} disabled={needsRecall && !campno}>Save</button>
      </div>
      {error && <p className="alert-text small">{error}</p>}
    </section>
  )
}
