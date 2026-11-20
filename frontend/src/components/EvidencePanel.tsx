import { useState } from 'react'
import { api } from '../api/client'
import type { Result } from '../api/types'
import { Quoted } from './Quoted'

/** Facts computed by code (never by the AI): earlier complaints, investigations, and complaints the AI cited. */
export function EvidencePanel({ result }: { result: Result }) {
  const { stats, investigations } = result.evidence
  const similar = result.judgment?.similar ?? []
  const [open, setOpen] = useState<Record<number, string>>({})
  const toggle = async (odino: number) => {
    if (open[odino]) { const { [odino]: _, ...rest } = open; setOpen(rest); return }
    const c = await api.complaint(odino)
    setOpen({ ...open, [odino]: c.text })
  }
  return (
    <section className="card">
      <h3>Evidence (computed from the records, before the complaint date)</h3>
      <table className="facts"><tbody>
        <tr><td>Earlier complaints, same vehicle and component</td><td>{stats.total}{stats.first && <span className="muted"> ({stats.first} → {stats.last})</span>}</td></tr>
        <tr><td>…in the 12 months before this one</td><td>{stats.last_12_months}</td></tr>
        <tr><td>…with a crash / fire / injury</td><td>{stats.crash} / {stats.fire} / {stats.injury}</td></tr>
        <tr><td>NHTSA investigations on this vehicle</td><td>{investigations.length === 0 ? 'none' : investigations.map(i => `${i.action} (${i.opened}): ${i.subject}`).join('; ')}</td></tr>
      </tbody></table>
      {similar.length > 0 && (
        <>
          <h4>Earlier complaints the AI found describing the same failure</h4>
          {similar.map(s => (
            <div key={s.odino} className="similar">
              <button className="link mono" onClick={() => toggle(s.odino)}>{s.odino}</button> “{s.quote}”
              {open[s.odino] && <Quoted text={open[s.odino]} marks={[{ quote: s.quote, label: String(s.odino) }]} />}
            </div>
          ))}
        </>
      )}
    </section>
  )
}
