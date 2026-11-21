import type { Result } from '../../api/types'

/** Facts computed by code (never by the AI): earlier complaints, investigations, and complaints the AI cited. */
export function EvidencePanel({ result }: { result: Result }) {
  const { stats, investigations } = result.evidence
  const similar = result.judgment?.similar ?? []
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
          <h4>Earlier complaints the AI found describing the same failure (quotes found word for word)</h4>
          {similar.map(s => <div key={s.odino} className="similar"><span className="mono">{s.odino}</span> “{s.quote}”</div>)}
        </>
      )}
    </section>
  )
}
