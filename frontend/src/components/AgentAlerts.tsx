import { useEffect, useMemo, useState } from 'react'

interface AlertItem {
  id: string
  category: string
  severity: 'high' | 'medium'
  message: string
  time: string
  read: boolean
}

interface ConversationSummary {
  id: string
}

interface ConversationMessage {
  id?: string
  content?: string
  created_at?: string
  delivery_type?: string
}

function extractCategory(content: string): string {
  const match = content.match(/预警[：:]\s*([^*\n]+)/)
  return match?.[1]?.trim() || '未知类别'
}

function stripAlertHeading(content: string): string {
  return content
    .replace(/^🤖\s*\*\*Agent通知\*\*\s*/m, '')
    .replace(/🚨\s*\*\*突发关键词预警[^*]*\*\*\s*/m, '')
    .trim()
}

export function AgentAlerts() {
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const convResponse = await fetch('/api/conversations?limit=1')
        if (!convResponse.ok) return
        const convs = await convResponse.json() as ConversationSummary[]
        if (!Array.isArray(convs) || convs.length === 0) {
          setAlerts([])
          return
        }

        const convId = convs[0].id
        const msgResponse = await fetch(`/api/conversations/${convId}/messages?limit=20`)
        if (!msgResponse.ok) return
        const msgs = await msgResponse.json() as ConversationMessage[]
        if (!Array.isArray(msgs)) {
          setAlerts([])
          return
        }

        const surgeMsgs = msgs
          .filter((msg) => msg.delivery_type === 'agent_notification' && msg.content?.includes('🚨'))
          .map((msg, index) => ({
            id: msg.id || `alert-${index}`,
            category: extractCategory(msg.content || ''),
            severity: msg.content?.includes('高危') || msg.content?.includes('🚨') ? 'high' as const : 'medium' as const,
            message: stripAlertHeading(msg.content || ''),
            time: msg.created_at ? new Date(msg.created_at).toLocaleTimeString() : '--:--:--',
            read: false,
          }))

        setAlerts(surgeMsgs)
      } catch {
        // 静默忽略，避免影响主聊天区
      }
    }

    void fetchAlerts()
    const intervalId = window.setInterval(() => {
      void fetchAlerts()
    }, 60000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [])

  const unreadCount = useMemo(() => alerts.filter((alert) => !alert.read).length, [alerts])

  if (alerts.length === 0) return null

  return (
    <div style={{ marginBottom: '16px' }}>
      <button
        onClick={() => setExpanded((prev) => !prev)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          borderRadius: '12px',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          color: '#fff',
          background: unreadCount > 0
            ? 'linear-gradient(90deg, #ef4444 0%, #f97316 100%)'
            : 'linear-gradient(90deg, #6b7280 0%, #4b5563 100%)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>🚨</span>
          <span style={{ fontWeight: 700 }}>Agent预警</span>
          {unreadCount > 0 && (
            <span style={{
              background: '#fff',
              color: '#dc2626',
              fontSize: '12px',
              padding: '2px 8px',
              borderRadius: '999px',
              fontWeight: 700,
            }}>
              {unreadCount}
            </span>
          )}
        </div>
        <span style={{ fontSize: '18px' }}>{expanded ? '▼' : '▶'}</span>
      </button>

      {expanded && (
        <div style={{ marginTop: '8px', display: 'grid', gap: '8px' }}>
          {alerts.map((alert) => {
            const high = alert.severity === 'high'
            return (
              <div
                key={alert.id}
                style={{
                  padding: '12px',
                  borderRadius: '12px',
                  borderLeft: high ? '4px solid #ef4444' : '4px solid #eab308',
                  background: high ? '#fef2f2' : '#fefce8',
                }}
              >
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '6px',
                }}>
                  <span style={{
                    fontSize: '12px',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: '999px',
                    background: high ? '#fee2e2' : '#fef3c7',
                    color: high ? '#b91c1c' : '#a16207',
                  }}>
                    {high ? '高危' : '中危'} · {alert.category}
                  </span>
                  <span style={{ fontSize: '12px', color: '#6b7280' }}>{alert.time}</span>
                </div>
                <div style={{ fontSize: '14px', color: '#1f2937', whiteSpace: 'pre-line' }}>
                  {alert.message}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default AgentAlerts
