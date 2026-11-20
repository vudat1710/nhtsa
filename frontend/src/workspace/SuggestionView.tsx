import type { Suggestion } from '../api/types'
import { Chip } from '../shared/Badges'

const TONE: Record<string, string> = { known_recall: 'ok', related_different: 'warn', possible_new: 'alert', needs_info: 'info' }

/** What it is and why, in field-quality terms. Every quote here was checked against the record it came from. */
export function SuggestionView({ s }: { s: Suggestion }) {
  return (
    <section className={`card decision ${TONE[s.outcome]}`}>
      <h2>{s.headline}</h2>
      <div className="chips">
        {s.severity.map(x => <Chip key={x} tone="alert">{x}</Chip>)}
        {!s.check_note && <Chip tone="ok">high confidence</Chip>}
      </div>
      {s.check_note && <p className="check-note">{s.check_note}</p>}

      <h4>Why</h4>
      {s.why.map((w, i) => (
        <div key={i} className="why">
          <p>{w.text}</p>
          {w.quotes.length > 0 && (
            <table className="quotes"><thead><tr><th>The owner wrote</th><th>The recall says</th></tr></thead><tbody>
              {w.quotes.map((q, k) => <tr key={k}><td>“{q.owner}”</td><td>“{q.recall}”</td></tr>)}
            </tbody></table>
          )}
          {w.owner_quotes.length > 0 && (
            <ul className="owner-quotes">{w.owner_quotes.map(q => <li key={q.odino}>“{q.quote}” <span className="muted small">complaint {q.odino}</span></li>)}</ul>
          )}
        </div>
      ))}
      {s.pattern && (
        <>
          <h4>Pattern</h4>
          <p>{s.pattern.sentence}{(s.pattern.crash + s.pattern.fire + s.pattern.injury) > 0 &&
            ` Among them: ${s.pattern.crash} crash, ${s.pattern.fire} fire, ${s.pattern.injury} with injuries.`}</p>
        </>
      )}
      {s.recall && (
        <details className="recall-card">
          <summary>Recall {s.recall.display}: covers {s.recall.covers} · filed {s.recall.filed}{s.recall.units ? ` · ${s.recall.units.toLocaleString()} vehicles` : ''}</summary>
          <h5>Problem</h5><p>{s.recall.problem}</p>
          <h5>Risk</h5><p>{s.recall.consequence}</p>
          <h5>Remedy</h5><p>{s.recall.remedy}</p>
          {s.recall.replaced.length > 0 && <p className="muted small">Replaces recall {s.recall.replaced.join(', ')}.</p>}
        </details>
      )}
      <p className="muted small summary">In short: {s.summary}</p>
    </section>
  )
}
