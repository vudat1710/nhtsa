import { useEffect, useState } from 'react'
import { ops } from '../api/client'
import type { EvalReport, RateStat } from '../api/types'

type M = Record<string, Record<string, RateStat | number | null>>

function pct(s?: RateStat | number | null): string {
  if (s == null || typeof s === 'number') return s == null ? '–' : String(s)
  if (s.rate == null) return '–'
  return `${Math.round(s.rate * 100)}%`
}

function Cell({ s, better }: { s?: RateStat | number | null; better?: boolean }) {
  if (s == null) return <td className="muted">–</td>
  if (typeof s === 'number') return <td>{s}</td>
  return (
    <td className={better ? 'ok-text' : ''}>
      <strong>{pct(s)}</strong> <span className="muted small">{s.k}/{s.n} · 95% CI {Math.round(s.ci95[0] * 100)}–{Math.round(s.ci95[1] * 100)}%</span>
    </td>
  )
}

const ROWS: [string, string, string, 'higher' | 'lower' | ''][] = [
  ['A_known_recall', 'right_recall', 'A · picks the recall the owner cited', 'higher'],
  ['A_known_recall', 'wrong_recall', 'A · answers a different recall (confidently wrong)', 'lower'],
  ['A_known_recall', 'needs_info', 'A · asks for more information', ''],
  ['A_known_recall', 'escalated', 'A · escalates (says no recall fits)', ''],
  ['B_no_recall_yet', 'false_known_recall', 'B · claims a known recall when none existed', 'lower'],
  ['B_no_recall_yet', 'escalated', 'B · escalates to an engineer', 'higher'],
  ['', 'false_known_recall_A_and_B', 'A+B · confidently wrong “known recall”', 'lower'],
]

