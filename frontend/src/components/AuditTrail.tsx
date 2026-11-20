import type { Result } from '../api/types'
import { ISSUE, STEP } from '../lib/labels'

/** Everything needed to audit this answer: steps that ran, every AI attempt and what the verifier found, tool calls. */
export function AuditTrail({ result }: { result: Result }) {
  const tokens = result.attempts.reduce((s, a) => s + a.input_tokens + a.output_tokens, 0)
  return (
    <details className="card audit">
      <summary>Audit trail · {result.steps.length} steps · {(result.latency_ms / 1000).toFixed(1)} s{tokens > 0 && ` · ${tokens.toLocaleString()} tokens`}{result.model && ` · ${result.model}`}{result.fault && ` · simulated failure: ${result.fault}`}</summary>
      <ol className="steps">{result.steps.map((s, i) => <li key={i}>{STEP[s] ?? s}</li>)}</ol>
      {result.attempts.map(a => (
        <div key={a.n} className="attempt">
          <strong>AI attempt {a.n}</strong>
          {a.error && <span className="alert-text"> failed: {a.error}</span>}
          {!a.error && a.issues.length === 0 && <span className="ok-text"> passed verification</span>}
          {a.issues.length > 0 && (
            <ul>{a.issues.map((i, k) => <li key={k}><strong>{ISSUE[i.code] ?? i.code}</strong>: <span className="small">{i.message}</span></li>)}</ul>
          )}
          {a.raw && <details><summary className="small">Raw answer</summary><pre>{a.raw}</pre></details>}
        </div>
      ))}
      {result.tool_calls.map((t, i) => (
        <p key={i} className="small">Tool <span className="mono">{t.tool}</span>({JSON.stringify(t.arguments)}) → {t.results.length} complaints in {t.ms} ms</p>
      ))}
      <p className="muted small">Result {result.id} · {result.created_at}</p>
    </details>
  )
}
