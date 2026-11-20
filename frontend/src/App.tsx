import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Outlet, Route, Routes } from 'react-router-dom'
import { ops } from './api/client'
import { EvalPage } from './ops/EvalPage'
import { RunPage, RunsPage } from './ops/RunsPage'
import { InboxPage } from './workspace/InboxPage'
import { IssuePage, IssuesPage } from './workspace/IssuesPage'
import { TicketPage } from './workspace/TicketPage'

/** The analyst's product: inbox, tickets, emerging issues. No system internals. */
function WorkspaceLayout() {
  return (
    <>
      <header className="top">
        <strong>Recall Match</strong>
        <nav>
          <NavLink to="/" end>Inbox</NavLink>
          <NavLink to="/issues">Emerging issues</NavLink>
        </nav>
        <NavLink to="/ops" className="small muted">Operations ↗</NavLink>
      </header>
      <main><Outlet /></main>
    </>
  )
}

function ModelStatus() {
  const [h, setH] = useState<{ model: string | null } | null>(null)
  useEffect(() => { ops.health().then(setH).catch(() => setH(null)) }, [])
  if (!h) return <span className="small">API offline</span>
  return <span className="small">{h.model ? `model ${h.model}` : 'no model configured · rules only'}</span>
}

/** For the people who build and run the system: runs, audit trails, failure drills, evaluation. */
function OpsLayout() {
  return (
    <>
      <header className="top ops">
        <strong>Recall Match · Operations</strong>
        <nav>
          <NavLink to="/ops" end>AI runs</NavLink>
          <NavLink to="/ops/eval">Evaluation</NavLink>
        </nav>
        <ModelStatus />
        <NavLink to="/" className="small">← Workspace</NavLink>
      </header>
      <main><Outlet /></main>
    </>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<WorkspaceLayout />}>
          <Route path="/" element={<InboxPage />} />
          <Route path="/tickets/:odino" element={<TicketPage />} />
          <Route path="/issues" element={<IssuesPage />} />
          <Route path="/issues/:id" element={<IssuePage />} />
        </Route>
        <Route element={<OpsLayout />}>
          <Route path="/ops" element={<RunsPage />} />
          <Route path="/ops/runs/:id" element={<RunPage />} />
          <Route path="/ops/eval" element={<EvalPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
