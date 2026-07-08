import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchConversations, sendChatStream, ChatApiError } from '../../services/api'

function mockTextResponse(body: unknown, status = 200) {
  const text = typeof body === 'string' ? body : JSON.stringify(body)
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'ERROR',
    text: vi.fn().mockResolvedValue(text),
    body: status >= 200 && status < 300 ? null : null,
  } as unknown as Response
}

function mockStreamResponse(lines: string[], status = 200) {
  const encoder = new TextEncoder()
  const chunks = lines.map((line) => encoder.encode(line))
  let idx = 0
  const reader = {
    read: vi.fn().mockImplementation(async () => {
      if (idx >= chunks.length) return { done: true, value: undefined }
      const value = chunks[idx]
      idx += 1
      return { done: false, value }
    }),
  }

  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'ERROR',
    text: vi.fn().mockResolvedValue(''),
    body: {
      getReader: () => reader,
    },
  } as unknown as Response
}

describe('chat api client auth behavior', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8001/api')
    vi.restoreAllMocks()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('does not use credentials include in legacy mode', async () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    fetchMock.mockResolvedValue(mockTextResponse([]))
    await fetchConversations()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.credentials).toBeUndefined()
  })

  it('uses credentials include in authenticated-user mode', async () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')

    fetchMock.mockResolvedValue(mockTextResponse([]))
    await fetchConversations()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.credentials).toBe('include')
  })

  it('fails safe without calling fetch in invalid mode', async () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    fetchMock.mockResolvedValue(mockTextResponse([]))
    await expect(fetchConversations()).rejects.toMatchObject({
      status: 503,
      code: 'CHAT_IDENTITY_INVALID',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('stream uses credentials include and does not send x-session-id headers in authenticated-user mode', async () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')

    fetchMock.mockResolvedValue(
      mockStreamResponse(['data: {"type":"done","conversation_id":"c1","message_id":"m1","full_content":"ok"}\n\n']),
    )

    const onEvent = vi.fn()
    await sendChatStream('hello', 'c1', onEvent)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [, init] = fetchMock.mock.calls[0]
    expect(init?.credentials).toBe('include')
    const headers = new Headers(init?.headers)
    expect(headers.get('x-session-id')).toBeNull()
    expect(headers.get('X-Session-Id')).toBeNull()
  })

  it('stream 401 rejects before reading body', async () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')

    const response = mockTextResponse({ detail: { error_code: 'AUTH_REQUIRED', message: 'Authentication required' } }, 401)
    fetchMock.mockResolvedValue(response)

    const onEvent = vi.fn()
    await expect(sendChatStream('hello', 'c1', onEvent)).rejects.toBeInstanceOf(ChatApiError)
    expect(onEvent).not.toHaveBeenCalled()
  })
})

