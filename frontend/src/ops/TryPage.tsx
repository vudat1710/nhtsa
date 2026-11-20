import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Complaint } from '../api/types'
import { DrillPanel } from './components/DrillPanel'

const EXAMPLE: Complaint = {
  odino: null, make: 'HONDA', model: 'RIDGELINE', year: '2018', received: '2022-06-01', crash: 0, fire: 0, injured: 0,
  components: ['BACK OVER PREVENTION'],
  text: 'The backup camera shows a black screen most of the time. The dealer said the wires in the tailgate are damaged from opening and closing it.',
}

/** Sandbox: type a complaint that is not in the data. Same pipeline, same rules, same checks; stored as an ops run. */
export function TryPage() {
  const [c, setC] = useState<Complaint>(EXAMPLE)
  const nav = useNavigate()
  const set = (k: keyof Complaint, v: string | number | string[]) => setC({ ...c, [k]: v })
  return (
    <>
      <div className="page-head">
        <h1>Try a complaint</h1>
        <p className="muted">Vehicle names must match NHTSA’s spelling (e.g. HONDA / RIDGELINE). The received date decides which recalls are visible.</p>
      </div>
      <section className="card form">
        <label>Make <input value={c.make} onChange={e => set('make', e.target.value.toUpperCase())} /></label>
        <label>Model <input value={c.model} onChange={e => set('model', e.target.value.toUpperCase())} /></label>
        <label>Model year <input value={c.year} onChange={e => set('year', e.target.value)} placeholder="9999 if unknown" /></label>
        <label>Received <input type="date" value={c.received} onChange={e => set('received', e.target.value)} /></label>
        <label>Component <input value={c.components.join(', ')} onChange={e => set('components', e.target.value ? e.target.value.split(',').map(s => s.trim().toUpperCase()) : [])} /></label>
        <label className="row">
          <span><input type="checkbox" checked={c.crash > 0} onChange={e => set('crash', e.target.checked ? 1 : 0)} /> Crash</span>
          <span><input type="checkbox" checked={c.fire > 0} onChange={e => set('fire', e.target.checked ? 1 : 0)} /> Fire</span>
          <span>Injured <input type="number" min={0} value={c.injured} onChange={e => set('injured', Number(e.target.value))} style={{ width: 60 }} /></span>
        </label>
        <label className="wide">What happened <textarea rows={6} value={c.text} onChange={e => set('text', e.target.value)} /></label>
      </section>
      <DrillPanel target={c} onDone={id => nav(`/ops/runs/${id}`)} />
    </>
  )
}
