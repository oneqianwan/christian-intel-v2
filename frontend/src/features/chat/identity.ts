import { isAuthUiEnabled } from '../../auth/flags'

export type ChatIdentityMode =
  | 'legacy'
  | 'authenticated-user'
  | 'invalid'

export function isChatUserOwnershipEnabled() {
  return import.meta.env.VITE_CHAT_USER_OWNERSHIP_ENABLED === 'true'
}

export function getChatIdentityMode(): ChatIdentityMode {
  if (!isChatUserOwnershipEnabled()) {
    return 'legacy'
  }

  if (isAuthUiEnabled()) {
    return 'authenticated-user'
  }

  return 'invalid'
}

export function isChatAuthMode() {
  return getChatIdentityMode() === 'authenticated-user'
}

export function isChatInvalidConfig() {
  return getChatIdentityMode() === 'invalid'
}

export function getChatInvalidConfigMessage() {
  return 'Chat 正式身份模式不可用，请先启用 Auth 功能。'
}

