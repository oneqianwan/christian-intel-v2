const API_BASE = 'http://localhost:8000/api'
const WELCOME_REPLY_TEXT = '你好！我是 CIO 情报助手。请问你想查询哪家机构的评分或投资关系？'
const normalizeWelcomeText = (value: string) => value.replace(/\s+/g, '')

export async function fetchConversations() {
  const r = await fetch(`${API_BASE}/conversations`)
  return r.json()
}

export async function createConversation(title?: string) {
  const body = JSON.stringify({ title: title || '新会话' })
  const r = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: body,
  })
  return r.json()
}

export async function fetchMessages(conversationId: string) {
  const r = await fetch(`${API_BASE}/conversations/${conversationId}/messages`)
  return r.json()
}

export async function sendChatStream(
  message: string,
  conversationId: string | null,
  onEvent: (type: string, data: any) => void,
  signal?: AbortSignal
) {
  const r = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  })
  if (!r.ok) throw new Error(`http ${r.status}`)
  if (!r.body) throw new Error('no body')
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim()
      if (!line) continue

      if (line.startsWith('event:')) {
        const eventType = line.slice(6).trim()
        const dataLine = lines[++i]
        if (dataLine?.startsWith('data:')) {
          try {
            onEvent(eventType, JSON.parse(dataLine.slice(5)))
          } catch {}
        }
      } else if (line.startsWith('data:')) {
        const data = line.slice(5).trim()
        if (!data || data === '[DONE]') continue
        try {
          const parsed = JSON.parse(data)
          const fullContent = parsed?.full_content || parsed?.delivery?.content || ''
          const welcomeReplyUuid = parsed?.welcome_reply_uuid || parsed?.delivery?.welcome_reply_uuid || null
          if (normalizeWelcomeText(fullContent) === normalizeWelcomeText(WELCOME_REPLY_TEXT) && welcomeReplyUuid) {
            console.log(`SSE_UUID=${welcomeReplyUuid}`)
          }
          const type = parsed?.type || 'message'
          onEvent(type, parsed)
        } catch {}
      }
    }
  }
}
