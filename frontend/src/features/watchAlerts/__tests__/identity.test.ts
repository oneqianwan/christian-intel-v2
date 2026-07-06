import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getWatchAlertIdentityMode,
  isAuthenticatedOwnershipEnabled,
  isWatchAlertUiEnabled,
} from '../identity'

describe('watch alert identity mode', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('defaults to disabled when the watch alert UI flag is false', () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'false')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    expect(isWatchAlertUiEnabled()).toBe(false)
    expect(getWatchAlertIdentityMode()).toBe('disabled')
  })

  it('uses legacy-session when ownership is disabled', () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'false')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    expect(isAuthenticatedOwnershipEnabled()).toBe(false)
    expect(getWatchAlertIdentityMode()).toBe('legacy-session')
  })

  it('uses authenticated-user when ownership and auth flags are enabled', () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'true')

    expect(isAuthenticatedOwnershipEnabled()).toBe(true)
    expect(getWatchAlertIdentityMode()).toBe('authenticated-user')
  })

  it('fails safe as invalid when ownership is enabled but auth is disabled', () => {
    vi.stubEnv('VITE_WATCH_ALERT_UI_ENABLED', 'true')
    vi.stubEnv('VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED', 'true')
    vi.stubEnv('VITE_AUTH_V1_ENABLED', 'false')

    expect(getWatchAlertIdentityMode()).toBe('invalid')
  })
})
