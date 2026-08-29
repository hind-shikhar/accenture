import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './Dashboard'
import Tester from './Tester'
import './index.css'

function Nav() {
  const base = 'px-4 py-2 text-sm font-semibold rounded-lg transition-colors'
  const active = `${base} bg-blue-600 text-white`
  const inactive = `${base} text-gray-400 hover:text-white hover:bg-gray-800`
  return (
    <nav className="bg-[#0A0E17] border-b border-gray-800 px-8 py-3 flex gap-3">
      <NavLink to="/" end className={({ isActive }) => isActive ? active : inactive}>
        Dashboard
      </NavLink>
      <NavLink to="/tester" className={({ isActive }) => isActive ? active : inactive}>
        Policy Tester
      </NavLink>
    </nav>
  )
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/tester" element={<Tester />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
)
