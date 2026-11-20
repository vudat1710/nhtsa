import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { workspace } from '../api/client'
import type { RunEvent, Ticket } from '../api/types'
import { STATUS } from '../lib/labels'
import { Chip } from '../shared/Badges'
import { Quoted } from '../shared/Quoted'
import { ActionPanel } from './ActionPanel'
import { SuggestionView } from './SuggestionView'

// What the analyst sees while a ticket is being checked: plain progress, no system internals.
const PROGRESS: Record<string, string> = {
  intake: 'Reading the complaint', evidence: 'Looking up recalls for this vehicle on that date',
  judge: 'Comparing the complaint with each recall', verify: 'Double-checking every quote against the records',
  decide: 'Preparing the suggestion',
}

const HISTORY: Record<string, string> = {
  linked_recall: 'Linked to recall', replied_to_owner: 'Replied to the owner', asked_owner: 'Asked the owner',
  escalated: 'Escalated to', closed: 'Closed', disagreed: 'Disagreed with the suggestion',
}

export function TicketPage() {
  const odino = Number(useParams().odino)
  const [t, setT] = useState<{ odino: number; ticket: Ticket } | null>(null)
  const [progress, setProgress] = useState<string | null>(null)
  const [error, setError] = useState('')
  const ticket = t && t.odino === odino ? t.ticket : null

  const load = useCallback(() => workspace.ticket(odino).then(ticket => setT({ odino, ticket })).catch(e => setError(String(e))), [odino])
  const runCheck = useCallback(async () => {
    setProgress(PROGRESS.intake)
    try {
      await workspace.check(odino, (e: RunEvent) => { if (e.type === 'step') setProgress(PROGRESS[e.step] ?? e.step) })
    } catch (e) { setError(String(e)) }
    setProgress(null)
    await load()
  }, [odino, load])

  useEffect(() => { load() }, [load])
  useEffect(() => {  // a ticket is checked automatically the first time anyone opens it
    if (ticket && !ticket.suggestion && progress === null) queueMicrotask(runCheck)
  }, [ticket, progress, runCheck])

  if (error) return <p className="alert-text">{error}</p>
  if (!ticket) return <p className="muted">Loading…</p>
  const c = ticket.complaint
  const s = ticket.suggestion
  const done = ['resolved', 'escalated', 'waiting'].includes(ticket.status.status)
  const marks = s ? s.why.flatMap(w => w.quotes.map(q => ({ quote: q.owner, label: 'owner' }))) : []

  return (
    <>
      <p><Link to="/">← Inbox</Link></p>
      <div className="ticket-head">
        <div>
          <h1>Complaint {c.odino} · {c.year} {c.make} {c.model}</h1>
          <p className="muted">Received {c.received} · owner chose: {c.components.join(', ') || 'no component'}</p>
        </div>
        <Chip tone={done ? 'ok' : 'info'}>{STATUS[ticket.status.status]}</Chip>
      </div>
      {ticket.demo && <div className="demo-banner"><strong>Demo {ticket.demo.id}:</strong> {ticket.demo.title}</div>}
      {progress && <section className="card checking"><span className="spinner" /> {progress}…</section>}

      <div className="ticket-grid">
        <div>
          {s && <SuggestionView s={s} />}
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
          {s && !done && <ActionPanel key={s.result_id} odino={odino} s={s} onDone={load} />}
          {ticket.history.length > 0 && (
            <section className="card">
              <h3>What was done</h3>
              {ticket.history.map((h, i) => (
                <div key={i} className="history">
                  <strong>{HISTORY[h.action] ?? h.action}</strong> {h.action === 'replied_to_owner' || h.action === 'asked_owner'
                    ? <details><summary className="small">message</summary><pre>{h.detail}</pre></details> : h.detail}
                  <div className="muted small">{h.by} · {h.at.replace('T', ' ').slice(0, 16)}</div>
                </div>
              ))}
              {done && <button className="secondary" onClick={runCheck}>Check again</button>}
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
