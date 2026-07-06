import type { ReactElement } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AuthGuard } from './auth/AuthGuard'
import { isAuthRequired } from './auth/flags'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import { LoginPage } from './pages/LoginPage'
import { OrgDetailPage } from './pages/OrgDetailPage'
import { PricingPage } from './pages/PricingPage'
import { AlertsPage } from './pages/AlertsPage'
import { SecuritySettingsPage } from './pages/SecuritySettingsPage'
import { WatchlistPage } from './pages/WatchlistPage'

function App() {
  const wrapAppRoute = (element: ReactElement) => {
    if (!isAuthRequired()) {
      return element
    }
    return <AuthGuard>{element}</AuthGuard>
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/settings/security" element={<AuthGuard requireEnabled><SecuritySettingsPage /></AuthGuard>} />
      <Route path="/dashboard" element={wrapAppRoute(<Dashboard />)} />
      <Route path="/dashboard/org/:orgId" element={wrapAppRoute(<OrgDetailPage />)} />
      <Route path="/watchlist" element={wrapAppRoute(<WatchlistPage />)} />
      <Route path="/alerts" element={wrapAppRoute(<AlertsPage />)} />
      <Route path="/pricing" element={wrapAppRoute(<PricingPage />)} />
      <Route path="*" element={wrapAppRoute(<Layout />)} />
    </Routes>
  )
}

export default App
