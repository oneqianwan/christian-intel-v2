import Layout from './components/Layout'
import Dashboard from './components/Dashboard'

function App() {
  if (window.location.pathname === '/dashboard') {
    return <Dashboard />
  }
  return <Layout />
}

export default App
