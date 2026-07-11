import { create } from 'zustand'
import type { ContactPayload } from '../types/contactIntelligence'
import type { PartnershipRecommendationPayload } from '../types/partnershipRecommendation'
import type { RelationshipGraphPayload } from '../types/relationshipGraph'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: { name: string; url: string }[]
  delivery_type: string
  status: string
  scope?: string
  localOnly?: boolean
  welcome_reply_uuid?: string
  relationship_graph?: RelationshipGraphPayload
  contact_lookup?: ContactPayload
  partnership_recommendations?: PartnershipRecommendationPayload
}

interface MessageStore {
  messages: Record<string, Message[]>
  addMessage: (convId: string, msg: Message) => void
  getMessages: (convId: string) => Message[]
  reset: () => void
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
        existing.welcome_reply_uuid === msg.welcome_reply_uuid &&
        JSON.stringify(existing.sources) === JSON.stringify(msg.sources) &&
        JSON.stringify(existing.relationship_graph) === JSON.stringify(msg.relationship_graph) &&
        JSON.stringify(existing.contact_lookup) === JSON.stringify(msg.contact_lookup) &&
        JSON.stringify(existing.partnership_recommendations) === JSON.stringify(msg.partnership_recommendations)

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
  reset: () => set({ messages: {} }),
}))
