import type { CaseView, Complaint, EvalReport, QueueItem, Result, Review, ReviewItem, RunEvent } from './types'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  queue: () => get<QueueItem[]>('/queue'),
  case: (odino: number) => get<CaseView>(`/cases/${odino}`),
  result: (id: string) => get<Result>(`/results/${id}`),
  complaint: (odino: number) => get<Complaint>(`/complaints/${odino}`),
  reviews: () => get<ReviewItem[]>('/reviews'),
  evals: () => get<EvalReport[]>('/evals'),
  health: () => get<{ llm_mode: string; model: string | null; live_model: boolean }>('/health'),
  review: async (resultId: string, body: Omit<Review, 'result_id' | 'created_at' | 'reviewer'>) => {
    const r = await fetch(`/api/results/${resultId}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, result_id: resultId }),
    })
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
    return r.json() as Promise<Review>
  },
}

export interface RunOptions { useLlm: boolean; fault: string | null }

/** Run a case (stored complaint by id, or a typed complaint) and call onEvent for each progress event. */
export async function runCase(target: number | Complaint, opts: RunOptions, onEvent: (e: RunEvent) => void) {
  const params = new URLSearchParams({ use_llm: String(opts.useLlm) })
  if (opts.fault) params.set('fault', opts.fault)
  const typed = typeof target !== 'number'
  const url = typed ? `/api/complaints/run?${params}` : `/api/cases/${target}/run?${params}`
  const r = await fetch(url, {
    method: 'POST',
    headers: typed ? { 'Content-Type': 'application/json' } : undefined,
    body: typed ? JSON.stringify(target) : undefined,
  })
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
