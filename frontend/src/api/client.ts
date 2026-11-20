import type {
  ActionId, EmergingIssue, EvalReport, InboxItem, Result, RunEvent, RunSummary, Ticket, TicketStatus, Turn,
} from './types'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) {
    const text = await r.text()
    let detail = text
    try { detail = JSON.parse(text).detail ?? text } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return r.json() as Promise<T>
}

export interface ActionBody {
  action: ActionId; campno?: string | null; issue_id?: number | null; issue_title?: string | null
  issue_kind?: string | null; issue_comp?: string | null; message?: string | null; reason?: string; disagrees?: boolean
}

/** The analyst's workspace. */
export const workspace = {
  inbox: () => get<InboxItem[]>('/inbox'),
  ticket: (odino: number) => get<Ticket>(`/tickets/${odino}`),
  act: (odino: number, body: ActionBody) => post<{ status: TicketStatus }>(`/tickets/${odino}/actions`, body),
  issues: () => get<EmergingIssue[]>('/issues'),
  issue: (id: number) => get<EmergingIssue>(`/issues/${id}`),
  check: (odino: number, onEvent: (e: RunEvent) => void) => streamEvents(`/api/tickets/${odino}/check`, onEvent),
  ask: (odino: number, question: string) => post<Turn>(`/tickets/${odino}/ask`, { question }),
}

/** The operations portal. */
export const ops = {
  health: () => get<{ model: string | null }>('/ops/health'),
  runs: () => get<RunSummary[]>('/ops/runs'),
  run: (id: string) => get<Result>(`/ops/runs/${id}`),
  evals: () => get<EvalReport[]>('/ops/evals'),
  drill: (odino: number, opts: { useLlm: boolean; fault: string | null }, onEvent: (e: RunEvent) => void) => {
    const params = new URLSearchParams({ use_llm: String(opts.useLlm) })
    if (opts.fault) params.set('fault', opts.fault)
    return streamEvents(`/api/ops/drill/${odino}?${params}`, onEvent)
  },
}

/** POST and read Server-Sent Events until the stream ends. */
async function streamEvents(url: string, onEvent: (e: RunEvent) => void) {
  const r = await fetch(url, { method: 'POST' })
  if (!r.ok || !r.body) throw new Error(`${r.status} ${await r.text()}`)
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let i
    while ((i = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, i)
      buffer = buffer.slice(i + 2)
      if (chunk.startsWith('data: ')) onEvent(JSON.parse(chunk.slice(6)) as RunEvent)
    }
  }
}
