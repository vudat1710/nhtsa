import type { Complaint, Intake, Judgment } from '../../api/types'
import { INTAKE_FLAG, ticketName } from '../../lib/labels'
import { Chip } from '../../shared/Badges'
import { Quoted } from '../../shared/Quoted'

/** The complaint exactly as the AI saw it (recall numbers masked), with the quotes it relied on highlighted. */
export function ComplaintPanel({ complaint, intake, judgment, active }: {
  complaint: Complaint; intake?: Intake; judgment?: Judgment | null; active?: string | null
}) {
  const c = complaint
  const marks = judgment?.checks.map(ch => ({ quote: ch.complaint_quote, label: ch.campno })) ?? []
  return (
    <section className="card">
      <h3>Complaint {ticketName(c.odino)}</h3>
      <p className="muted">{c.year} {c.make} {c.model} · received {c.received} · {c.components.join(', ') || 'no component chosen'}</p>
      <div className="chips">
        {c.crash > 0 && <Chip tone="alert">Crash</Chip>}
        {c.fire > 0 && <Chip tone="alert">Fire</Chip>}
        {c.injured > 0 && <Chip tone="alert">{c.injured} injured</Chip>}
        {intake?.flags.filter(f => f !== 'severe').map(f => <Chip key={f} tone="info">{INTAKE_FLAG[f] ?? f}</Chip>)}
        {intake && intake.masked > 0 && <Chip>{intake.masked} recall number{intake.masked > 1 ? 's' : ''} hidden from the AI</Chip>}
      </div>
      <Quoted text={intake?.text ?? c.text} marks={marks} active={active} />
    </section>
  )
}
