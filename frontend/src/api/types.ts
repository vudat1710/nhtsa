// Mirrors backend/app/models.py (the contract between steps). Keep the two in sync.

export type Outcome = 'known_recall' | 'related_different' | 'possible_new' | 'needs_info'
export type Confidence = 'high' | 'medium' | 'low'

export interface Complaint {
  odino: number | null
  make: string
  model: string
  year: string
  received: string
  crash: number
  fire: number
  injured: number
  text: string
  components: string[]
}

export interface Intake { text: string; masked: number; flags: string[] }

export interface RecallItem {
  campno: string
  filed: string
  influenced_by: string
  units: number | null
  components: string[]
  comps: string[]
  same_component: boolean
  defect: string
  consequence: string
  remedy: string
  replaced_by: string | null
  complaints_since: number
}

export interface InvestigationItem { action: string; opened: string; closed: string | null; campno: string | null; subject: string }

export interface Stats { total: number; crash: number; fire: number; injury: number; first: string | null; last: string | null; last_12_months: number }

export interface Evidence { recalls: RecallItem[]; recalls_total: number; investigations: InvestigationItem[]; stats: Stats }

export interface RecallCheck {
  campno: string
  verdict: 'same' | 'partial' | 'different'
  complaint_quote: string
  recall_quote: string
  reason: string
}

export interface Judgment {
  checks: RecallCheck[]
  similar: { odino: number; quote: string }[]
  proposed: Outcome
  summary: string
  questions: string[]
}

export interface Issue { code: string; message: string }

export interface Attempt { n: number; raw: string; error: string | null; issues: Issue[]; input_tokens: number; output_tokens: number }

export interface Decision {
  outcome: Outcome
  confidence: Confidence
  campno: string | null
  reasons: string[]
  flags: string[]
  escalate: boolean
  source: 'ai_verified' | 'ai_repaired' | 'fallback' | 'rules'
}

export interface ToolCall { tool: string; arguments: Record<string, unknown>; results: number[]; ms: number }

export interface Result {
  id: string
  complaint: Complaint
  intake: Intake
  evidence: Evidence
  judgment: Judgment | null
  decision: Decision
  attempts: Attempt[]
  tool_calls: ToolCall[]
  steps: string[]
  model: string
  fault: string | null
  latency_ms: number
  created_at: string
}

export interface Review {
  result_id: string
  action: 'confirm_new' | 'link_recall' | 'dismiss' | 'accept' | 'override'
  campno: string | null
  note: string
  reviewer: string
  created_at: string
}

export interface QueueItem {
  odino: number
  vehicle: string
  received: string
  components: string[]
  severe: boolean
  snippet: string
  demo: string | null
  result: null | { id: string; outcome: Outcome; confidence: Confidence; campno: string | null; escalate: boolean; source: Decision['source']; flags: string[] }
}

export interface DemoCase { id: string; odino: number; title: string; expect: string; story: string; next?: string }

export interface CaseView { complaint: Complaint; result: Result | null; reviews: Review[]; demo: DemoCase | null }

export interface ReviewItem {
  result_id: string
  odino: number | null
  vehicle: string
  received: string
  outcome: Outcome
  confidence: Confidence
  flags: string[]
  reason: string
  review: Review | null
}

export interface RateStat { k: number; n: number; rate: number | null; ci95: [number, number] }

export interface EvalReport {
  name: string
  set: string
  split: string
  mode: 'ai' | 'baseline'
  prompt: string
  model: string
  metrics: Record<string, unknown>
}

// Progress events streamed while a case runs (see backend/app/pipeline/workflow.py)
export type RunEvent =
  | { type: 'step'; step: string; attempt?: number }
  | { type: 'intake'; flags: string[]; masked: number }
  | { type: 'evidence'; recalls: string[]; recalls_total: number; stats: Stats }
  | { type: 'tool_call'; tool: string; arguments: Record<string, unknown>; results: number[]; ms: number }
  | { type: 'agent'; attempt: number; error: string | null; input_tokens: number; output_tokens: number }
  | { type: 'verify'; attempt: number; result: string; issues: Issue[] }
  | { type: 'done'; result: Result }
  | { type: 'error'; message: string }
