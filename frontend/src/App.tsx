import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import { OrgDetailPage } from './pages/OrgDetailPage'
import { PricingPage } from './pages/PricingPage'

function App() {
  return (
    <Routes>
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/dashboard/org/:orgId" element={<OrgDetailPage />} />
      <Route path="/pricing" element={<PricingPage />} />
      <Route path="*" element={<Layout />} />
    </Routes>
  )
}

export default App
