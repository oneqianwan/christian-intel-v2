import { useEffect, useState } from 'react'

type MissionView = {
  id: string
  query: string
  country: string
  status: string
  priority: number
  target_entity: string | null
  created_at: string | null
  updated_at: string | null
}

type TaskItem = {
  id: number
  title: string
  description?: string
  mission_id: string | null
  mission: MissionView | null
  priority?: string
  status?: string
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

  const isMissionTask = (task: TaskItem) => Boolean(task.mission_id && task.mission)

  const getTaskStatus = (task: TaskItem) => {
    if (isMissionTask(task)) return task.mission?.status || ''
    return task.status || 'pending'
  }

  const getTaskPriority = (task: TaskItem) => {
    if (!isMissionTask(task)) return task.priority || 'medium'

    const missionPriority = task.mission?.priority
    if (typeof missionPriority !== 'number') return ''
    return `P${missionPriority}`
  }

  const getPriorityColor = (priority: string) => {
    if (/^P\d+$/i.test(priority)) {
      const level = Number(priority.slice(1))
      if (level <= 2) return { background: '#fee2e2', color: '#b91c1c' }
      if (level <= 5) return { background: '#ffedd5', color: '#c2410c' }
      return { background: '#f3f4f6', color: '#4b5563' }
    }
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
      case 'running':
        return { background: '#e0f2fe', color: '#0369a1' }
      case 'completed':
      case 'done':
        return { background: '#dcfce7', color: '#15803d' }
      case 'in_progress':
        return { background: '#fef3c7', color: '#a16207' }
      case 'pending':
      case 'queued':
        return { background: '#f3f4f6', color: '#4b5563' }
      case 'failed':
      case 'cancelled':
        return { background: '#fef2f2', color: '#dc2626' }
      default:
        return { background: '#f3f4f6', color: '#4b5563' }
    }
  }

  const translateStatus = (status: string) => {
    if (status === 'pending') return '待跟进'
    if (status === 'in_progress') return '进行中'
    if (status === 'completed') return '已完成'
    if (status === 'queued') return '排队中'
    if (status === 'running') return '运行中'
    if (status === 'done') return '已完成'
    if (status === 'failed') return '失败'
    if (status === 'cancelled') return '已取消'
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
              {(() => {
                const status = getTaskStatus(task)
                const priority = getTaskPriority(task)
                const missionTask = isMissionTask(task)

                return (
                  <>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                <div style={{ flex: 1, fontSize: '14px', color: '#111827', lineHeight: 1.5 }}>{task.title}</div>
                {priority && (
                  <span
                    style={{
                      ...getPriorityColor(priority),
                      padding: '3px 8px',
                      borderRadius: '999px',
                      fontSize: '11px',
                      fontWeight: 700,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {priority}
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
                <span
                  style={{
                    ...getStatusColor(status),
                    padding: '3px 8px',
                    borderRadius: '999px',
                    fontSize: '11px',
                    fontWeight: 700,
                  }}
                >
                  {translateStatus(status)}
                </span>
                {missionTask && task.mission?.id && (
                  <span style={{ fontSize: '11px', color: '#64748b' }}>
                    Mission: {task.mission.id.slice(0, 8)}
                  </span>
                )}
                <span style={{ fontSize: '11px', color: '#9ca3af' }}>
                  {task.created_at ? new Date(task.created_at).toLocaleDateString() : ''}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '10px', flexWrap: 'wrap' }}>
                {!missionTask && status !== 'completed' && (
                  <button
                    onClick={() => void updateStatus(task.id, 'completed')}
                    style={{ border: 'none', borderRadius: '8px', padding: '4px 8px', fontSize: '12px', background: '#f0fdf4', color: '#16a34a', cursor: 'pointer' }}
                  >
                    ✓ 完成
                  </button>
                )}
                {!missionTask && status === 'pending' && (
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
                  </>
                )
              })()}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
