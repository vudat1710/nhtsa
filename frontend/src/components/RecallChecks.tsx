import { useState } from 'react'
import type { RecallCheck, RecallItem, Result } from '../api/types'
import { VERDICT } from '../lib/labels'
import { Chip } from './Badges'
import { Quoted } from './Quoted'

function RecallMeta({ r }: { r: RecallItem }) {
  return (
    <p className="muted small">
      Filed {r.filed} · influenced by {r.influenced_by || '?'} · {r.units?.toLocaleString() ?? '?'} vehicles · {r.components.join(', ')}
      {r.replaced_by && <> · <strong>replaced by {r.replaced_by}</strong></>}
      {r.complaints_since > 0 && <> · {r.complaints_since} similar complaints since it was filed</>}
    </p>
  )
}

function RecallText({ r, quote }: { r: RecallItem; quote?: string }) {
  const marks = quote ? [{ quote, label: r.campno }] : []
  return (
    <div className="recall-text">
      <h5>Defect</h5><Quoted text={r.defect} marks={marks} />
      <h5>Consequence</h5><Quoted text={r.consequence} marks={marks} />
      <h5>Remedy</h5><Quoted text={r.remedy} marks={marks} />
    </div>
  )
}

function CheckCard({ check, recall, onFocus, focused }: { check: RecallCheck; recall: RecallItem; onFocus: () => void; focused: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={`check ${check.verdict} ${focused ? 'focused' : ''}`} onMouseEnter={onFocus}>
      <div className="check-head">
        <span className="mono">{check.campno}</span>
        <Chip tone={check.verdict === 'same' ? 'ok' : check.verdict === 'different' ? 'warn' : 'info'}>{VERDICT[check.verdict]}</Chip>
        {!recall.same_component && <Chip>filed under another component</Chip>}
      </div>
      <p>{check.reason}</p>
      <div className="quote-pair">
        <blockquote><span className="muted small">Complaint says</span>“{check.complaint_quote}”</blockquote>
        <blockquote><span className="muted small">Recall says</span>“{check.recall_quote}”</blockquote>
      </div>
      <RecallMeta r={recall} />
      <button className="link" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'} the full recall text</button>
      {open && <RecallText r={recall} quote={check.recall_quote} />}
    </div>
  )
}

/** Each recall the AI judged relevant, with both quotes; the rest of the candidates are listed, not hidden. */
export function RecallChecks({ result, focused, onFocus }: { result: Result; focused: string | null; onFocus: (c: string) => void }) {
  const ev = result.evidence
  const checks = result.judgment?.checks ?? []
  const judged = new Set(checks.map(c => c.campno))
  const others = ev.recalls.filter(r => !judged.has(r.campno))
  const [showOthers, setShowOthers] = useState(false)
  return (
    <section className="card">
      <h3>Recalls compared ({ev.recalls.length} candidate{ev.recalls.length === 1 ? '' : 's'} on this vehicle{ev.recalls_total > ev.recalls.length ? `, ${ev.recalls_total - ev.recalls.length} more not shown` : ''})</h3>
      {ev.recalls.length === 0 && <p className="muted">No recall covered this vehicle when the complaint arrived.</p>}
      {checks.map(ch => (
        <CheckCard key={ch.campno} check={ch} recall={ev.recalls.find(r => r.campno === ch.campno)!} focused={focused === ch.campno} onFocus={() => onFocus(ch.campno)} />
      ))}
      {!result.judgment && ev.recalls.length > 0 && <p className="muted">No AI comparison for this run (rules only or fallback).</p>}
      {others.length > 0 && (
        <>
          <button className="link" onClick={() => setShowOthers(!showOthers)}>
            {showOthers ? 'Hide' : 'Show'} {others.length} other candidate{others.length === 1 ? '' : 's'} {result.judgment ? 'judged unrelated' : ''}
          </button>
          {showOthers && others.map(r => (
            <div key={r.campno} className="other-recall">
              <span className="mono">{r.campno}</span> {r.defect.split('. ').slice(-2).join('. ')}
              <RecallMeta r={r} />
            </div>
          ))}
        </>
      )}
    </section>
  )
}
