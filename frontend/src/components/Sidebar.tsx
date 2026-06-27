import { useEffect, useState } from 'react'
import { useConversationStore } from '../stores/conversationStore'
import { fetchConversations, createConversation } from '../services/api'
import type { Conversation } from '../stores/conversationStore'

const API_BASE = 'http://localhost:8000/api'

function Sidebar() {
  const { conversations, currentId, setConversations, setCurrentId, addConversation } = useConversationStore()
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [hoverId, setHoverId] = useState<string | null>(null)

  const loadConversations = async () => {
    const list = await fetchConversations()
    setConversations(list)
  }

  useEffect(() => {
    loadConversations()
  }, [])

  useEffect(() => {
    const handleOutsideClick = () => setMenuOpen(null)
    window.addEventListener('click', handleOutsideClick)
    return () => window.removeEventListener('click', handleOutsideClick)
  }, [])

  const handleNewChat = async () => {
    const conv = await createConversation()
    addConversation(conv)
  }

  const handleEdit = (conv: Conversation) => {
    setEditingId(conv.id)
    setEditTitle(conv.title || '新会话')
    setMenuOpen(null)
  }

  const submitEdit = async (convId: string) => {
    const title = editTitle.trim()
    if (!title) return

    try {
      await fetch(`${API_BASE}/conversations/${convId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      setEditingId(null)
      setEditTitle('')
      await loadConversations()
    } catch (e) {
      console.error('编辑失败:', e)
    }
  }

  const handlePin = async (conv: Conversation) => {
    try {
      await fetch(`${API_BASE}/conversations/${conv.id}/pin`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: !conv.is_pinned }),
      })
      setMenuOpen(null)
      await loadConversations()
    } catch (e) {
      console.error('置顶失败:', e)
    }
  }

  const handleDelete = async (conv: Conversation) => {
    const confirmed = window.confirm(
      `确定删除会话「${conv.title}」？\n聊天记录将被删除，但已采集的情报数据保留。`
    )
    if (!confirmed) {
      setMenuOpen(null)
      return
    }

    try {
      await fetch(`${API_BASE}/conversations/${conv.id}`, { method: 'DELETE' })
      setMenuOpen(null)
      if (currentId === conv.id) {
        setCurrentId(null)
      }
      await loadConversations()
    } catch (e) {
      console.error('删除失败:', e)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '16px', borderBottom: '1px solid #e0e0e0' }}>
        <button
          onClick={handleNewChat}
          style={{
            width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid #d0d0d0',
            background: '#fff', cursor: 'pointer', fontSize: '14px',
          }}
        >
          + 新会话
        </button>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: '8px' }}>
        {conversations.map((c) => (
          <div
            key={`conv-${c.id}-${c.created_at}`}
            onClick={() => {
              if (editingId !== c.id) setCurrentId(c.id)
            }}
            onMouseEnter={() => setHoverId(c.id)}
            onMouseLeave={() => setHoverId((prev) => (prev === c.id ? null : prev))}
            style={{
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '12px',
              paddingRight: '36px',
              borderRadius: '8px',
              marginBottom: '4px',
              cursor: 'pointer',
              fontSize: '14px', background: c.id === currentId ? '#eef2ff' : 'transparent',
              fontWeight: c.id === currentId ? 600 : 400, color: c.id === currentId ? '#4f46e5' : '#333',
            }}
          >
            <span style={{ width: '16px', textAlign: 'center', flexShrink: 0, opacity: c.is_pinned ? 1 : 0.35 }}>
              {c.is_pinned ? '📌' : '💬'}
            </span>

            {editingId === c.id ? (
              <div
                onClick={(e) => e.stopPropagation()}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1, minWidth: 0 }}
              >
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') submitEdit(c.id)
                    if (e.key === 'Escape') {
                      setEditingId(null)
                      setEditTitle('')
                    }
                  }}
                  autoFocus
                  style={{
                    flex: 1,
                    minWidth: 0,
                    fontSize: '13px',
                    padding: '6px 8px',
                    border: '1px solid #a5b4fc',
                    borderRadius: '6px',
                    outline: 'none',
                  }}
                />
                <button
                  onClick={() => submitEdit(c.id)}
                  style={{
                    border: 'none',
                    background: '#dcfce7',
                    color: '#166534',
                    borderRadius: '6px',
                    padding: '4px 6px',
                    cursor: 'pointer',
                  }}
                >
                  ✓
                </button>
                <button
                  onClick={() => {
                    setEditingId(null)
                    setEditTitle('')
                  }}
                  style={{
                    border: 'none',
                    background: '#fee2e2',
                    color: '#991b1b',
                    borderRadius: '6px',
                    padding: '4px 6px',
                    cursor: 'pointer',
                  }}
                >
                  ✕
                </button>
              </div>
            ) : (
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.title || '新会话'}
              </span>
            )}

            {editingId !== c.id && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setMenuOpen(menuOpen === c.id ? null : c.id)
                }}
                style={{
                  position: 'absolute',
                  right: '8px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  opacity: hoverId === c.id || menuOpen === c.id ? 1 : 0,
                  border: 'none',
                  background: menuOpen === c.id ? '#e5e7eb' : 'transparent',
                  borderRadius: '6px',
                  padding: '4px 6px',
                  cursor: 'pointer',
                  color: '#6b7280',
                  transition: 'opacity 0.15s ease',
                }}
              >
                ⋯
              </button>
            )}

            {menuOpen === c.id && editingId !== c.id && (
              <div
                onClick={(e) => e.stopPropagation()}
                style={{
                  position: 'absolute',
                  top: '40px',
                  right: '8px',
                  width: '132px',
                  background: '#fff',
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  boxShadow: '0 10px 25px rgba(0, 0, 0, 0.12)',
                  zIndex: 50,
                  padding: '6px 0',
                }}
              >
                <button
                  onClick={() => handleEdit(c)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    border: 'none',
                    background: 'transparent',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    color: '#374151',
                  }}
                >
                  编辑标题
                </button>
                <button
                  onClick={() => handlePin(c)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    border: 'none',
                    background: 'transparent',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    color: '#374151',
                  }}
                >
                  {c.is_pinned ? '取消置顶' : '置顶'}
                </button>
                <div style={{ height: '1px', background: '#f3f4f6', margin: '4px 0' }} />
                <button
                  onClick={() => handleDelete(c)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    border: 'none',
                    background: 'transparent',
                    padding: '8px 12px',
                    cursor: 'pointer',
                    color: '#dc2626',
                  }}
                >
                  删除
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default Sidebar
