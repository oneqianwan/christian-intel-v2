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
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          padding: '12px 16px 0',
          background: '#f5f5f5',
        }}>
          <button
            onClick={() => setShowSettings((prev) => !prev)}
            style={{
              border: '1px solid #d1d5db',
              background: '#fff',
              borderRadius: '999px',
              padding: '8px 14px',
              fontSize: '13px',
              cursor: 'pointer',
              color: '#374151',
            }}
          >
            {showSettings ? '关闭设置' : '打开设置'}
          </button>
        </div>
        <ChatArea />
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
