import type { Confidence, Outcome } from '../api/types'
import { CONFIDENCE, OUTCOME } from '../lib/labels'

export function OutcomeBadge({ outcome, confidence }: { outcome: Outcome; confidence?: Confidence }) {
  const o = OUTCOME[outcome]
  return (
    <span className={`badge ${o.tone}`}>
      {o.label}
      {confidence && <span className="badge-sub"> · {CONFIDENCE[confidence].replace(' confidence', '')}</span>}
    </span>
  )
}

export function Chip({ children, tone = '' }: { children: React.ReactNode; tone?: string }) {
  return <span className={`chip ${tone}`}>{children}</span>
}
