import { isAuthUiEnabled } from '../../auth/flags'

export type WatchAlertIdentityMode =
  | 'disabled'
  | 'legacy-session'
  | 'authenticated-user'
  | 'invalid'

export function isWatchAlertUiEnabled() {
  return import.meta.env.VITE_WATCH_ALERT_UI_ENABLED === 'true'
}

export function isAuthenticatedOwnershipEnabled() {
  return import.meta.env.VITE_WATCH_ALERT_USER_OWNERSHIP_ENABLED === 'true'
}

export function getWatchAlertIdentityMode(): WatchAlertIdentityMode {
  if (!isWatchAlertUiEnabled()) {
    return 'disabled'
  }

  if (!isAuthenticatedOwnershipEnabled()) {
    return 'legacy-session'
  }

  if (isAuthUiEnabled()) {
    return 'authenticated-user'
  }

  return 'invalid'
}

export function isAuthenticatedUserMode() {
  return getWatchAlertIdentityMode() === 'authenticated-user'
}

export function isLegacySessionMode() {
  return getWatchAlertIdentityMode() === 'legacy-session'
}

export function getWatchAlertInvalidConfigMessage() {
  return 'Watch / Alert 正式身份模式不可用，请先启用 Auth 功能。'
}
