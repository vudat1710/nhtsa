import { useEffect, useState } from 'react'
import { ops } from '../api/client'
import type { EvalReport, RateStat } from '../api/types'

type M = Record<string, Record<string, RateStat | number | null>>

function Count({ k, n }: { k: number; n: number }) {
  return <td className={k === n ? 'ok-text' : 'alert-text'}><strong>{k}/{n}</strong></td>
}

/** Only what is checked objectively: against the records, against our own specification, or measured. There is no
 *  ground truth for which recall is right, so no agreement or accuracy number is shown (see "Not measured"). */
export function EvalPage() {
  const [reports, setReports] = useState<EvalReport[] | null>(null)
  useEffect(() => { ops.evals().then(setReports) }, [])
  if (!reports) return <p className="muted">Loading…</p>
  const ai = reports.find(r => r.split === 'test' && r.set !== 'ask' && r.mode === 'ai')
  const asked = reports.find(r => r.set === 'ask')?.metrics as Record<string, RateStat | number> | undefined
  const asNew = reports.find(r => r.set === 'as_new') as unknown as Record<string, number> | undefined
  if (!ai) return <p className="muted">No AI evaluation run yet: <code>uv run python -m app.eval.run</code></p>
  const am = ai.metrics as M
  const provenance = am.provenance as Record<string, RateStat> | undefined
  const operations = am.operations as Record<string, number> | undefined
  const rules = (ai.rules ?? []).filter(r => !r.id.startsWith('scenario.'))
  const scenarios = (ai.rules ?? []).filter(r => r.id.startsWith('scenario.'))
  const held = rules.filter(r => r.k === r.n).length

  return (
    <>
      <div className="page-head">
        <h1>What is checked</h1>
        <p className="muted">{String(ai.metrics.cases)} real, owner-written NHTSA complaints, each replayed as of the day it arrived (nothing later is visible). Only what code can check objectively is shown: against the records, against our own specification, or measured. Prompt {ai.prompt} · model {ai.model || '–'} · run {ai.name}.</p>
      </div>

      {provenance && (
        <section className="card">
          <h3>Every citation is checked against the records</h3>
          <p className="small muted">Every recall, quote and number in an answer is found in the records before it is shown. If a check fails, the AI gets one correction; then the answer is labelled “not checked by the AI” and a person must look. This proves the citations are real, not that the judgment is right.</p>
          <table className="metrics"><tbody>
            <tr><td>First AI answers that failed a check</td><Count k={provenance.first_answer_failed_verification.k} n={provenance.first_answer_failed_verification.n} /></tr>
            <tr><td>Not checked by the AI (a person must look)</td><td><strong>{provenance.fallback.k}/{provenance.fallback.n}</strong></td></tr>
          </tbody></table>
        </section>
      )}

      {rules.length > 0 && (
        <section className="card">
          <h3>The workflow’s rules held on every run: {held} of {rules.length}</h3>
          <p className="small muted">Rules that must always hold, checked against each stored run (app/eval/trajectory.py). Each is tested to fail on a deliberately broken run.</p>
          <table className="metrics"><tbody>
            {rules.map(r => <tr key={r.id}><td>{r.question}</td><Count k={r.k} n={r.n} /></tr>)}
          </tbody></table>
        </section>
      )}

      {scenarios.length > 0 && (
        <section className="card">
          <h3>Stress cases behave as designed</h3>
          <p className="small muted">Real complaints with one thing broken, each with a behaviour we specified.</p>
          <table className="metrics"><tbody>
            {scenarios.map(r => <tr key={r.id}><td>{r.question}</td><Count k={r.k} n={r.n} /></tr>)}
          </tbody></table>
        </section>
      )}

      {asNew && (
        <section className="card">
          <h3>No look-ahead: a stored complaint is judged as a brand-new one</h3>
          <p className="small muted">Each complaint’s evidence, gathered as stored and as a new complaint with no id (app/eval/as_new.py). Everything the system sees was received before the complaint’s own date, so it cannot see itself or anything later.</p>
          <table className="metrics"><tbody>
            <tr><td>Identical evidence</td><Count k={asNew.evidence_identical} n={asNew.cases} /></tr>
            <tr><td>Identical search results with and without excluding its own id</td><Count k={asNew.search_identical} n={asNew.cases} /></tr>
            <tr><td>Complaints whose search found themselves</td><td><strong>{asNew.found_itself}</strong></td></tr>
          </tbody></table>
        </section>
      )}

      {asked && (
        <section className="card">
          <h3>Follow-up questions keep to the records</h3>
          <p className="small muted">“Ask about this case” on the demo tickets (data/eval/ask_questions.json).</p>
          <table className="metrics"><tbody>
            {typeof asked.verified_when_not_blocked === 'object' && <tr><td>Answers with every quote found word for word</td><Count k={asked.verified_when_not_blocked.k} n={asked.verified_when_not_blocked.n} /></tr>}
            {typeof asked.says_not_in_records_when_the_data_lacks_it === 'object' && <tr><td>Says “not in the records” for what the data lacks (repair history, crash data, VIN)</td><Count k={asked.says_not_in_records_when_the_data_lacks_it.k} n={asked.says_not_in_records_when_the_data_lacks_it.n} /></tr>}
            {typeof asked.declines_requests_not_about_the_case === 'object' && <tr><td>Declines requests that are not about the case</td><Count k={asked.declines_requests_not_about_the_case.k} n={asked.declines_requests_not_about_the_case.n} /></tr>}
            {typeof asked.suggests_recheck_when_a_fact_changes === 'object' && <tr><td>Suggests a re-check when the analyst gives a new fact (a different model year)</td><Count k={asked.suggests_recheck_when_a_fact_changes.k} n={asked.suggests_recheck_when_a_fact_changes.n} /></tr>}
            <tr><td>Blocked by the provider’s safety filter (shown as blocked)</td><td><strong>{String(asked.blocked_by_provider)}</strong></td></tr>
          </tbody></table>
        </section>
      )}

      {operations && (
        <section className="card">
          <h3>Cost and speed (measured)</h3>
          <table className="metrics"><tbody>
            <tr><td>Time per complaint, median / 95th percentile</td><td>{(operations.latency_ms_p50 / 1000).toFixed(0)} s / {(operations.latency_ms_p95 / 1000).toFixed(0)} s</td></tr>
            <tr><td>Tokens per complaint (in + out)</td><td>{(operations.input_tokens_per_case + operations.output_tokens_per_case).toLocaleString()}</td></tr>
          </tbody></table>
        </section>
      )}

      <section className="card">
        <h3>Not measured: accuracy</h3>
        <p className="small">There is no ground truth for which recall is right: the only labels are the recalls owners cite, owners are sometimes wrong, and the data has no VINs or repair records. So no accuracy number is shown. Next: two analysts label a blind sample (which recall fits, without seeing the AI’s answer); in production, the analysts’ own accept/override decisions, already logged in the workspace, become the labels.</p>
      </section>
    </>
  )
}
