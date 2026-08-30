import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './Dashboard'
import Tester from './Tester'
import { UtilityBar } from './ui'
import './index.css'

function Nav() {
  const base = 'font-mono text-xs uppercase tracking-[0.2em] px-4 py-2 border-b-2 transition-colors'
  const active = `${base} border-rust text-ink`
  const inactive = `${base} border-transparent text-charcoal hover:text-ink hover:border-hairline`
  return (
    <header className="bg-parchment sticky top-0 z-40 border-b border-hairline">
      <UtilityBar right="ENTERPRISE AI GOVERNANCE" />
      <div className="flex items-end justify-between px-6 pt-4 pb-0 border-t border-hairline">
        <div className="pb-3">
          <h1 className="font-serif text-2xl leading-none text-ink">
            ControlPlane<span className="font-serif-italic text-rust">.ai</span>
          </h1>
        </div>
        <nav className="flex gap-1">
          <NavLink to="/" end className={({ isActive }) => isActive ? active : inactive}>
            I. Dashboard
          </NavLink>
          <NavLink to="/tester" className={({ isActive }) => isActive ? active : inactive}>
            II. Policy Tester
          </NavLink>
        </nav>
      </div>
    </header>
  )
}

function Footer() {
  return (
    <footer className="border-t border-hairline mt-16">
      <UtilityBar left="§ FIN — CONTROLPLANE.AI" right={`BUILD 2026.08 · GOVERNANCE ENGINE`} />
    </footer>
  )
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-parchment text-ink">
        <Nav />
        <div className="flex-1">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/tester" element={<Tester />} />
          </Routes>
        </div>
        <Footer />
      </div>
    </BrowserRouter>
  </StrictMode>
)
