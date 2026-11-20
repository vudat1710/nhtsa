import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { CaseView, Complaint, Result, Review } from '../api/types'
import { AuditTrail } from '../components/AuditTrail'
import { ComplaintPanel } from '../components/ComplaintPanel'
import { DecisionCard } from '../components/DecisionCard'
import { EvidencePanel } from '../components/EvidencePanel'
import { RecallChecks } from '../components/RecallChecks'
import { ReviewPanel } from '../components/ReviewPanel'
import { RunPanel } from '../components/RunPanel'

/** One case file. /case/:odino for a stored complaint, /result/:id for any stored run (incl. typed complaints). */
export function CasePage() {
  const { odino, id } = useParams()
  const key = odino ?? id ?? ''
  const [loaded, setLoaded] = useState<{ key: string; view: CaseView | null; error: string }>({ key: '', view: null, error: '' })
  const [focused, setFocused] = useState<string | null>(null)

  useEffect(() => {
    const load = odino ? api.case(Number(odino))
      : api.result(id!).then(r => ({ complaint: r.complaint, result: r, reviews: [], demo: null }) as CaseView)
    load.then(view => setLoaded({ key, view, error: '' })).catch(e => setLoaded({ key, view: null, error: String(e) }))
  }, [odino, id, key])

  const view = loaded.key === key ? loaded.view : null
  const setView = (v: CaseView) => setLoaded({ key, view: v, error: '' })
  if (loaded.key === key && loaded.error) return <p className="alert-text">{loaded.error}</p>
  if (!view) return <p className="muted">Loading…</p>
  const { complaint, result, reviews, demo } = view
  const target: number | Complaint = complaint.odino ?? complaint
  const done = (r: Result) => setView({ ...view, result: r, reviews: [] })
  const saved = (r: Review) => setView({ ...view, reviews: [...view.reviews, r] })

  return (
    <>
      <p><Link to="/">← Queue</Link></p>
      {demo && <div className="demo-banner"><strong>Demo {demo.id}: {demo.title}.</strong> {demo.story}</div>}
      <RunPanel target={target} onDone={done} />
      <div className="case-grid">
        <div>
          <ComplaintPanel complaint={complaint} intake={result?.intake} judgment={result?.judgment} active={focused} />
          {result && <EvidencePanel result={result} />}
        </div>
        <div>
          {result ? (
            <>
              <DecisionCard result={result} />
              <RecallChecks result={result} focused={focused} onFocus={setFocused} />
              <ReviewPanel result={result} reviews={reviews} onSaved={saved} />
              {demo?.next && (
                <details className="card hindsight">
                  <summary>What happened next (hindsight, never shown to the system)</summary>
                  <p>{demo.next}</p>
                </details>
              )}
              <AuditTrail result={result} />
            </>
          ) : <section className="card muted">Not checked yet. Run it above.</section>}
        </div>
      </div>
    </>
  )
}
