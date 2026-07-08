import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getUnreadAlertCount,
  hasWatchAlertSession,
  WATCH_ALERT_UNREAD_REFRESH_EVENT,
} from '../api/watchAlerts'
import { useAuth } from '../auth/useAuth'
import { getWatchAlertIdentityMode } from '../features/watchAlerts/identity'
import { WatchAlertApiError } from '../types/watchAlerts'

const POLL_INTERVAL_MS = 60_000
const SERVICE_UNAVAILABLE_RETRY_MS = 120_000

function BellIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M15 17h5l-1.4-1.4A2 2 0 0 1 18 14.2V11a6 6 0 1 0-12 0v3.2a2 2 0 0 1-.6 1.4L4 17h5" />
      <path d="M10 21a2 2 0 0 0 4 0" />
    </svg>
  )
}

function getUnreadErrorMessage(error: unknown) {
  if (error instanceof WatchAlertApiError) {
    if (error.status === 401) {
      return '登录状态已失效，请重新登录'
    }
    if (error.status === 429) {
      return '请求过于频繁，请稍后重试'
    }
    if (error.status === 503) {
      return 'Watch / Alert 功能当前未启用'
    }
    return error.userMessage
  }

  return '操作失败，请稍后重试'
}

export function NotificationBell() {
  const navigate = useNavigate()
  const { refreshUser, status, user } = useAuth()
  const identityMode = getWatchAlertIdentityMode()
  const enabled = identityMode !== 'disabled' && identityMode !== 'invalid'
  const authenticatedMode = identityMode === 'authenticated-user'
  const canPoll =
    enabled &&
    (authenticatedMode ? status === 'authenticated' : hasWatchAlertSession())
  const [unreadCount, setUnreadCount] = useState(0)
  const [inlineMessage, setInlineMessage] = useState<string | null>(null)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [authExpired, setAuthExpired] = useState(false)
  const timerRef = useRef<number | null>(null)
  const inFlightRef = useRef(false)
  const mountedRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const scheduleNextPoll = (delayMs = POLL_INTERVAL_MS) => {
    clearTimer()
    if (!canPoll || authExpired || document.visibilityState === 'hidden') {
      return
    }
    timerRef.current = window.setTimeout(() => {
      void refreshUnreadCount()
    }, delayMs)
  }

  const refreshUnreadCount = async () => {
    if (!canPoll || authExpired || inFlightRef.current) {
      return
    }

    if (!authenticatedMode && !hasWatchAlertSession()) {
      if (mountedRef.current) {
        setUnreadCount(0)
        setInlineMessage('登录状态已失效，请重新登录')
        setHasLoaded(true)
        setAuthExpired(true)
      }
      return
    }

    inFlightRef.current = true
    clearTimer()
    const controller = new AbortController()
    controllerRef.current = controller

    try {
      const nextCount = await getUnreadAlertCount({ signal: controller.signal })
      if (!mountedRef.current) {
        return
      }

      setUnreadCount(nextCount)
      setInlineMessage(null)
      setHasLoaded(true)
      scheduleNextPoll(POLL_INTERVAL_MS)
    } catch (error) {
      if (!mountedRef.current) {
        return
      }

      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (typeof error === 'object' && error && 'name' in error && (error as any).name === 'AbortError') {
        return
      }

      const message = getUnreadErrorMessage(error)
      setHasLoaded(true)
      setInlineMessage(message)

      if (error instanceof WatchAlertApiError && error.status === 401) {
        setUnreadCount(0)
        setAuthExpired(true)
        if (authenticatedMode) {
          await refreshUser()
        }
        return
      }

      if (error instanceof WatchAlertApiError && (error.status === 429 || error.status === 503)) {
        scheduleNextPoll(SERVICE_UNAVAILABLE_RETRY_MS)
        return
      }

      scheduleNextPoll(POLL_INTERVAL_MS)
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
      inFlightRef.current = false
    }
  }

  useEffect(() => {
    mountedRef.current = true

    if (!enabled) {
      setUnreadCount(0)
      setInlineMessage(null)
      setHasLoaded(false)
      setAuthExpired(false)
      return
    }

    if (authenticatedMode && status !== 'authenticated') {
      clearTimer()
      controllerRef.current?.abort()
      setUnreadCount(0)
      setInlineMessage(null)
      setHasLoaded(status !== 'loading')
      setAuthExpired(status === 'unauthenticated')
      return () => {
        mountedRef.current = false
        clearTimer()
        controllerRef.current?.abort()
      }
    }

    if (!authenticatedMode && !hasWatchAlertSession()) {
      setUnreadCount(0)
      setInlineMessage('登录状态已失效，请重新登录')
      setHasLoaded(true)
      setAuthExpired(true)
      return () => {
        mountedRef.current = false
        clearTimer()
        controllerRef.current?.abort()
      }
    }

    setAuthExpired(false)
    void refreshUnreadCount()

    const handleUnreadRefresh = () => {
      void refreshUnreadCount()
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        clearTimer()
        return
      }
      void refreshUnreadCount()
    }

    const handleFocus = () => {
      if (document.visibilityState !== 'hidden') {
        void refreshUnreadCount()
      }
    }

    window.addEventListener(WATCH_ALERT_UNREAD_REFRESH_EVENT, handleUnreadRefresh)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', handleFocus)

    return () => {
      mountedRef.current = false
      clearTimer()
      controllerRef.current?.abort()
      window.removeEventListener(WATCH_ALERT_UNREAD_REFRESH_EVENT, handleUnreadRefresh)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleFocus)
    }
  }, [authenticatedMode, canPoll, enabled, status, user?.public_id])

  const showBadge = unreadCount > 0
  const badgeText = unreadCount > 99 ? '99+' : String(unreadCount)
  const ariaLabel = authExpired
    ? '通知铃铛，登录状态已失效'
    : inlineMessage && !showBadge
      ? `通知铃铛，${inlineMessage}`
      : showBadge
        ? `通知铃铛，当前 ${unreadCount} 条未读通知`
        : '通知铃铛，当前无未读通知'

  if (!enabled) {
    return null
  }

  if (authenticatedMode && status !== 'authenticated') {
    return null
  }

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <button
        type="button"
        aria-label={ariaLabel}
        onClick={() => navigate('/alerts')}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '10px 12px',
          borderRadius: 10,
          border: '1px solid #d0d0d0',
          background: '#f8fafc',
          color: '#0f172a',
          cursor: 'pointer',
        }}
      >
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 14, fontWeight: 600 }}>
          <BellIcon />
          <span>Alerts</span>
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          {showBadge ? (
            <span
              aria-hidden="true"
              style={{
                minWidth: 28,
                padding: '2px 8px',
                borderRadius: 999,
                background: '#dc2626',
                color: '#fff',
                fontSize: 12,
                fontWeight: 700,
                textAlign: 'center',
              }}
            >
              {badgeText}
            </span>
          ) : null}
          <span style={{ fontSize: 12, color: '#64748b' }}>{hasLoaded ? 'Open' : 'Loading...'}</span>
        </span>
      </button>

      {showBadge ? (
        <span style={{ fontSize: 11, color: '#475569' }}>
          <span className="sr-only">未读通知数量：</span>
          {unreadCount > 99 ? '未读通知 99+ 条' : `未读通知 ${unreadCount} 条`}
        </span>
      ) : null}

      {inlineMessage ? (
        <div style={{ fontSize: 11, color: inlineMessage.includes('未启用') ? '#92400e' : '#b91c1c' }}>
          {inlineMessage}
        </div>
      ) : null}
    </div>
  )
}

export default NotificationBell
