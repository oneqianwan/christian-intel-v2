import { useCallback, useEffect, useMemo, useState } from 'react'

interface CollectionTask {
  id: string
  status: string
  task_type: string
  keywords: string[]
  country?: string
  collected: number
  failed: number
  deduped?: number
  total_expected: number
  created_at: string
  started_at?: string
  finished_at?: string
  error_message?: string
}

interface CollectionPreset {
  label: string
  keywords: string[]
  country?: string | null
}

const API_BASE = 'http://localhost:8000/api/collection'

const COLLECTION_SOURCES = [
  { value: 'newsapi', label: '📰 NewsAPI', desc: '新闻聚合，全球覆盖' },
  { value: 'rss', label: '📡 RSS源', desc: '基督教媒体RSS' },
  { value: 'webpage', label: '🕷️ 网页爬虫', desc: '动态渲染，深度采集' },
]

export function CollectionPanel() {
  const [keywords, setKeywords] = useState('')
  const [country, setCountry] = useState('')
  const [source, setSource] = useState('newsapi')
  const [isRunning, setIsRunning] = useState(false)
  const [currentTask, setCurrentTask] = useState<CollectionTask | null>(null)
  const [recentTasks, setRecentTasks] = useState<CollectionTask[]>([])
  const [message, setMessage] = useState('')
  const [presets, setPresets] = useState<CollectionPreset[]>([])

  const activeSource = useMemo(
    () => COLLECTION_SOURCES.find((item) => item.value === source),
    [source]
  )

  const fetchRecentTasks = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/recent`)
      const data = await res.json()
      const tasks = data.tasks || []
      setRecentTasks(tasks)

      if (!currentTask && tasks.length > 0) {
        const latestRunning = tasks.find((task: CollectionTask) => task.status === 'running' || task.status === 'pending')
        if (latestRunning) {
          setCurrentTask(latestRunning)
        }
      }
    } catch (e) {
      console.error('Fetch tasks failed:', e)
    }
  }, [currentTask])

  useEffect(() => {
    void fetchRecentTasks()
    const interval = window.setInterval(() => {
      void fetchRecentTasks()
    }, 3000)
    return () => window.clearInterval(interval)
  }, [fetchRecentTasks])

  useEffect(() => {
    fetch(`${API_BASE}/presets`)
      .then((res) => res.json())
      .then((data) => setPresets(data.presets || []))
      .catch(() => setPresets([]))
  }, [])

  const checkStatus = useCallback(async (taskId: string) => {
    try {
      const res = await fetch(`${API_BASE}/status/${taskId}`)
      const data = await res.json()
      if (data.task) {
        setCurrentTask(data.task)
        setRecentTasks(data.recent_tasks || [])
        if (data.task.status === 'running' || data.task.status === 'pending') {
          window.setTimeout(() => {
            void checkStatus(taskId)
          }, 2000)
        }
      }
    } catch (e) {
      console.error('Status check failed:', e)
    }
  }, [])

  const startCollection = async () => {
    if (!keywords.trim()) {
      setMessage('请输入关键词')
      return
    }

    setIsRunning(true)
    setMessage('启动中...')

    try {
      const res = await fetch(`${API_BASE}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keywords: keywords.split(',').map((item) => item.trim()).filter(Boolean),
          country: country || undefined,
          source,
          limit_per_keyword: 30,
        }),
      })

      const data = await res.json()
      if (res.ok && data.task_id) {
        setMessage(`✅ 任务已启动: ${data.task_id}`)
        void checkStatus(data.task_id)
        void fetchRecentTasks()
      } else {
        setMessage(`❌ 启动失败: ${data.detail || data.message || '未知错误'}`)
      }
    } catch (e) {
      setMessage(`❌ 错误: ${String(e)}`)
    } finally {
      setIsRunning(false)
    }
  }

  const applyPreset = (preset: CollectionPreset) => {
    setKeywords(preset.keywords.join(', '))
    setCountry(preset.country || '')
  }

  const progress = currentTask?.total_expected
    ? Math.min(100, (currentTask.collected / Math.max(currentTask.total_expected, 1)) * 100)
    : 0

  return (
    <div
      style={{
        marginBottom: '20px',
        border: '1px solid #e5e7eb',
        borderRadius: '16px',
        background: '#fff',
        padding: '16px',
        boxShadow: '0 8px 24px rgba(15, 23, 42, 0.04)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 700, color: '#111827' }}>🔍 情报采集中心</h3>
        <span style={{ fontSize: '12px', color: '#9ca3af' }}>一键批量采集</span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '14px' }}>
        {presets.map((preset) => (
          <button
            key={preset.label}
            onClick={() => applyPreset(preset)}
            style={{
              fontSize: '12px',
              padding: '6px 10px',
              background: '#f3f4f6',
              color: '#4b5563',
              borderRadius: '999px',
              border: '1px solid #e5e7eb',
              cursor: 'pointer',
            }}
          >
            {preset.label}
          </button>
        ))}
        {presets.length === 0 && (
          <span style={{ fontSize: '12px', color: '#9ca3af' }}>预设关键词加载中...</span>
        )}
      </div>

      <div style={{ marginBottom: '12px' }}>
        <label style={{ display: 'block', fontSize: '12px', color: '#6b7280', marginBottom: '6px' }}>关键词（逗号分隔）</label>
        <textarea
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          placeholder="Philippines church, FaithTech startup..."
          rows={2}
          style={{
            width: '100%',
            resize: 'none',
            boxSizing: 'border-box',
            borderRadius: '12px',
            border: '1px solid #d1d5db',
            padding: '10px 12px',
            fontSize: '14px',
            outline: 'none',
          }}
        />
      </div>

      <div style={{ display: 'flex', gap: '10px', marginBottom: '12px' }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontSize: '12px', color: '#6b7280', marginBottom: '6px' }}>国家（可选）</label>
          <input
            type="text"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            placeholder="Philippines"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              borderRadius: '12px',
              border: '1px solid #d1d5db',
              padding: '10px 12px',
              fontSize: '14px',
              outline: 'none',
            }}
          />
        </div>

        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontSize: '12px', color: '#6b7280', marginBottom: '6px' }}>采集源</label>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              borderRadius: '12px',
              border: '1px solid #d1d5db',
              padding: '10px 12px',
              fontSize: '14px',
              outline: 'none',
              background: '#fff',
            }}
          >
            {COLLECTION_SOURCES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {activeSource && (
        <div
          style={{
            fontSize: '12px',
            color: '#6b7280',
            background: '#f9fafb',
            border: '1px solid #eef2f7',
            borderRadius: '10px',
            padding: '8px 10px',
            marginBottom: '12px',
          }}
        >
          当前采集源：{activeSource.label} | {activeSource.desc}
        </div>
      )}

      <button
        onClick={startCollection}
        disabled={isRunning}
        style={{
          width: '100%',
          padding: '12px 16px',
          borderRadius: '12px',
          border: 'none',
          background: '#111827',
          color: '#fff',
          fontSize: '14px',
          fontWeight: 700,
          cursor: isRunning ? 'not-allowed' : 'pointer',
          opacity: isRunning ? 0.5 : 1,
        }}
      >
        {isRunning ? '⏳ 启动中...' : '🚀 开始采集'}
      </button>

      {message && (
        <div
          style={{
            marginTop: '12px',
            fontSize: '12px',
            color: '#4b5563',
            background: '#f9fafb',
            borderRadius: '10px',
            padding: '10px 12px',
            border: '1px solid #eef2f7',
          }}
        >
          {message}
        </div>
      )}

      {currentTask && (
        <div style={{ marginTop: '14px', display: 'grid', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: '12px', color: '#6b7280' }}>当前任务</div>
            <span
              style={{
                fontSize: '12px',
                padding: '4px 8px',
                borderRadius: '999px',
                background:
                  currentTask.status === 'completed'
                    ? '#dcfce7'
                    : currentTask.status === 'running'
                    ? '#dbeafe'
                    : currentTask.status === 'failed'
                    ? '#fee2e2'
                    : '#f3f4f6',
                color:
                  currentTask.status === 'completed'
                    ? '#166534'
                    : currentTask.status === 'running'
                    ? '#1d4ed8'
                    : currentTask.status === 'failed'
                    ? '#b91c1c'
                    : '#4b5563',
              }}
            >
              {currentTask.status}
            </span>
          </div>

          <div style={{ fontSize: '13px', color: '#111827', fontWeight: 600 }}>
            {currentTask.keywords.join(', ')}
          </div>
          <div style={{ fontSize: '12px', color: '#6b7280' }}>
            {currentTask.task_type} | {currentTask.country || '全球'} | 已采集 {currentTask.collected} | 失败 {currentTask.failed}
            {typeof currentTask.deduped === 'number' ? ` | 去重 ${currentTask.deduped}` : ''}
          </div>

          <div style={{ width: '100%', height: '8px', borderRadius: '999px', background: '#e5e7eb', overflow: 'hidden' }}>
            <div
              style={{
                width: `${progress}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #111827 0%, #4f46e5 100%)',
                transition: 'width 0.3s ease',
              }}
            />
          </div>

          <div style={{ fontSize: '12px', color: '#6b7280' }}>
            进度：{currentTask.collected} / {currentTask.total_expected}
          </div>

          {currentTask.error_message && (
            <div style={{ fontSize: '12px', color: '#b91c1c', background: '#fef2f2', borderRadius: '10px', padding: '8px 10px' }}>
              {currentTask.error_message}
            </div>
          )}
        </div>
      )}

      {recentTasks.length > 0 && (
        <div style={{ marginTop: '16px', borderTop: '1px solid #eef2f7', paddingTop: '12px' }}>
          <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '8px' }}>最近任务</div>
          <div style={{ display: 'grid', gap: '8px', maxHeight: '220px', overflowY: 'auto' }}>
            {recentTasks.map((task) => (
              <button
                key={task.id}
                onClick={() => void checkStatus(task.id)}
                style={{
                  textAlign: 'left',
                  width: '100%',
                  border: '1px solid #eef2f7',
                  borderRadius: '12px',
                  background: '#f9fafb',
                  padding: '10px 12px',
                  cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '13px', color: '#111827', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {task.keywords.join(', ')}
                    </div>
                    <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
                      {task.task_type} | {task.country || '全球'} | 已采集 {task.collected}
                    </div>
                  </div>
                  <span
                    style={{
                      fontSize: '11px',
                      padding: '4px 7px',
                      borderRadius: '999px',
                      background:
                        task.status === 'completed'
                          ? '#dcfce7'
                          : task.status === 'running'
                          ? '#dbeafe'
                          : task.status === 'failed'
                          ? '#fee2e2'
                          : '#f3f4f6',
                      color:
                        task.status === 'completed'
                          ? '#166534'
                          : task.status === 'running'
                          ? '#1d4ed8'
                          : task.status === 'failed'
                          ? '#b91c1c'
                          : '#4b5563',
                    }}
                  >
                    {task.status}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
