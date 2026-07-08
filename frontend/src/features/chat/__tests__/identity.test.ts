import { afterEach, describe, expect, it, vi } from 'vitest'
import { getChatIdentityMode, isChatUserOwnershipEnabled } from '../identity'

describe('chat identity mode', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('defaults to legacy when ownership is disabled', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')
    expect(isChatUserOwnershipEnabled()).toBe(false)
    expect(getChatIdentityMode()).toBe('legacy')
  })

  it('uses authenticated-user when ownership and auth flags are enabled', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')
    expect(isChatUserOwnershipEnabled()).toBe(true)
    expect(getChatIdentityMode()).toBe('authenticated-user')
  })

  it('fails safe as invalid when ownership is enabled but auth is disabled', () => {
    vi.stubEnv('VITE_CHAT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')
    expect(getChatIdentityMode()).toBe('invalid')
  })
})

