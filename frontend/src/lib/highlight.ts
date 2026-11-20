// Find a quote inside its source text the same way the verifier does (case, spacing and curly quotes ignored),
// and return the [start, end) range in the ORIGINAL text so it can be highlighted in context.

function norm(c: string): string {
  return c.toLowerCase().replace(/[’‘]/g, "'").replace(/[“”]/g, '"')
}

export function findQuote(source: string, quote: string): [number, number] | null {
  const q = norm(quote).replace(/\s+/g, ' ').trim().replace(/^[\s.,;:!?"'…]+|[\s.,;:!?"'…]+$/g, '')
  if (!q) return null
  // map normalized (single-spaced) positions back to original positions
  const map: number[] = []
  let flat = ''
  for (let i = 0; i < source.length; i++) {
    const ch = norm(source[i])
    if (/\s/.test(ch)) {
      if (flat.endsWith(' ') || flat.length === 0) continue
      flat += ' '
    } else flat += ch
    map.push(i)
  }
  const at = flat.indexOf(q)
  if (at < 0) return null
  return [map[at], map[at + q.length - 1] + 1]
}

export interface Span { text: string; mark: string | null }

/** Split text into plain and highlighted spans; marks = [{quote, label}], overlapping marks keep the first. */
export function highlight(source: string, marks: { quote: string; label: string }[]): Span[] {
  const ranges = marks
    .map(m => ({ r: findQuote(source, m.quote), label: m.label }))
    .filter((m): m is { r: [number, number]; label: string } => m.r !== null)
    .sort((a, b) => a.r[0] - b.r[0])
  const out: Span[] = []
  let pos = 0
  for (const { r, label } of ranges) {
    if (r[0] < pos) continue
    if (r[0] > pos) out.push({ text: source.slice(pos, r[0]), mark: null })
    out.push({ text: source.slice(r[0], r[1]), mark: label })
    pos = r[1]
  }
  if (pos < source.length) out.push({ text: source.slice(pos), mark: null })
  return out
}
