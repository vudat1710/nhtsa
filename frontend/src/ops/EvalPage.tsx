import { useEffect, useState } from 'react'
import { ops } from '../api/client'
import type { EvalReport, RateStat } from '../api/types'

type M = Record<string, Record<string, RateStat | number | null>>
type Agreement = { a: Record<string, RateStat> }

const ERROR_KIND: Record<string, string> = {
  content_filter: 'blocked by Azure’s content filter', unavailable: 'AI unavailable', refused: 'the AI refused',
  incomplete: 'answer cut off', error: 'other errors (e.g. rate limit)',
}

/** A share with its count, e.g. "6%  17 of 300", and the 95% range on hover. Under 2%, one decimal (0.6%, not 1%). */
function Share({ s }: { s: RateStat }) {
  const value = s.n ? (s.k / s.n) * 100 : 0
  const pct = value > 0 && value < 2 ? value.toFixed(1) : String(Math.round(value))
  return <td title={`95% range ${Math.round(s.ci95[0] * 100)}–${Math.round(s.ci95[1] * 100)}%`}><strong>{pct}%</strong> <span className="small muted">{s.k} of {s.n}</span></td>
}

/** A guardrail: should always hold, so only a failure is highlighted. */
function Held({ k, n }: { k: number; n: number }) {
  return <td className={k === n ? '' : 'alert-text'}><strong>{k}/{n}</strong></td>
}

/** The AI's results first (they can vary), then the guardrails (tests that must always hold). There is no ground truth
 *  for which recall is right, so the comparison with owners is labelled agreement, never accuracy. */
export function EvalPage() {
  const [reports, setReports] = useState<EvalReport[] | null>(null)
  useEffect(() => { ops.evals().then(setReports) }, [])
  if (!reports) return <p className="muted">Loading…</p>
  const ai = reports.find(r => r.split === 'test' && r.mode === 'ai')
  if (!ai) return <p className="muted">No AI evaluation run yet: <code>uv run python -m app.eval.run</code></p>
  const agreement = reports.find(r => r.set === 'agreement' && (r as unknown as { run: string }).run === ai.name) as unknown as Agreement | undefined
  const asNew = reports.find(r => r.set === 'as_new') as unknown as Record<string, number> | undefined
  const am = ai.metrics as M
  const provenance = am.provenance as Record<string, RateStat> | undefined
  const errorKinds = (am.provenance?.model_error_kinds ?? {}) as unknown as Record<string, number>
  const operations = am.operations as Record<string, number> | undefined
  const rules = (ai.rules ?? []).filter(r => !r.id.startsWith('scenario.'))
  const scenarios = (ai.rules ?? []).filter(r => r.id.startsWith('scenario.'))
  const rulesHeld = rules.filter(r => r.k === r.n).length
  const scenariosHeld = scenarios.filter(r => r.k === r.n).length
  const stressCases = scenarios.reduce((total, r) => total + r.n, 0)

  return (
    <>
      <div className="page-head">
        <h1>How the AI is evaluated</h1>
        <p className="muted">{String(ai.metrics.cases)} test cases built from real complaints written by car owners, each replayed as of the day it arrived. Model {ai.model || '–'} · prompt {ai.prompt} · run {ai.name}.</p>
      </div>

      {agreement && (
        <section className="card">
          <h3>Compared with what the owner believed</h3>
          <p className="small muted">In {agreement.a.ai_names_a_recall.n} complaints the owner named a recall (hidden from the AI). Owners are sometimes wrong, so this is <strong>agreement, not accuracy</strong>. The simple rule is what an analyst might do instead: pick the newest recall on the same part (app/eval/agreement.py).</p>
          <table className="metrics">
            <thead><tr><th></th><th>AI</th><th>Simple rule</th></tr></thead>
            <tbody>
              <tr><td>Names a different recall than the owner</td><Share s={agreement.a.ai_names_a_different} /><Share s={agreement.a.rule_names_a_different} /></tr>
              <tr><td>When it names one, it is the owner’s</td><Share s={agreement.a.ai_names_the_owners} /><Share s={agreement.a.rule_names_the_owners} /></tr>
              <tr><td>Asks for more detail instead of guessing</td><Share s={agreement.a.ai_asks_for_detail} /><td className="muted">never</td></tr>
            </tbody>
          </table>
        </section>
      )}

      {provenance && (
        <section className="card">
          <h3>When the AI’s answer can’t be used</h3>
          <p className="small muted">Every quote and recall, and every number in the AI’s summary, is checked before anything is shown. A failed check gets one correction. With no usable answer, the ticket says “not checked by the AI” and no recall is matched.</p>
          <table className="metrics"><tbody>
            <tr><td>First answer broke a check (then corrected: {(am.provenance.repaired as RateStat).k})</td><Share s={provenance.first_answer_failed_verification} /></tr>
            <tr><td>No answer from the AI{Object.keys(errorKinds).length > 0 && <>: {Object.entries(errorKinds).map(([kind, count]) => `${count} ${ERROR_KIND[kind] ?? kind}`).join(', ')}</>}</td><Share s={provenance.model_errors} /></tr>
          </tbody></table>
        </section>
      )}

      {rules.length > 0 && (
        <section className="card">
          <h3>Guardrails: held on every run</h3>
          <p className="small">{rulesHeld} of {rules.length} workflow rules held on every run they apply to ({String(ai.metrics.cases)} runs); {scenariosHeld} of {scenarios.length} stress behaviours held on their {stressCases} cases{asNew && <>; {asNew.evidence_identical} of {asNew.cases} complaints got the same evidence stored or brand-new, and none found itself</>}.</p>
          <p className="small muted">These are tests, run on the real AI outputs (app/eval/trajectory.py, app/eval/as_new.py). They should always hold: a failure would be a bug. Each rule is tested to fail on a deliberately broken run.</p>
          <details className="audit">
            <summary>All {rules.length + scenarios.length} checks</summary>
            <table className="metrics"><tbody>
              {[...rules, ...scenarios].map(r => <tr key={r.id}><td>{r.question}</td><Held k={r.k} n={r.n} /></tr>)}
            </tbody></table>
          </details>
        </section>
      )}

      {operations && (
        <section className="card">
          <h3>Cost and speed</h3>
          <table className="metrics"><tbody>
            <tr><td>Time per complaint, median / 95th percentile</td><td>{(operations.latency_ms_p50 / 1000).toFixed(0)} s / {(operations.latency_ms_p95 / 1000).toFixed(0)} s</td></tr>
            <tr><td>Tokens per complaint (in + out)</td><td>{(operations.input_tokens_per_case + operations.output_tokens_per_case).toLocaleString()}</td></tr>
          </tbody></table>
        </section>
      )}

      <section className="card">
        <h3>Not measured yet: accuracy</h3>
        <p className="small">The only labels are the recalls owners named, and owners are sometimes wrong; the data has no VINs or repair records. Next: two analysts label a sample without seeing the AI’s answer. In production, every time an analyst overrides a suggestion it is logged with a reason, and those become the labels.</p>
      </section>
    </>
  )
}
