import { highlight } from '../lib/highlight'

/** Source text with the AI's quotes highlighted in place, so a reader sees each quote in its full context. */
export function Quoted({ text, marks, active }: { text: string; marks: { quote: string; label: string }[]; active?: string | null }) {
  return (
    <p className="quoted">
      {highlight(text, marks).map((s, i) =>
        s.mark ? <mark key={i} className={active && s.mark !== active ? 'dim' : ''} title={s.mark}>{s.text}</mark> : <span key={i}>{s.text}</span>,
      )}
    </p>
  )
}
