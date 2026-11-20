import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api/client'
import { CasePage } from './pages/CasePage'
import { NewComplaintPage } from './pages/NewComplaintPage'
import { QueuePage } from './pages/QueuePage'
import { ReviewsPage } from './pages/ReviewsPage'
import { TrustPage } from './pages/TrustPage'

function ModelStatus() {
  const [h, setH] = useState<{ llm_mode: string; model: string | null } | null>(null)
  useEffect(() => { api.health().then(setH).catch(() => setH(null)) }, [])
  if (!h) return <span className="muted small">API offline</span>
  return <span className="muted small">{h.model ? `model ${h.model} · ${h.llm_mode}` : 'no model configured · replaying recorded answers'}</span>
}

export function App() {
  return (
    <BrowserRouter>
      <header className="top">
        <strong>Recall Match</strong>
        <nav>
          <NavLink to="/" end>Queue</NavLink>
          <NavLink to="/reviews">Engineer review</NavLink>
          <NavLink to="/new">New complaint</NavLink>
          <NavLink to="/trust">Can you trust it?</NavLink>
        </nav>
        <ModelStatus />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<QueuePage />} />
          <Route path="/case/:odino" element={<CasePage />} />
          <Route path="/result/:id" element={<CasePage />} />
          <Route path="/reviews" element={<ReviewsPage />} />
          <Route path="/new" element={<NewComplaintPage />} />
          <Route path="/trust" element={<TrustPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
