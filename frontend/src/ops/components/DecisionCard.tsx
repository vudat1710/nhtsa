import type { Result } from '../../api/types'
import { CONFIDENCE, FLAG, OUTCOME, SOURCE } from '../../lib/labels'
import { Chip } from '../../shared/Badges'

/** The answer first: outcome, recall, confidence, why (rules), what to do, and whether the AI was verified. */
export function DecisionCard({ result }: { result: Result }) {
  const d = result.decision
  const o = OUTCOME[d.outcome]
  const s = SOURCE[d.source]
  const recall = d.campno ? result.evidence.recalls.find(r => r.campno === d.campno) : null
  return (
    <section className={`card decision ${o.tone}`}>
      <div className="decision-head">
        <h2>{o.label}{d.campno && <> · <span className="mono">{d.campno}</span></>}</h2>
        <span className="muted">{CONFIDENCE[d.confidence]}</span>
      </div>
      <p className="action">
        {d.flags.includes('not_checked')
          ? 'Not checked by the AI: read the recalls listed below, or check it again with the AI.'
          : o.action}
        {d.escalate && d.outcome === 'known_recall' && ' Also escalate: see the flag below.'}
        {d.escalate && d.flags.includes('not_checked') && ' Escalated: crash, fire or injury.'}
      </p>
      {recall && <p className="recall-line">{recall.defect.split('. ').slice(-2).join('. ')}</p>}
      <h4>Why (rules, from checked citations)</h4>
      <ul className="reasons">{d.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
      {d.flags.length > 0 && (
        <div className="chips">{d.flags.map(f => <Chip key={f} tone={f === 'severe' || f === 'after_remedy' ? 'alert' : ''}>{FLAG[f] ?? f}</Chip>)}</div>
      )}
      {result.judgment && (
        <>
          <h4>AI summary (its own words; only its quotes and numbers were checked)</h4>
          <p>{result.judgment.summary}</p>
          {result.judgment.questions.length > 0 && (
            <>
              <h4>Ask the owner</h4>
              <ol>{result.judgment.questions.map((q, i) => <li key={i}>{q}</li>)}</ol>
            </>
          )}
        </>
      )}
      <p className={`source ${d.source === 'fallback' ? 'alert' : ''}`} title={s.note}>
        <strong>{s.label}.</strong> {s.note}
      </p>
    </section>
  )
}
