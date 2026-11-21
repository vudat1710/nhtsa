import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { type NewComplaint, workspace } from '../api/client'

const EMPTY: NewComplaint = { make: '', model: '', year: '', component: 'UNKNOWN OR OTHER', text: '', crash: false, fire: false, injured: 0 }

/** A complaint that is not in NHTSA's data yet (e.g. one that just came in by phone). It becomes a ticket received
 *  today and is checked like any other. The vehicle is picked from NHTSA's own names: recalls are matched on them
 *  exactly, so "Ioniq5" would find no recall and look like "no recall covers this". */
export function NewComplaintPage() {
  const nav = useNavigate()
  const [makes, setMakes] = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [years, setYears] = useState<string[]>([])
  const [components, setComponents] = useState<string[]>([])
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (patch: Partial<NewComplaint>) => setForm(f => ({ ...f, ...patch }))

  const makeOk = makes.includes(form.make)
  const modelOk = makeOk && models.includes(form.model)
  const ready = modelOk && years.includes(form.year) && form.text.trim().length > 0

  useEffect(() => { workspace.vehicles().then(setMakes); workspace.components().then(setComponents) }, [])
  useEffect(() => { if (makeOk) workspace.vehicles(form.make).then(setModels) }, [form.make, makeOk])
  useEffect(() => { if (modelOk) workspace.vehicles(form.make, form.model).then(setYears) }, [form.make, form.model, modelOk])

  const submit = async () => {
    setBusy(true); setError('')
    try {
      const { odino } = await workspace.newComplaint(form)
      nav(`/tickets/${odino}`)  // the ticket page checks it on first open
    } catch (e) { setError(String(e)); setBusy(false) }
  }

  return (
    <>
      <p><Link to="/">← Inbox</Link></p>
      <div className="page-head">
        <h1>New complaint</h1>
        <p className="muted">For a complaint that is not in NHTSA's data yet. It is received today, so it is compared with every recall filed before today.</p>
      </div>
      <section className="card new-complaint">
        <p className="small muted">Pick the vehicle from NHTSA's list: recalls are matched on NHTSA's exact names (in production, the VIN would fill these in).</p>
        <div className="row">
          <label className="grow">Make
            <input list="makes" value={form.make} placeholder="e.g. HYUNDAI"
                   onChange={e => set({ make: e.target.value.toUpperCase(), model: '', year: '' })} />
          </label>
          <label className="grow">Model
            <input list="models" value={form.model} disabled={!makeOk} placeholder={makeOk ? 'e.g. IONIQ 5' : 'pick a make first'}
                   onChange={e => set({ model: e.target.value.toUpperCase(), year: '' })} />
          </label>
          <label>Model year
            <select value={form.year} disabled={!modelOk} onChange={e => set({ year: e.target.value })}>
              <option value="">–</option>
              {modelOk && years.map(y => <option key={y}>{y}</option>)}
            </select>
          </label>
        </div>
        <datalist id="makes">{makes.map(m => <option key={m} value={m} />)}</datalist>
        <datalist id="models">{makeOk && models.map(m => <option key={m} value={m} />)}</datalist>
        {form.make && !makeOk && <p className="warn-text small">“{form.make}” is not one of NHTSA's makes: pick one from the list.</p>}
        {form.model && makeOk && !modelOk && <p className="warn-text small">“{form.model}” is not one of NHTSA's {form.make} models: pick one from the list.</p>}

        <div className="row">
          <label className="grow">Component the owner chose
            <select value={form.component} onChange={e => set({ component: e.target.value })}>
              {components.map(c => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label className="small"><input type="checkbox" checked={form.crash} onChange={e => set({ crash: e.target.checked })} /> crash</label>
          <label className="small"><input type="checkbox" checked={form.fire} onChange={e => set({ fire: e.target.checked })} /> fire</label>
          <label className="small">injured
            <input type="number" min={0} max={99} value={form.injured} className="narrow"
                   onChange={e => set({ injured: Math.max(0, Number(e.target.value) || 0) })} />
          </label>
        </div>

        <label>What the owner wrote
          <textarea rows={7} value={form.text} maxLength={5000} placeholder="In the owner's words…"
                    onChange={e => set({ text: e.target.value })} />
        </label>

        <div className="row">
          <button disabled={!ready || busy} onClick={submit}>{busy ? 'Creating…' : 'Create ticket and check it'}</button>
          {error && <span className="alert-text small">{error}</span>}
        </div>
      </section>
    </>
  )
}
