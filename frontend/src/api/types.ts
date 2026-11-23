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

export interface RateStat { k: number; n: number; rate: number | null; ci95: [number, number] }

// ---------- the analyst's workspace (backend/app/workspace) ----------

export type TicketStatus = 'new' | 'suggested' | 'waiting' | 'resolved' | 'escalated' | 'monitoring'
export type ActionId = 'link_close' | 'request_info' | 'add_to_issue' | 'new_issue' | 'monitor' | 'close_no_action' | 'recheck' | 'reopen'

export interface QuotePair { owner: string; recall: string }
export interface Why { text: string; quotes: QuotePair[]; owner_quotes: { odino: number; quote: string }[] }
export interface RecallCard {
  campno: string; display: string; filed: string; covers: string; built: string | null; problem: string; consequence: string
  remedy: string; units: number | null; replaced: string[]
}
export interface Pattern {
  sentence: string; crash: number; fire: number; injury: number
}
export interface ActionOption {
  id: ActionId; label: string; primary: boolean; campno: string | null; issue_id: number | null
  issue_title: string | null; issue_kind: 'new_defect' | 'remedy_concern' | null; issue_comp: string | null
  message: string | null
}
export interface Suggestion {
  result_id: string; outcome: Outcome; headline: string; confidence: Confidence; check_note: string | null
  severity: string[]; summary: string; summary_by: 'ai' | 'rules'; recall: RecallCard | null; why: Why[]; pattern: Pattern | null
  questions: string[]; actions: ActionOption[]
}
export interface HistoryItem { odino: number; action: string; detail: string; result_id: string | null; by: string; at: string }
export interface DemoCase { id: string; odino: number; title: string; expect: string; story: string; next?: string }
export interface Ticket {
  complaint: Complaint
  status: { odino: number; status: TicketStatus; campno: string | null; issue_id: number | null; updated_at: string | null }
  history: HistoryItem[]
  suggestion: Suggestion | null
  demo: DemoCase | null
  trail: TrailStep[]
}
export interface TrailStep {
  kind: 'read' | 'look' | 'search' | 'compare' | 'check' | 'decide'
  title: string; lines: string[]; quotes: QuotePair[]; status: 'ok' | 'warn' | 'info'
}
export interface InboxItem {
  odino: number; vehicle: string; received: string; snippet: string; severity: string[]; status: TicketStatus
  demo: string | null
  suggestion: null | { outcome: Outcome; headline: string; confidence: Confidence; check: boolean; action: string | null }
}
export interface EmergingIssue {
  id: number; title: string; kind: 'new_defect' | 'remedy_concern'; make: string; model: string; comp: string
  campno: string | null; status: string; created_at: string; complaints: number[]; count: number; severe: number
  latest: string | null
  complaint_details?: { odino: number; vehicle: string; received: string; text: string; severe: boolean }[]
}

// ---------- the operations portal ----------

export interface RunSummary {
  id: string; odino: number | null; label: string; created_at: string; vehicle: string; outcome: Outcome
  confidence: Confidence; source: Decision['source']; latency_ms: number; fault: string | null; tokens: number
  attempts: number; tool_calls: number; first_issues: string[]
}

export interface EvalReport {
  name: string
  set: string
  split: string
  mode: string
  prompt: string
  model: string
  metrics: Record<string, unknown>
  rules?: { id: string; question: string; k: number; n: number }[]   // workflow invariants checked on this run
}

// Progress events streamed while a case runs (see backend/app/pipeline/workflow.py)
export type RunEvent =
  | { type: 'step'; step: string; attempt?: number }
  | { type: 'intake'; flags: string[]; masked: number }
  | { type: 'evidence'; recalls: string[]; recalls_total: number; stats: Stats }
  | { type: 'tool_call'; tool: string; arguments: Record<string, unknown>; results: number[]; ms: number }
  | { type: 'agent'; attempt: number; error: string | null; input_tokens: number; output_tokens: number }
  | { type: 'verify'; attempt: number; result: string; issues: Issue[] }
  | { type: 'judgment'; checks: RecallCheck[]; similar: { odino: number; quote: string }[] }
  | { type: 'done'; result_id: string; outcome: Outcome }
  | { type: 'error'; message: string }
