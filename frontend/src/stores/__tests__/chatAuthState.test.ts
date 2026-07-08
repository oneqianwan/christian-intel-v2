import { describe, expect, it, vi } from 'vitest'
import { clearChatState, registerChatAbortHandler } from '../../features/chat/cleanup'
import { useConversationStore } from '../conversationStore'
import { useMessageStore } from '../messageStore'

describe('chat state cleanup', () => {
  it('clears chat stores and abort handlers', () => {
    useConversationStore.getState().setConversations([
      {
        id: 'c1',
        title: 'T',
        created_at: 'now',
        updated_at: 'now',
      },
    ])
    useConversationStore.getState().setCurrentId('c1')
    useMessageStore.getState().addMessage('c1', {
      id: 'm1',
      role: 'user',
      content: 'hi',
      sources: [],
      delivery_type: 'text',
      status: 'completed',
    })

    const abortMock = vi.fn()
    const unregister = registerChatAbortHandler(abortMock)

    clearChatState()

    expect(abortMock).toHaveBeenCalledTimes(1)
    expect(useConversationStore.getState().conversations).toEqual([])
    expect(useConversationStore.getState().currentId).toBeNull()
    expect(useMessageStore.getState().messages).toEqual({})

    unregister()
  })
})

