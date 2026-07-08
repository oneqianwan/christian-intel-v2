import { getChatIdentityMode } from '../features/chat/identity'
import type { Conversation } from '../stores/conversationStore'

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/api'
const WELCOME_REPLY_TEXT = '你好！我是 CIO 情报助手。请问你想查询哪家机构的评分或投资关系？'
const normalizeWelcomeText = (value: string) => value.replace(/\s+/g, '')

export function getApiBaseUrl() {
  return ((import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || DEFAULT_API_BASE_URL).replace(/\/+$/, '')
}

export function buildApiUrl(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${getApiBaseUrl()}${normalizedPath}`
}

export class ChatApiError extends Error {
  status: number
  code: string
  isNetworkError: boolean

  constructor(payload: { status: number; code: string; message: string; isNetworkError?: boolean }) {
    super(payload.message)
    this.name = 'ChatApiError'
    this.status = payload.status
    this.code = payload.code
    this.isNetworkError = Boolean(payload.isNetworkError)
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

async function parseJsonSafely(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) {
    return null
  }
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

async function parseChatError(response: Response): Promise<ChatApiError> {
  const payload = await parseJsonSafely(response)
  const detail =
    payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail?: unknown }).detail
      : undefined
  const detailObject = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail : undefined
  const payloadObject = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : undefined

  return new ChatApiError({
    status: response.status,
    code:
      (detailObject as { error_code?: string } | undefined)?.error_code ||
      (payloadObject as { error_code?: string } | undefined)?.error_code ||
      `HTTP_${response.status}`,
    message:
      (detailObject as { message?: string } | undefined)?.message ||
      (payloadObject as { message?: string } | undefined)?.message ||
      response.statusText ||
      'Request failed',
  })
}

async function requestJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const identityMode = getChatIdentityMode()
  if (identityMode === 'invalid') {
    throw new ChatApiError({
      status: 503,
      code: 'CHAT_IDENTITY_INVALID',
      message: 'Chat 正式身份模式不可用，请先启用 Auth 功能。',
    })
  }

  const requestInit: RequestInit = {
    method: options.method || 'GET',
    signal: options.signal,
  }

  if (identityMode === 'authenticated-user') {
    requestInit.credentials = 'include'
  }

  if (options.body !== undefined) {
    requestInit.headers = { 'Content-Type': 'application/json; charset=utf-8' }
    requestInit.body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(buildApiUrl(path), requestInit)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ChatApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Network request failed',
      isNetworkError: true,
    })
  }

  if (!response.ok) {
    throw await parseChatError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const payload = await parseJsonSafely(response)
  return (payload ?? undefined) as T
}

export async function fetchConversations() {
  return requestJson<Conversation[]>('/conversations')
}

export async function createConversation(title?: string) {
  return requestJson<Conversation>('/conversations', {
    method: 'POST',
    body: { title: title || '新会话' },
  })
}

export async function fetchMessages(conversationId: string) {
  return requestJson<any[]>(`/conversations/${conversationId}/messages`)
}

export async function fetchConversation(conversationId: string) {
  return requestJson<Conversation>(`/conversations/${conversationId}`)
}

export async function updateConversationTitle(conversationId: string, title: string) {
  return requestJson<Conversation>(`/conversations/${conversationId}`, {
    method: 'PUT',
    body: { title },
  })
}

export async function updateConversationPinned(conversationId: string, pinned: boolean) {
  return requestJson<Conversation>(`/conversations/${conversationId}/pin`, {
    method: 'PUT',
    body: { pinned },
  })
}

export async function deleteConversation(conversationId: string) {
  return requestJson<void>(`/conversations/${conversationId}`, {
    method: 'DELETE',
  })
}

export async function sendChatSimple(message: string, conversationId: string | null) {
  return requestJson<any>('/chat/simple', {
    method: 'POST',
    body: { message, conversation_id: conversationId },
  })
}

export async function sendChatStream(
  message: string,
  conversationId: string | null,
  onEvent: (type: string, data: any) => void,
  signal?: AbortSignal
) {
  const identityMode = getChatIdentityMode()
  if (identityMode === 'invalid') {
    throw new ChatApiError({
      status: 503,
      code: 'CHAT_IDENTITY_INVALID',
      message: 'Chat 正式身份模式不可用，请先启用 Auth 功能。',
    })
  }

  const requestInit: RequestInit = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  }

  if (identityMode === 'authenticated-user') {
    requestInit.credentials = 'include'
  }

  let r: Response
  try {
    r = await fetch(buildApiUrl('/chat/stream'), requestInit)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ChatApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message: 'Network request failed',
      isNetworkError: true,
    })
  }

  if (!r.ok) {
    throw await parseChatError(r)
  }
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
