import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { workspace } from '../api/client'
import type { RunEvent, Ticket } from '../api/types'
import { STATUS, ticketName } from '../lib/labels'
import { Chip } from '../shared/Badges'
import { Quoted } from '../shared/Quoted'
import { ActionPanel } from './ActionPanel'
import { SuggestionView } from './SuggestionView'
import { liveLine } from '../lib/liveTrail'
import { TrailView } from './TrailView'

const HISTORY: Record<string, string> = {
  linked_recall: 'Linked to recall', reply_drafted: 'Reply to the owner drafted (not sent)', no_reply: 'No reply to the owner',
  owner_request_drafted: 'Request to the owner drafted (not sent)', escalated: 'Escalated to', closed: 'Closed',
  disagreed: 'Chose something other than the suggestion', monitoring: 'Recorded and watching', reopened: 'Reopened',
  // older entries
  replied_to_owner: 'Reply to the owner drafted (not sent)', asked_owner: 'Request to the owner drafted (not sent)',
}
const MESSAGES = ['reply_drafted', 'owner_request_drafted', 'replied_to_owner', 'asked_owner']

/** One ticket: what it is (suggestion), how the agent got there (trail), and what to do (actions). */
export function TicketPage() {
  const odino = Number(useParams().odino)
  const [t, setT] = useState<{ odino: number; ticket: Ticket } | null>(null)
  const [live, setLive] = useState<{ icon: string; text: string }[] | null>(null)
  const [error, setError] = useState('')
  const ticket = t && t.odino === odino ? t.ticket : null

  const load = useCallback(() => workspace.ticket(odino).then(ticket => setT({ odino, ticket })).catch(e => setError(String(e))), [odino])
  const runCheck = useCallback(async () => {
    setLive([])
    try {
      await workspace.check(odino, (e: RunEvent) => { const l = liveLine(e); if (l) setLive(x => [...(x ?? []), l]) })
    } catch (e) { setError(String(e)) }
    await load()
    setLive(null)
  }, [odino, load])

  useEffect(() => { load() }, [load])
  useEffect(() => {  // a ticket is checked automatically the first time anyone opens it
    if (ticket && !ticket.suggestion && live === null) queueMicrotask(runCheck)
  }, [ticket, live, runCheck])

  if (error) return <p className="alert-text">{error}</p>
  if (!ticket) return <p className="muted">Loading…</p>
  const c = ticket.complaint
  const s = ticket.suggestion
  const done = ['resolved', 'escalated', 'waiting', 'monitoring'].includes(ticket.status.status)
  const marks = s ? s.why.flatMap(w => w.quotes.map(q => ({ quote: q.owner, label: 'owner' }))) : []

  return (
    <>
      <p><Link to="/">← Inbox</Link></p>
      <div className="ticket-head">
        <div>
          <h1>{c.odino != null && c.odino < 0 ? `New complaint (${ticketName(c.odino)})` : `Complaint ${c.odino}`} · {c.year} {c.make} {c.model}</h1>
          <p className="muted">Received {c.received} · owner chose: {c.components.join(', ') || 'no component'}</p>
        </div>
        <Chip tone={done ? 'ok' : 'info'}>{STATUS[ticket.status.status]}</Chip>
      </div>
      {ticket.demo && <div className="demo-banner"><strong>Demo {ticket.demo.id}:</strong> {ticket.demo.title}</div>}
      {live && (
        <section className="card live-trail">
          <h3><span className="spinner" /> The agent is investigating…</h3>
          <ol className="trail">{live.map((l, i) => <li key={i} className="trail-step"><span className="trail-icon">{l.icon}</span><div>{l.text}</div></li>)}</ol>
        </section>
      )}

      <div className="ticket-grid">
        <div>
          {s && !live && <SuggestionView s={s} />}
          {ticket.trail.length > 0 && !live && (
            <details className="card trail-card">
              <summary>How the agent investigated · {ticket.trail.length} steps <button className="link" onClick={e => { e.preventDefault(); runCheck() }}>watch it again live</button></summary>
              <TrailView steps={ticket.trail} />
            </details>
          )}
          <section className="card">
            <h3>What the owner wrote</h3>
            <div className="chips">
              {c.crash > 0 && <Chip tone="alert">crash</Chip>}{c.fire > 0 && <Chip tone="alert">fire</Chip>}
              {c.injured > 0 && <Chip tone="alert">{c.injured} injured</Chip>}
            </div>
            <Quoted text={c.text} marks={marks} />
          </section>
        </div>
        <div>
          {s && !done && !live && <ActionPanel key={s.result_id} odino={odino} s={s} onDone={load} onRecheck={runCheck} />}
          {ticket.history.length > 0 && (
            <section className="card">
              <h3>What was done</h3>
              {ticket.history.map((h, i) => (
                <div key={i} className="history">
                  <strong>{HISTORY[h.action] ?? h.action}</strong> {MESSAGES.includes(h.action)
                    ? <details><summary className="small">message</summary><pre>{h.detail}</pre></details> : h.detail}
                  <div className="muted small">{h.by} · {h.at.replace('T', ' ').slice(0, 16)}</div>
                </div>
              ))}
            </section>
          )}
          {ticket.demo?.next && done && (
            <details className="card hindsight">
              <summary>What happened next (hindsight, not known when the complaint arrived)</summary>
              <p>{ticket.demo.next}</p>
            </details>
          )}
        </div>
      </div>
    </>
  )
}
