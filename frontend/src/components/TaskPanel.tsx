import { useEffect, useState } from 'react'

type TaskItem = {
  id: number
  title: string
  description?: string
  priority: string
  status: string
  created_at: string
}

interface TaskPanelProps {
  refreshToken?: number
}

const API_BASE = 'http://localhost:8000/api'

export function TaskPanel({ refreshToken = 0 }: TaskPanelProps) {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [loading, setLoading] = useState(false)

  const fetchTasks = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/tasks?limit=20`)
      const data = await res.json()
      setTasks(data.tasks || [])
    } catch (e) {
      console.error('Fetch tasks failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchTasks()
  }, [refreshToken])

  const updateStatus = async (id: number, status: string) => {
    try {
      await fetch(`${API_BASE}/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      await fetchTasks()
    } catch (e) {
      console.error('Update task failed:', e)
    }
  }

  const deleteTask = async (id: number) => {
    if (!window.confirm('确认删除？')) return
    try {
      await fetch(`${API_BASE}/tasks/${id}`, { method: 'DELETE' })
      await fetchTasks()
    } catch (e) {
      console.error('Delete task failed:', e)
    }
  }

  const getPriorityColor = (priority: string) => {
    switch (priority) {
      case 'urgent':
        return { background: '#fee2e2', color: '#b91c1c' }
      case 'high':
        return { background: '#ffedd5', color: '#c2410c' }
      case 'medium':
        return { background: '#dbeafe', color: '#1d4ed8' }
      default:
        return { background: '#f3f4f6', color: '#4b5563' }
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return { background: '#dcfce7', color: '#15803d' }
      case 'in_progress':
        return { background: '#fef3c7', color: '#a16207' }
      case 'pending':
        return { background: '#f3f4f6', color: '#4b5563' }
      default:
        return { background: '#f3f4f6', color: '#4b5563' }
    }
  }

  const translateStatus = (status: string) => {
    if (status === 'pending') return '待跟进'
    if (status === 'in_progress') return '进行中'
    if (status === 'completed') return '已完成'
    return status
  }

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: '14px', background: '#fff', marginBottom: '16px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 14px',
          borderBottom: '1px solid #f1f5f9',
        }}
      >
        <div style={{ fontSize: '14px', fontWeight: 700, color: '#111827' }}>跟踪任务</div>
        <button
          onClick={() => void fetchTasks()}
          style={{ border: 'none', background: 'transparent', color: '#6b7280', fontSize: '12px', cursor: 'pointer' }}
        >
          {loading ? '刷新中...' : '刷新'}
        </button>
      </div>

      {tasks.length === 0 ? (
        <div style={{ padding: '16px', textAlign: 'center', color: '#9ca3af', fontSize: '12px' }}>暂无任务</div>
      ) : (
        <div style={{ maxHeight: '240px', overflowY: 'auto' }}>
          {tasks.map((task) => (
            <div key={task.id} style={{ padding: '12px 14px', borderTop: '1px solid #f8fafc' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                <div style={{ flex: 1, fontSize: '14px', color: '#111827', lineHeight: 1.5 }}>{task.title}</div>
                <span
                  style={{
                    ...getPriorityColor(task.priority),
                    padding: '3px 8px',
                    borderRadius: '999px',
                    fontSize: '11px',
                    fontWeight: 700,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {task.priority}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
                <span
                  style={{
                    ...getStatusColor(task.status),
                    padding: '3px 8px',
                    borderRadius: '999px',
                    fontSize: '11px',
                    fontWeight: 700,
                  }}
                >
                  {translateStatus(task.status)}
                </span>
                <span style={{ fontSize: '11px', color: '#9ca3af' }}>
                  {task.created_at ? new Date(task.created_at).toLocaleDateString() : ''}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '10px', flexWrap: 'wrap' }}>
                {task.status !== 'completed' && (
                  <button
                    onClick={() => void updateStatus(task.id, 'completed')}
                    style={{ border: 'none', borderRadius: '8px', padding: '4px 8px', fontSize: '12px', background: '#f0fdf4', color: '#16a34a', cursor: 'pointer' }}
                  >
                    ✓ 完成
                  </button>
                )}
                {task.status === 'pending' && (
                  <button
                    onClick={() => void updateStatus(task.id, 'in_progress')}
                    style={{ border: 'none', borderRadius: '8px', padding: '4px 8px', fontSize: '12px', background: '#fefce8', color: '#ca8a04', cursor: 'pointer' }}
                  >
                    ▶ 开始
                  </button>
                )}
                <button
                  onClick={() => void deleteTask(task.id)}
                  style={{ border: 'none', borderRadius: '8px', padding: '4px 8px', fontSize: '12px', background: '#fef2f2', color: '#dc2626', cursor: 'pointer' }}
                >
                  ✕ 删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
