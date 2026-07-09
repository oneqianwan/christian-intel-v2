import type { ReactElement } from 'react'
import { Route, Routes } from 'react-router-dom'
import { AdminGuard } from './auth/AdminGuard'
import { AuthGuard } from './auth/AuthGuard'
import { isAuthRequired } from './auth/flags'
import { AdminLayout } from './components/AdminLayout'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import { getWatchAlertIdentityMode } from './features/watchAlerts/identity'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { LoginPage } from './pages/LoginPage'
import { OrgDetailPage } from './pages/OrgDetailPage'
import { PricingPage } from './pages/PricingPage'
import { AlertsPage } from './pages/AlertsPage'
import { SecuritySettingsPage } from './pages/SecuritySettingsPage'
import { WatchlistPage } from './pages/WatchlistPage'

function App() {
  const watchAlertIdentityMode = getWatchAlertIdentityMode()

  const wrapAppRoute = (element: ReactElement) => {
    if (!isAuthRequired()) {
      return element
    }
    return <AuthGuard>{element}</AuthGuard>
  }

  const wrapWatchAlertRoute = (element: ReactElement) => {
    if (watchAlertIdentityMode !== 'authenticated-user') {
      return element
    }
    return <AuthGuard requireEnabled>{element}</AuthGuard>
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/admin"
        element={
          <AdminGuard>
            <AdminLayout>
              <AdminUsersPage />
            </AdminLayout>
          </AdminGuard>
        }
      />
      <Route
        path="/admin/users"
        element={
          <AdminGuard>
            <AdminLayout>
              <AdminUsersPage />
            </AdminLayout>
          </AdminGuard>
        }
      />
      <Route path="/settings/security" element={<AuthGuard requireEnabled><SecuritySettingsPage /></AuthGuard>} />
      <Route path="/dashboard" element={wrapAppRoute(<Dashboard />)} />
      <Route path="/dashboard/org/:orgId" element={wrapAppRoute(<OrgDetailPage />)} />
      <Route path="/watchlist" element={wrapWatchAlertRoute(<WatchlistPage />)} />
      <Route path="/alerts" element={wrapWatchAlertRoute(<AlertsPage />)} />
      <Route path="/pricing" element={wrapAppRoute(<PricingPage />)} />
      <Route path="*" element={wrapAppRoute(<Layout />)} />
    </Routes>
  )
}

export default App
