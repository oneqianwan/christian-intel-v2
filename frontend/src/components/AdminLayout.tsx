import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

type AdminLayoutProps = {
  children: ReactNode
}

function navStyle(active: boolean) {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '10px 14px',
    borderRadius: '10px',
    border: `1px solid ${active ? '#c7d2fe' : '#cbd5e1'}`,
    background: active ? '#eef2ff' : '#fff',
    color: active ? '#4338ca' : '#0f172a',
    fontWeight: active ? 700 : 600,
    textDecoration: 'none',
  } as const
}

export function AdminLayout({ children }: AdminLayoutProps) {
  const navigate = useNavigate()

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc', color: '#0f172a' }}>
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          borderBottom: '1px solid #e2e8f0',
          background: '#fff',
        }}
      >
        <div
          style={{
            maxWidth: '1180px',
            margin: '0 auto',
            padding: '20px 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '16px',
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#6366f1', letterSpacing: '0.04em' }}>ADMIN</div>
            <h1 style={{ margin: '6px 0 0', fontSize: '26px' }}>用户管理</h1>
            <p style={{ margin: '8px 0 0', color: '#475569', lineHeight: 1.6 }}>
              前端 Guard 仅用于界面控制，最终权限边界仍由后端 RBAC 决定。
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <NavLink to="/admin" end style={({ isActive }) => navStyle(isActive)}>
              Users
            </NavLink>
            <NavLink to="/admin/users" style={({ isActive }) => navStyle(isActive)}>
              Users API
            </NavLink>
            <button
              type="button"
              onClick={() => navigate('/dashboard')}
              style={{
                border: '1px solid #cbd5e1',
                borderRadius: '10px',
                padding: '10px 14px',
                background: '#fff',
                color: '#0f172a',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              返回 Dashboard
            </button>
          </div>
        </div>
      </header>
      <main style={{ maxWidth: '1180px', margin: '0 auto', padding: '24px' }}>{children}</main>
    </div>
  )
}
