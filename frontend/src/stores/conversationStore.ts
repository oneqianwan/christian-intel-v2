import { create } from 'zustand'

export interface Conversation {
  id: string
  title: string
  is_pinned?: boolean
  pinned_at?: string | null
  created_at: string
  updated_at: string
}

interface ConversationStore {
  conversations: Conversation[]
  currentId: string | null
  setConversations: (list: Conversation[]) => void
  setCurrentId: (id: string | null) => void
  addConversation: (conv: Conversation) => void
}

export const useConversationStore = create<ConversationStore>((set) => ({
  conversations: [],
  currentId: null,
  setConversations: (list) => set({ conversations: list }),
  setCurrentId: (id) => set({ currentId: id }),
  addConversation: (conv) => set((s) => ({
    conversations: [conv, ...s.conversations],
    currentId: conv.id,
  })),
}))