/** How we know the answers can be trusted: AI vs a rules baseline on frozen real cases, with intervals. */
export function EvalPage() {
  const [reports, setReports] = useState<EvalReport[] | null>(null)
  useEffect(() => { ops.evals().then(setReports) }, [])
  if (!reports) return <p className="muted">Loading…</p>
  const test = reports.filter(r => r.split === 'test' && r.set !== 'ask')
  const ai = test.find(r => r.mode === 'ai')
  const base = test.find(r => r.mode === 'baseline')
  const asked = reports.find(r => r.set === 'ask')?.metrics as Record<string, RateStat | number> | undefined
  if (!ai && !base) return <p className="muted">No evaluation runs yet: <code>uv run python -m app.eval.run --set a,b,c</code></p>
  const get = (r: EvalReport | undefined, group: string, key: string) => {
    const m = r?.metrics as M | undefined
    return (group ? m?.[group]?.[key] : (m as unknown as Record<string, RateStat>)?.[key]) as RateStat | undefined
  }
  const am = ai?.metrics as M | undefined
  return (
    <>
      <div className="page-head">
        <h1>Can you trust it?</h1>
        <p className="muted">Frozen test sets built only from real NHTSA records (see docs/DATA_CARD.md). Prompt {ai?.prompt} · model {ai?.model || '–'} · run {ai?.name}</p>
      </div>
      <section className="card">
        <h3>AI vs rules baseline</h3>
        <p className="small muted">Baseline = “newest recall on the same component”, no reading of the text. Set A: the owner cited a recall (number hidden). Owners are sometimes wrong, so “picks the cited recall” is agreement with the owner, not accuracy. Set B: no matching recall existed yet; one was filed within a year.</p>
        <table className="metrics">
          <thead><tr><th></th><th>AI (verified)</th><th>Baseline</th></tr></thead>
          <tbody>
            {ROWS.map(([g, k, label, dir]) => {
              const a = get(ai, g, k), b = get(base, g, k)
              const better = !!(a && b && a.rate != null && b.rate != null && dir && (dir === 'higher' ? a.rate > b.rate : a.rate < b.rate))
              return <tr key={g + k}><td>{label}</td><Cell s={a} better={better} /><Cell s={b} /></tr>
            })}
          </tbody>
        </table>
      </section>
      {ai?.adjudication && (
        <section className="card">
          <h3>When the AI disagreed, who was right?</h3>
          <p className="small muted">A person read each case (data/eval/adjudication/{ai.name}.md) and judged whether the AI's answer or the owner's recall was right.</p>
          <table className="metrics"><thead><tr><th></th><th>AI right</th><th>Owner right</th><th>Unclear</th></tr></thead><tbody>
            <tr><td>A · random {ai.adjudication.A.adjudicated} of {ai.adjudication.A.disagreements} disagreements</td><td className="ok-text">{ai.adjudication.A.ai_right}</td><td>{ai.adjudication.A.owner_right}</td><td>{ai.adjudication.A.unclear}</td></tr>
            <tr><td>B · all {ai.adjudication.B.adjudicated} “known recall” claims</td><td className="ok-text">{ai.adjudication.B.ai_right}</td><td>{ai.adjudication.B.owner_right}</td><td>{ai.adjudication.B.unclear}</td></tr>
          </tbody></table>
          <p className="small">All 7 “owner right” cases in A are complaints that describe no failure, only trouble getting the recall repair done. The AI correctly found no failure to match; the product should then link the cited recall as a remedy-access problem instead of escalating. That is the top next step.</p>
        </section>
      )}
      {ai?.rescore_note && <p className="small muted">Rescored from {ai.rescored_from} with the same AI answers ({ai.decisions_changed} decisions changed): {ai.rescore_note}.</p>}
      {am?.calibration && (
        <section className="card">
          <h3>Does “confidence” mean something?</h3>
          <p className="small muted">Share of answers that were right, by the confidence the rules gave (A: matched the cited recall; B: did not claim a known recall).</p>
          <table className="metrics"><tbody>
            {Object.entries(am.calibration).map(([lvl, s]) => <tr key={lvl}><td>{lvl}</td><Cell s={s as RateStat} /></tr>)}
          </tbody></table>
        </section>
      )}
      {am?.C_stress && (
        <section className="card">
          <h3>Stress cases (set C)</h3>
          <table className="metrics"><thead><tr><th></th><th>AI</th><th>Baseline</th></tr></thead><tbody>
            {Object.keys(am.C_stress).map(k => <tr key={k}><td>{k.replaceAll('_', ' ')}</td><Cell s={get(ai, 'C_stress', k)} /><Cell s={get(base, 'C_stress', k)} /></tr>)}
          </tbody></table>
        </section>
      )}
      {am?.provenance && (
        <section className="card">
          <h3>Are its sources real?</h3>
          <p className="small muted">Every final answer is 100% verified by construction. This is how often the AI’s first answer needed correcting.</p>
          <table className="metrics"><tbody>
            <tr><td>First answer failed verification</td><Cell s={am.provenance.first_answer_failed_verification as RateStat} /></tr>
            <tr><td>Fixed in one retry</td><Cell s={am.provenance.repaired as RateStat} /></tr>
            <tr><td>Fell back to rules (not AI-verified)</td><Cell s={am.provenance.fallback as RateStat} /></tr>
            <tr><td>Model errors</td><Cell s={am.provenance.model_errors as RateStat} /></tr>
          </tbody></table>
        </section>
      )}
      {am?.operations && (
        <section className="card">
          <h3>Cost and speed (AI)</h3>
          <table className="metrics"><tbody>
            {Object.entries(am.operations).map(([k, v]) => <tr key={k}><td>{k.replaceAll('_', ' ')}</td><td>{String(v)}</td></tr>)}
          </tbody></table>
        </section>
      )}
      {asked && (
        <section className="card">
          <h3>Follow-up questions (“Ask about this case”)</h3>
          <p className="small muted">Questions about the demo tickets (data/eval/ask_questions.json), checked by code: right scope, every quote verified, “not in the records” instead of a guess.</p>
          <table className="metrics"><tbody>
            <tr><td>Questions passed</td><Cell s={asked.passed} /></tr>
            <tr><td>Answers with every quote verified (not blocked)</td><Cell s={asked.verified_when_not_blocked} /></tr>
            <tr><td>Says “not in the records” when it should</td><Cell s={asked.says_not_in_records_when_expected} /></tr>
            <tr><td>Blocked by the provider’s safety filter</td><Cell s={asked.blocked_by_provider} /></tr>
          </tbody></table>
        </section>
      )}
    </>
  )
}
