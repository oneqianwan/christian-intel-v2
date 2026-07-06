type AuthLoadingScreenProps = {
  title?: string
  description?: string
}

export function AuthLoadingScreen({
  title = '正在校验登录状态',
  description = '请稍候，系统正在恢复当前会话。',
}: AuthLoadingScreenProps) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        background: '#f8fafc',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '420px',
          borderRadius: '18px',
          border: '1px solid #e2e8f0',
          background: '#fff',
          boxShadow: '0 18px 45px rgba(15, 23, 42, 0.08)',
          padding: '28px',
          textAlign: 'center',
        }}
      >
        <div
          aria-hidden="true"
          style={{
            width: '40px',
            height: '40px',
            margin: '0 auto 16px',
            borderRadius: '999px',
            border: '3px solid #cbd5f5',
            borderTopColor: '#4f46e5',
            animation: 'auth-spin 1s linear infinite',
          }}
        />
        <h1 style={{ margin: '0 0 8px', fontSize: '20px', color: '#0f172a' }}>{title}</h1>
        <p style={{ margin: 0, color: '#475569', lineHeight: 1.6 }}>{description}</p>
      </div>
    </div>
  )
}
