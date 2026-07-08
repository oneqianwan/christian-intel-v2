import { useConversationStore } from '../../stores/conversationStore'
import { useMessageStore } from '../../stores/messageStore'

type AbortHandler = () => void

const abortHandlers = new Set<AbortHandler>()

export function registerChatAbortHandler(handler: AbortHandler) {
  abortHandlers.add(handler)
  return () => {
    abortHandlers.delete(handler)
  }
}

export function abortChatRequests() {
  for (const handler of Array.from(abortHandlers)) {
    try {
      handler()
    } catch {}
  }
}

export function resetChatStores() {
  useConversationStore.getState().reset()
  useMessageStore.getState().reset()
}

export function clearChatState() {
  abortChatRequests()
  resetChatStores()
}

