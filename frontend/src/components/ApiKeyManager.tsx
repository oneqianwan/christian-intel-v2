import { useCallback, useEffect, useMemo, useState } from 'react'

type ApiKeyStatus = 'active' | 'limited' | 'invalid' | 'unknown'

interface ApiKeyItem {
  id: string
  name: string
  key: string
  status: ApiKeyStatus
  usage?: string
  lastChecked?: string
}

interface AgentStatus {
  last_run?: string | null
  next_run?: string
  today_tasks: number
  pending_auto_tasks: number
  apis?: Record<string, string>
}

interface AgentLog {
  level?: string
  module: string
  message: string
  created_at?: string
}

const STORAGE_KEY = 'watcher-api-keys-draft'

const DEFAULT_KEYS: ApiKeyItem[] = [
  { id: 'youtube', name: 'YouTube Data API', key: '', status: 'unknown' },
  { id: 'google_cse', name: 'Google Custom Search', key: '', status: 'unknown' },
  { id: 'rss2json', name: 'RSSAPI / rss2json', key: '', status: 'unknown' },
  { id: 'newsapi', name: 'NewsAPI', key: '', status: 'unknown' },
  { id: 'scrapingbee', name: 'ScrapingBee', key: '', status: 'unknown' },
  { id: 'twitter', name: 'Twitter API v2', key: '', status: 'unknown' },
  { id: 'reddit', name: 'Reddit API', key: '', status: 'unknown' },
]

function maskKey(value: string) {
  if (!value) return ''
  if (value.length <= 8) return '*'.repeat(value.length)
  return `${value.slice(0, 4)}${'*'.repeat(Math.max(value.length - 8, 4))}${value.slice(-4)}`
}

function statusMeta(status: ApiKeyStatus) {
  switch (status) {
    case 'active':
      return { icon: 'OK', color: '#16a34a', label: '正常' }
    case 'limited':
      return { icon: '!', color: '#d97706', label: '额度紧张' }
    case 'invalid':
      return { icon: 'X', color: '#dc2626', label: '密钥无效' }
    default:
      return { icon: '?', color: '#9ca3af', label: '未检测' }
  }
}

