import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { workspace } from '../api/client'
import type { InboxItem } from '../api/types'
import { STATUS, ticketName } from '../lib/labels'
import { Chip } from '../shared/Badges'

const TONE: Record<string, string> = { known_recall: 'ok', related_different: 'warn', possible_new: 'alert', needs_info: 'info' }
const OPEN = ['new', 'suggested']

/** The analyst's inbox: open tickets first, severe first, each with what the system suggests doing. */
export function InboxPage() {
  const [items, setItems] = useState<InboxItem[] | null>(null)
  const [showDone, setShowDone] = useState(false)
  const [checking, setChecking] = useState<string | null>(null)
  const nav = useNavigate()
  const load = () => workspace.inbox().then(setItems)
  useEffect(() => { load() }, [])
  if (!items) return <p className="muted">Loading…</p>

  const open = items.filter(i => OPEN.includes(i.status))
  const shown = (showDone ? items : open).slice().sort((a, b) =>
    Number(!OPEN.includes(a.status)) - Number(!OPEN.includes(b.status)) || b.severity.length - a.severity.length)
  const unchecked = items.filter(i => i.status === 'new')

  const checkAll = async () => {
    for (const [n, i] of unchecked.entries()) {
      setChecking(`Checking ${n + 1} of ${unchecked.length}`)
      await workspace.check(i.odino, () => {})
    }
    setChecking(null)
    load()
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Inbox</h1>
          <p className="muted">{open.length} open · each complaint is checked against the recalls that covered that vehicle on the day it arrived.</p>
        </div>
        <div className="row">
          <button className="secondary" onClick={() => nav('/new')}>+ New complaint</button>
          {unchecked.length > 0 && <button onClick={checkAll} disabled={!!checking}>{checking ?? `Check ${unchecked.length} new`}</button>}
          <label className="small"><input type="checkbox" checked={showDone} onChange={e => setShowDone(e.target.checked)} /> show done</label>
        </div>
      </div>
      <table className="queue">
        <thead><tr><th>Complaint</th><th>What the owner says</th><th>Suggestion</th><th>Status</th></tr></thead>
        <tbody>
          {shown.map(i => (
            <tr key={i.odino} className="clickable" onClick={() => nav(`/tickets/${i.odino}`)}>
              <td>
                <Link to={`/tickets/${i.odino}`} className="mono">{ticketName(i.odino)}</Link>
                <div>{i.vehicle}</div>
                <div className="muted small">{i.received}</div>
                {i.severity.map(s => <Chip key={s} tone="alert">{s}</Chip>)}
              </td>
              <td className="snippet">{i.snippet}…{i.demo && <div className="demo-tag">Demo: {i.demo}</div>}</td>
              <td className="suggest-cell">
                {i.suggestion ? (
                  <>
                    <span className={`badge ${TONE[i.suggestion.outcome]}`}>{i.suggestion.headline}</span>
                    {i.suggestion.action && <div className="small">→ {i.suggestion.action}</div>}
                    {i.suggestion.check && <div className="warn-text small">please confirm before acting</div>}
                  </>
                ) : <span className="muted">not checked yet</span>}
              </td>
              <td><Chip tone={OPEN.includes(i.status) ? 'info' : 'ok'}>{STATUS[i.status]}</Chip></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
