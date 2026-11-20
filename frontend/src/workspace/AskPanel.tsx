import { useState } from 'react'
import { workspace } from '../api/client'
import type { Suggestion, Turn } from '../api/types'

const SUGGESTED: Record<string, string[]> = {
  known_recall: ['Why this recall and not another one?', 'What would change this answer?', 'Was the car already repaired under the recall?'],
  related_different: ["Why doesn't that recall cover this?", 'Have other owners reported the same failure?', 'What should engineering look at first?'],
  possible_new: ['Have other owners reported the same failure?', 'Why does no recall cover this?', 'What should engineering look at first?'],
  needs_info: ['Which recall is most likely, and why?', 'What details would settle it?', "What is the owner's VIN?"],
}
const KIND: Record<string, string> = { complaint: 'this complaint', recall: 'recall', earlier_complaint: 'earlier complaint' }

function Answer({ t }: { t: Turn }) {
  if (t.error) return <p className="alert-text small">The assistant is unavailable right now ({t.error.slice(0, 80)}).</p>
  if (!t.answer) return <p className="alert-text small">No usable answer. {t.issues[0]}</p>
  const a = t.answer
  return (
    <div className="answer">
      <p>{a.answer}</p>
      <div className="chips">
        {a.scope === 'not_in_records' && <span className="chip info">not in the records</span>}
        {a.scope === 'out_of_scope' && <span className="chip">outside this case</span>}
        {a.recheck && <span className="chip warn">suggests re-checking the ticket</span>}
        {t.blocked ? <span className="chip warn">blocked by the provider’s safety filter</span>
          : t.verified ? <span className="chip ok">✓ every source checked</span> : <span className="chip alert">could not be verified: treat with caution</span>}
      </div>
      {!t.blocked && (
        <details className="how-answered">
          <summary>How it answered</summary>
          <ol className="trail">
            <li className="trail-step"><span className="trail-icon">📄</span><div>Read this case’s record: the complaint, its candidate recalls, the earlier complaints already found, and the decision.</div></li>
            {t.searches.map((s, i) => (
              <li key={i} className="trail-step"><span className="trail-icon">🔎</span><div>Decided to search earlier complaints for “{s.query}” → {s.results.length} found.</div></li>
            ))}
            {a.citations.length > 0 && (
              <li className="trail-step"><span className="trail-icon">📎</span><div>Based the answer on:
                <ul className="citations">{a.citations.map((c, i) => <li key={i}><span className="muted small">{KIND[c.kind]} {c.kind === 'complaint' ? '' : c.id}</span> “{c.quote}”</li>)}</ul>
              </div></li>
            )}
            <li className={`trail-step ${t.verified ? 'ok' : 'warn'}`}><span className="trail-icon">{t.verified ? '✓' : '⚠'}</span><div>
              {t.verified ? `Every quote was found word for word in its source${a.citations.length ? '' : ' (no claims needing a source)'}.` : `Verification failed: ${t.issues.join('; ')}`}
            </div></li>
          </ol>
        </details>
      )}
    </div>
  )
}

/** Follow-up questions about this one case. Answers must cite the records; code checks every quote. */
export function AskPanel({ odino, s, turns, onAsked }: { odino: number; s: Suggestion; turns: Turn[]; onAsked: (t: Turn) => void }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const send = async (question: string) => {
    if (question.trim().length < 3) return
    setBusy(true); setError('')
    try { onAsked(await workspace.ask(odino, question)); setQ('') } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  return (
    <section className="card ask">
      <h3>Ask about this case</h3>
      <p className="muted small">Answers come only from this complaint, its candidate recalls and earlier complaints received before it. Every quote is checked against its source.</p>
      {turns.map((t, i) => (
        <div key={i} className="turn"><p className="question">{t.question}</p><Answer t={t} /></div>
      ))}
      {busy && <p className="checking"><span className="spinner" /> The agent is reading the case record…</p>}
      <div className="chips">{(SUGGESTED[s.outcome] ?? []).map(x => <button key={x} className="chip-button" disabled={busy} onClick={() => send(x)}>{x}</button>)}</div>
      <div className="row">
        <input className="grow" placeholder="Ask a question about this complaint…" value={q} disabled={busy}
               onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') send(q) }} />
        <button disabled={busy || q.trim().length < 3} onClick={() => send(q)}>Ask</button>
      </div>
      {error && <p className="alert-text small">{error}</p>}
    </section>
  )
}
