import { useState } from 'react'
import Sidebar from './Sidebar'
import ChatArea from './ChatArea'
import ApiKeyManager from './ApiKeyManager'

function Layout() {
  const [sidebarWidth] = useState(260)
  const [showSettings, setShowSettings] = useState(false)

  return (
    <div style={{ display: 'flex', width: '100vw', height: '100vh', position: 'relative' }}>
      <div style={{ width: sidebarWidth, minWidth: 200, maxWidth: 400, borderRight: '1px solid #e0e0e0', background: '#fff', display: 'flex', flexDirection: 'column' }}>
        <Sidebar />
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <ChatArea
          showSettings={showSettings}
          onToggleSettings={() => setShowSettings((prev) => !prev)}
        />
      </div>
      {showSettings && (
        <div style={{
          width: '420px',
          maxWidth: '42vw',
          borderLeft: '1px solid #e5e7eb',
          background: '#f8fafc',
          padding: '16px',
          overflow: 'auto',
        }}>
          <ApiKeyManager />
        </div>
      )}
    </div>
  )
}

export default Layout