export function ApiKeyManager() {
  const [keys, setKeys] = useState<ApiKeyItem[]>(DEFAULT_KEYS)
  const [showKey, setShowKey] = useState<Record<string, boolean>>({})
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null)
  const [agentLogs, setAgentLogs] = useState<AgentLog[]>([])
  const [agentRunning, setAgentRunning] = useState(false)
  const [lastRefresh, setLastRefresh] = useState('')
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true)

  const fetchLogs = useCallback(async () => {
    try {
      const response = await fetch('/api/agent/logs?limit=10')
      if (!response.ok) return
      const data = await response.json() as { logs?: AgentLog[] }
      setAgentLogs(data.logs || [])
      setLastRefresh(new Date().toLocaleTimeString())
    } catch {
      // Agent接口未就绪时静默忽略
    }
  }, [])

  useEffect(() => {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    try {
      const parsed = JSON.parse(raw) as ApiKeyItem[]
      if (Array.isArray(parsed) && parsed.length) {
        setKeys(parsed)
      }
    } catch (error) {
      console.error('加载 API Key 草稿失败:', error)
    }
  }, [])

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(keys))
  }, [keys])

  useEffect(() => {
    const loadAgentPanel = async () => {
      try {
        const statusResponse = await fetch('/api/agent/status')

        if (statusResponse.ok) {
          const data = await statusResponse.json() as AgentStatus
          setAgentStatus(data)
        }
      } catch {
        // Agent接口未就绪时静默忽略
      }
    }

    void loadAgentPanel()
  }, [])

  useEffect(() => {
    if (!autoRefreshEnabled) return

    void fetchLogs()
    const intervalId = window.setInterval(() => {
      void fetchLogs()
    }, 30000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [autoRefreshEnabled, fetchLogs])

  const summary = useMemo(() => {
    const filled = keys.filter((item) => item.key.trim()).length
    return `已录入 ${filled}/${keys.length} 个密钥`
  }, [keys])

  const toggleShowKey = (id: string) => {
    setShowKey((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const updateKey = (id: string, newKey: string) => {
    setKeys((prev) => prev.map((item) => (
      item.id === id
        ? {
            ...item,
            key: newKey,
            status: newKey.trim() ? 'unknown' : 'unknown',
          }
        : item
    )))
  }

  const markChecked = (id: string) => {
    setKeys((prev) => prev.map((item) => (
      item.id === id
        ? {
            ...item,
            status: item.key.trim() ? 'limited' : 'unknown',
            usage: item.key.trim() ? '待后端检测' : undefined,
            lastChecked: new Date().toLocaleString(),
          }
        : item
    )))
  }

  const triggerAgent = async () => {
    try {
      setAgentRunning(true)
      const response = await fetch('/api/agent/run', { method: 'POST' })
      if (!response.ok) {
        throw new Error('触发失败')
      }
      const result = await response.json() as { message?: string }
      window.alert(result.message || 'Agent已触发')

      const statusResponse = await fetch('/api/agent/status')
      if (statusResponse.ok) {
        const status = await statusResponse.json() as AgentStatus
        setAgentStatus(status)
      }
      await fetchLogs()
    } catch (error) {
      console.error('触发 Agent 失败:', error)
      window.alert('Agent触发失败')
    } finally {
      setAgentRunning(false)
    }
  }

  const handleManualRefresh = async () => {
    await fetchLogs()
  }

  return (
    <div style={{
      background: '#fff',
      border: '1px solid #e5e7eb',
      borderRadius: '12px',
      padding: '16px',
      boxShadow: '0 6px 18px rgba(15, 23, 42, 0.06)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#111827' }}>API 密钥管理</div>
          <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>{summary}</div>
        </div>
        <div style={{
          fontSize: '12px',
          color: '#475569',
          background: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: '999px',
          padding: '4px 10px',
        }}>
          本地草稿模式
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {keys.map((item) => {
          const meta = statusMeta(item.status)
          const visibleValue = showKey[item.id] ? item.key : maskKey(item.key)
          return (
            <div key={item.id} style={{
              border: '1px solid #e5e7eb',
              borderRadius: '10px',
              padding: '12px',
              background: '#fcfcfd',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                <div style={{
                  width: '22px',
                  height: '22px',
                  borderRadius: '999px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '11px',
                  fontWeight: 700,
                  color: '#fff',
                  background: meta.color,
                }}>
                  {meta.icon}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: '#111827' }}>{item.name}</div>
                  <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>
                    状态：{meta.label}
                    {item.usage ? ` · ${item.usage}` : ''}
                    {item.lastChecked ? ` · 检测：${item.lastChecked}` : ''}
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input
                  type={showKey[item.id] ? 'text' : 'password'}
                  value={showKey[item.id] ? item.key : visibleValue}
                  onChange={(e) => updateKey(item.id, e.target.value)}
                  placeholder="输入 API 密钥"
                  style={{
                    flex: 1,
                    minWidth: 0,
                    border: '1px solid #d1d5db',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    fontSize: '13px',
                    outline: 'none',
                    background: '#fff',
                  }}
                />
                <button
                  onClick={() => toggleShowKey(item.id)}
                  style={{
                    border: '1px solid #d1d5db',
                    borderRadius: '8px',
                    background: '#fff',
                    padding: '9px 12px',
                    cursor: 'pointer',
                    fontSize: '12px',
                  }}
                >
                  {showKey[item.id] ? '隐藏' : '显示'}
                </button>
                <button
                  onClick={() => markChecked(item.id)}
                  style={{
                    border: '1px solid #d1d5db',
                    borderRadius: '8px',
                    background: '#f8fafc',
                    padding: '9px 12px',
                    cursor: 'pointer',
                    fontSize: '12px',
                  }}
                >
                  测试
                </button>
              </div>
            </div>
          )
        })}
      </div>

      <div style={{ marginTop: '12px', fontSize: '12px', lineHeight: 1.7, color: '#6b7280' }}>
        <div>• 当前为前端框架占位，后续可直接改成调用后端保存与测试接口。</div>
        <div>• 密钥现在只保存在浏览器本地草稿，不会自动提交到后端。</div>
        <div>• 后端 API 就绪后，可保留这套交互结构直接接线。</div>
      </div>

      {agentStatus && (
        <div style={{
          marginTop: '16px',
          paddingTop: '16px',
          borderTop: '1px solid #e5e7eb',
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '10px',
          }}>
            <div style={{ fontSize: '15px', fontWeight: 700, color: '#111827' }}>
              Agent 状态
            </div>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '12px',
              color: '#4b5563',
              cursor: 'pointer',
            }}>
              <input
                type="checkbox"
                checked={autoRefreshEnabled}
                onChange={(e) => setAutoRefreshEnabled(e.target.checked)}
                style={{ width: '13px', height: '13px' }}
              />
              自动刷新
            </label>
          </div>
          <div style={{ fontSize: '13px', lineHeight: 1.8, color: '#374151' }}>
            <div>上次运行：{agentStatus.last_run || '未运行'}</div>
            <div>下次策略：{agentStatus.next_run || '未知'}</div>
            <div>今日任务：{agentStatus.today_tasks}</div>
            <div>待处理：{agentStatus.pending_auto_tasks}</div>
          </div>
          {lastRefresh && (
            <div style={{ fontSize: '12px', color: '#9ca3af', marginTop: '8px' }}>
              上次刷新：{lastRefresh}
              {autoRefreshEnabled && <span style={{ color: '#16a34a', marginLeft: '6px' }}>●</span>}
            </div>
          )}
          <button
            onClick={() => { void triggerAgent() }}
            disabled={agentRunning}
            style={{
              marginTop: '12px',
              border: '1px solid #4f46e5',
              borderRadius: '8px',
              background: agentRunning ? '#c7d2fe' : '#4f46e5',
              color: '#fff',
              padding: '9px 14px',
              cursor: agentRunning ? 'not-allowed' : 'pointer',
              fontSize: '12px',
              fontWeight: 600,
            }}
          >
            {agentRunning ? '触发中...' : '手动触发 Agent'}
          </button>
          <div style={{
            marginTop: '16px',
            paddingTop: '16px',
            borderTop: '1px solid #e5e7eb',
          }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '8px',
            }}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827' }}>
                最近日志
              </div>
              <button
                onClick={() => { void handleManualRefresh() }}
                style={{
                  border: '1px solid #d1d5db',
                  borderRadius: '8px',
                  background: '#f3f4f6',
                  padding: '5px 10px',
                  cursor: 'pointer',
                  fontSize: '12px',
                  color: '#374151',
                }}
              >
                刷新
              </button>
            </div>
            <div style={{ fontSize: '12px', color: '#9ca3af', marginBottom: '8px' }}>
              自动刷新：30秒
            </div>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              maxHeight: '192px',
              overflowY: 'auto',
            }}>
              {agentLogs.map((log, index) => {
                const background =
                  log.level === 'error'
                    ? '#fef2f2'
                    : log.level === 'warning'
                      ? '#fefce8'
                      : '#f9fafb'
                const color =
                  log.level === 'error'
                    ? '#b91c1c'
                    : log.level === 'warning'
                      ? '#a16207'
                      : '#374151'

                return (
                  <div
                    key={`${log.module}-${index}-${log.created_at || ''}`}
                    style={{
                      fontSize: '12px',
                      padding: '8px 10px',
                      background,
                      borderRadius: '8px',
                      color,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ color: '#6b7280' }}>[{log.module}]</span>
                      <span>{log.message}</span>
                    </div>
                    <div style={{ color: '#9ca3af', marginTop: '4px' }}>
                      {log.created_at ? new Date(log.created_at).toLocaleTimeString() : '--:--:--'}
                    </div>
                  </div>
                )
              })}
              {agentLogs.length === 0 && (
                <div style={{ fontSize: '12px', color: '#9ca3af' }}>暂无日志</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ApiKeyManager
