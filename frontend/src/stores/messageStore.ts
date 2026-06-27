import { create } from 'zustand'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: { name: string; url: string }[]
  delivery_type: string
  status: string
  scope?: string
  localOnly?: boolean
}

interface MessageStore {
  messages: Record<string, Message[]>
  addMessage: (convId: string, msg: Message) => void
  getMessages: (convId: string) => Message[]
}

export const useMessageStore = create<MessageStore>((set, get) => ({
  messages: {},
  addMessage: (convId, msg) => set((s) => {
    const current = s.messages[convId] || []
    const existingIndex = current.findIndex((item) => item.id === msg.id)
    const nextMessages = [...current]

    if (existingIndex >= 0) {
      const existing = current[existingIndex]
      const unchanged =
        existing.role === msg.role &&
        existing.content === msg.content &&
        existing.delivery_type === msg.delivery_type &&
        existing.status === msg.status &&
        existing.scope === msg.scope &&
        existing.localOnly === msg.localOnly &&
        JSON.stringify(existing.sources) === JSON.stringify(msg.sources)

      if (unchanged) {
        return s
      }

      nextMessages[existingIndex] = { ...existing, ...msg }
    } else {
      const optimisticIndex = current.findIndex((item) =>
        item.localOnly &&
        item.role === msg.role &&
        item.content === msg.content &&
        item.delivery_type === msg.delivery_type
      )

      if (optimisticIndex >= 0 && !msg.localOnly) {
        nextMessages[optimisticIndex] = { ...current[optimisticIndex], ...msg, localOnly: false }
      } else {
        const duplicateIndex = current.findIndex((item) =>
          !item.localOnly &&
          item.role === msg.role &&
          item.content === msg.content &&
          item.delivery_type === msg.delivery_type &&
          item.status === msg.status
        )

        if (duplicateIndex >= 0) {
          return s
        }

      nextMessages.push(msg)
      }
    }

    return {
      messages: {
        ...s.messages,
        [convId]: nextMessages,
      },
    }
  }),
  getMessages: (convId) => get().messages[convId] || [],
}))
