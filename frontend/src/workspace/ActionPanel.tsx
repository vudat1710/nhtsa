import { useState } from 'react'
import { workspace } from '../api/client'
import type { ActionOption, Suggestion } from '../api/types'

/** What to do. The suggested action is pre-filled (drafted message, issue); anything else asks why, so the system
 *  learns when it was wrong. */
export function ActionPanel({ odino, s, onDone }: { odino: number; s: Suggestion; onDone: () => void }) {
  const primaryIndex = Math.max(0, s.actions.findIndex(a => a.primary))
  // track the choice by position, not object identity: the ticket may be re-fetched (new objects, same content)
  const [index, setIndex] = useState(primaryIndex)
  const chosen: ActionOption = s.actions[index] ?? s.actions[primaryIndex]
  const [message, setMessage] = useState(chosen.message ?? '')
  const [title, setTitle] = useState(chosen.issue_title ?? '')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const disagrees = index !== primaryIndex

  const pick = (i: number) => { const a = s.actions[i]; setIndex(i); setMessage(a.message ?? ''); setTitle(a.issue_title ?? ''); setError('') }
  const submit = async () => {
    setBusy(true); setError('')
    try {
      await workspace.act(odino, {
        action: chosen.id, campno: chosen.campno, issue_id: chosen.issue_id, issue_kind: chosen.issue_kind,
        issue_comp: chosen.issue_comp, issue_title: chosen.issue_id ? null : (title || null), message: message || null,
        reason, disagrees,
      })
      onDone()
    } catch (e) { setError(String(e).replace(/^Error: /, '')) } finally { setBusy(false) }
  }

  return (
    <section className="card actions">
      <h3>What to do</h3>
      <div className="action-list">
        {s.actions.map((a, i) => (
          <label key={i} className={`action-option ${i === index ? 'chosen' : ''}`}>
            <input type="radio" checked={i === index} onChange={() => pick(i)} />
            <span>{a.label}{a.primary && <span className="suggested"> · suggested</span>}</span>
          </label>
        ))}
      </div>
      {(chosen.id === 'new_issue' || (chosen.issue_kind && !chosen.issue_id)) && (
        <label className="field">Emerging issue title<input value={title} onChange={e => setTitle(e.target.value)} /></label>
      )}
      {chosen.message !== null && chosen.id !== 'close_no_action' && (
        <label className="field">{chosen.id === 'request_info' ? 'Message to the owner' : 'Reply to the owner (from the recall’s own text; edit freely)'}
          <textarea rows={9} value={message} onChange={e => setMessage(e.target.value)} />
        </label>
      )}
      {(disagrees || chosen.id === 'close_no_action') && (
        <label className="field">{chosen.id === 'close_no_action' ? 'Why is this not a safety defect?' : 'Why not the suggested action? (helps the system learn)'}
          <input value={reason} onChange={e => setReason(e.target.value)} placeholder="One line is enough" />
        </label>
      )}
      <button onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Confirm'}</button>
      {error && <p className="alert-text small">{error}</p>}
    </section>
  )
}
