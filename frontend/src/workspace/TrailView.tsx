import type { TrailStep } from '../api/types'

const ICON: Record<TrailStep['kind'], string> = {
  read: '📄', look: '🗂', search: '🔎', compare: '⚖', check: '✓', decide: '➜',
}

/** How the agent investigated, step by step (stored trail from workspace/trail.py). */
export function TrailView({ steps }: { steps: TrailStep[] }) {
  return (
    <ol className="trail">
      {steps.map((s, i) => (
        <li key={i} className={`trail-step ${s.kind} ${s.status}`}>
          <span className="trail-icon">{ICON[s.kind]}</span>
          <div>
            <strong>{s.title}</strong>
            {s.lines.filter(Boolean).map((l, k) => <p key={k}>{l}</p>)}
            {s.quotes.length > 0 && (
              <table className="quotes"><thead><tr><th>The owner wrote</th><th>The recall says</th></tr></thead><tbody>
                {s.quotes.map((q, k) => <tr key={k}><td>“{q.owner}”</td><td>“{q.recall}”</td></tr>)}
              </tbody></table>
            )}
          </div>
        </li>
      ))}
    </ol>
  )
}
