import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  createWatchTarget,
  deleteWatchTarget,
  listWatchTargets,
  runWatchTarget,
  updateWatchTarget,
} from '../api/watchAlerts'
import { useAuth } from '../auth/useAuth'
import { getWatchAlertIdentityMode, getWatchAlertInvalidConfigMessage } from '../features/watchAlerts/identity'
import {
  type WatchEntityType,
  type WatchFrequency,
  type WatchTarget,
  WatchAlertApiError,
} from '../types/watchAlerts'

interface WatchButtonProps {
  entityId: string
  entityType: WatchEntityType
}

type WatchButtonViewState =
  | 'loading'
  | 'not_watched'
  | 'active'
  | 'paused'
  | 'disabled'
  | 'creating'
  | 'updating'
  | 'running'
  | 'removing'
  | 'login_required'
  | 'config_invalid'
  | 'error'

const buttonStyle: React.CSSProperties = {
  padding: '8px 14px',
  borderRadius: 8,
  border: '1px solid #cbd5e1',
  background: '#fff',
  color: '#0f172a',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 600,
}

const actionButtonStyle: React.CSSProperties = {
  ...buttonStyle,
  padding: '6px 12px',
  fontSize: 12,
}

const selectStyle: React.CSSProperties = {
  padding: '8px 10px',
  borderRadius: 8,
  border: '1px solid #cbd5e1',
  background: '#fff',
  fontSize: 13,
  color: '#0f172a',
}

function getErrorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return null
  }
  if (error instanceof WatchAlertApiError) {
    return error.userMessage
  }
  return 'Request failed. Please try again.'
}

function isUnauthorizedError(error: unknown): error is WatchAlertApiError {
  return error instanceof WatchAlertApiError && error.status === 401
}

async function findExistingWatchTarget(
  entityId: string,
  entityType: WatchEntityType,
  signal?: AbortSignal,
) {
  let page = 1
  let total = 0
  const pageSize = 100

  do {
    const response = await listWatchTargets(
      { entity_type: entityType, page, page_size: pageSize },
      { signal },
    )
    total = response.total
    const matched = response.items.find((item) => item.entity_id === entityId && item.entity_type === entityType)
    if (matched) {
      return matched
    }
    page += 1
  } while ((page - 1) * pageSize < total)

  return null
}

export function WatchButton({ entityId, entityType }: WatchButtonProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { refreshUser, status, user } = useAuth()
  const identityMode = getWatchAlertIdentityMode()
  const featureEnabled = identityMode !== 'disabled'
  const authenticatedMode = identityMode === 'authenticated-user'
  const [watchTarget, setWatchTarget] = useState<WatchTarget | null>(null)
  const [frequency, setFrequency] = useState<WatchFrequency>('daily')
  const [state, setState] = useState<WatchButtonViewState>('loading')
  const [message, setMessage] = useState<string | null>(null)
  const requestSequenceRef = useRef(0)
  const controllerRef = useRef<AbortController | null>(null)

  const loading = useMemo(
    () => ['loading', 'creating', 'updating', 'running', 'removing'].includes(state),
    [state],
  )

  const cancelInFlightRequest = () => {
    if (!controllerRef.current) {
      return
    }
    controllerRef.current.abort()
    controllerRef.current = null
  }

  const handleUnauthorized = async (error: WatchAlertApiError) => {
    setWatchTarget(null)
    setFrequency('daily')
    setState('login_required')
    setMessage(error.userMessage)
    await refreshUser()
  }

  const redirectToLogin = () => {
    navigate('/login', {
      state: {
        from: `${location.pathname}${location.search}${location.hash}`,
        message: '登录后可继续关注当前机构。',
      },
    })
  }

  const refreshTarget = async () => {
    if (!featureEnabled || !entityId) {
      return
    }

    if (identityMode === 'invalid') {
      cancelInFlightRequest()
      setWatchTarget(null)
      setFrequency('daily')
      setState('config_invalid')
      setMessage(getWatchAlertInvalidConfigMessage())
      return
    }

    if (authenticatedMode && status !== 'authenticated') {
      cancelInFlightRequest()
      setWatchTarget(null)
      setFrequency('daily')
      setState(status === 'loading' ? 'loading' : 'login_required')
      setMessage(status === 'loading' ? null : '登录后可关注该机构。')
      return
    }

    cancelInFlightRequest()
    const requestSequence = requestSequenceRef.current + 1
    requestSequenceRef.current = requestSequence
    const controller = new AbortController()
    controllerRef.current = controller

    setState('loading')
    setMessage(null)

    try {
      const existing = await findExistingWatchTarget(entityId, entityType, controller.signal)
      if (requestSequenceRef.current !== requestSequence) {
        return
      }
      setWatchTarget(existing)
      setFrequency(existing?.frequency ?? 'daily')
      setState(existing?.status ?? 'not_watched')
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (requestSequenceRef.current !== requestSequence) {
        return
      }
      if (authenticatedMode && isUnauthorizedError(error)) {
        await handleUnauthorized(error)
        return
      }
      setWatchTarget(null)
      setState('error')
      setMessage(getErrorMessage(error))
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }

  useEffect(() => {
    void refreshTarget()
    return () => {
      cancelInFlightRequest()
    }
  }, [authenticatedMode, entityId, entityType, featureEnabled, identityMode, status, user?.public_id])

  if (!featureEnabled || !entityId) {
    return null
  }

  if (identityMode === 'invalid') {
    return (
      <section
        aria-label="Watch controls"
        style={{
          border: '1px solid #e2e8f0',
          borderRadius: 16,
          padding: 16,
          background: '#fff',
          display: 'grid',
          gap: 12,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Watch</div>
        <div style={{ fontSize: 12, color: '#b91c1c' }}>{getWatchAlertInvalidConfigMessage()}</div>
        <button type="button" disabled style={{ ...buttonStyle, cursor: 'not-allowed', opacity: 0.7 }}>
          Watch unavailable
        </button>
      </section>
    )
  }

  if (authenticatedMode && status !== 'authenticated') {
    return (
      <section
        aria-label="Watch controls"
        style={{
          border: '1px solid #e2e8f0',
          borderRadius: 16,
          padding: 16,
          background: '#fff',
          display: 'grid',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Watch</div>
          <span
            style={{
              padding: '4px 10px',
              borderRadius: 999,
              background: status === 'loading' ? '#eff6ff' : '#fef3c7',
              color: status === 'loading' ? '#1d4ed8' : '#92400e',
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {status === 'loading' ? 'Checking login' : 'Login required'}
          </span>
        </div>
        <div style={{ fontSize: 12, color: '#475569' }}>
          {status === 'loading' ? '正在恢复登录状态，请稍候。' : '登录后可关注该机构。'}
        </div>
        <button
          type="button"
          onClick={status === 'loading' ? undefined : redirectToLogin}
          disabled={status === 'loading'}
          style={{
            ...buttonStyle,
            cursor: status === 'loading' ? 'not-allowed' : 'pointer',
            opacity: status === 'loading' ? 0.7 : 1,
          }}
        >
          {status === 'loading' ? 'Checking login...' : '登录后关注'}
        </button>
        {message ? (
          <div
            role="status"
            style={{
              borderRadius: 10,
              padding: '10px 12px',
              background: '#f8fafc',
              color: '#334155',
              fontSize: 12,
            }}
          >
            {message}
          </div>
        ) : null}
      </section>
    )
  }

  const handleCreate = async () => {
    cancelInFlightRequest()
    const controller = new AbortController()
    controllerRef.current = controller

    setState('creating')
    setMessage(null)

    try {
      await createWatchTarget(
        {
          entity_id: entityId,
          entity_type: entityType,
          frequency,
        },
        { signal: controller.signal },
      )
      setMessage('Added to watchlist.')
      await refreshTarget()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (authenticatedMode && isUnauthorizedError(error)) {
        await handleUnauthorized(error)
        return
      }
      if (error instanceof WatchAlertApiError && error.status === 409) {
        setMessage(error.userMessage)
        await refreshTarget()
        return
      }
      setState('error')
      setMessage(getErrorMessage(error))
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }

  const handleStatusUpdate = async (nextStatus: WatchTarget['status']) => {
    if (!watchTarget) {
      return
    }

    cancelInFlightRequest()
    const controller = new AbortController()
    controllerRef.current = controller

    setState('updating')
    setMessage(null)

    try {
      await updateWatchTarget(watchTarget.id, { status: nextStatus }, { signal: controller.signal })
      setMessage(nextStatus === 'paused' ? 'Watch paused.' : 'Watch resumed.')
      await refreshTarget()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (authenticatedMode && isUnauthorizedError(error)) {
        await handleUnauthorized(error)
        return
      }
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }

  const handleFrequencyUpdate = async (nextFrequency: WatchFrequency) => {
    if (!watchTarget) {
      return
    }

    cancelInFlightRequest()
    const controller = new AbortController()
    controllerRef.current = controller

    setState('updating')
    setMessage(null)

    try {
      await updateWatchTarget(watchTarget.id, { frequency: nextFrequency }, { signal: controller.signal })
      setMessage('Frequency updated.')
      await refreshTarget()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (authenticatedMode && isUnauthorizedError(error)) {
        await handleUnauthorized(error)
        return
      }
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }

  const handleRunNow = async () => {
    if (!watchTarget) {
      return
    }

    cancelInFlightRequest()
    const controller = new AbortController()
    controllerRef.current = controller

    setState('running')
    setMessage(null)

    try {
      await runWatchTarget(watchTarget.id, { signal: controller.signal })
      setMessage('Watch run triggered.')
      await refreshTarget()
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (authenticatedMode && isUnauthorizedError(error)) {
        await handleUnauthorized(error)
        return
      }
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }

  const handleRemove = async () => {
    if (!watchTarget) {
      return
    }

    cancelInFlightRequest()
    const controller = new AbortController()
    controllerRef.current = controller

    setState('removing')
    setMessage(null)

    try {
      await deleteWatchTarget(watchTarget.id, { signal: controller.signal })
      setWatchTarget(null)
      setFrequency('daily')
      setState('not_watched')
      setMessage('Removed from watchlist.')
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (authenticatedMode && isUnauthorizedError(error)) {
        await handleUnauthorized(error)
        return
      }
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
    }
  }

  const statusLabelMap: Record<WatchButtonViewState, string> = {
    loading: 'Loading...',
    not_watched: 'Watch',
    active: 'Watching',
    paused: 'Paused',
    disabled: 'Disabled',
    creating: 'Creating...',
    updating: 'Updating...',
    running: 'Running...',
    removing: 'Removing...',
    login_required: 'Login required',
    config_invalid: 'Unavailable',
    error: 'Load failed',
  }

  return (
    <section
      aria-label="Watch controls"
      style={{
        border: '1px solid #e2e8f0',
        borderRadius: 16,
        padding: 16,
        background: '#fff',
        display: 'grid',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>Watch</div>
        <span
          style={{
            padding: '4px 10px',
            borderRadius: 999,
            background:
              state === 'active'
                ? '#dcfce7'
                : state === 'paused'
                  ? '#fef3c7'
                  : state === 'disabled'
                    ? '#e2e8f0'
                    : state === 'login_required'
                      ? '#fef3c7'
                      : '#eff6ff',
            color:
              state === 'active'
                ? '#166534'
                : state === 'paused'
                  ? '#92400e'
                  : state === 'disabled'
                    ? '#475569'
                    : state === 'login_required'
                      ? '#92400e'
                      : '#1d4ed8',
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          {statusLabelMap[state]}
        </span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
        <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
          <span>Frequency</span>
          <select
            aria-label="Watch frequency"
            value={frequency}
            onChange={(event) => {
              const nextFrequency = event.target.value as WatchFrequency
              setFrequency(nextFrequency)
              if (watchTarget) {
                void handleFrequencyUpdate(nextFrequency)
              }
            }}
            disabled={loading || watchTarget?.status === 'disabled'}
            style={selectStyle}
          >
            <option value="daily">daily</option>
            <option value="weekly">weekly</option>
            <option value="manual">manual</option>
          </select>
        </label>

        {!watchTarget ? (
          <button type="button" onClick={() => void handleCreate()} disabled={loading} style={buttonStyle}>
            Watch
          </button>
        ) : null}

        {watchTarget?.status === 'active' ? (
          <button
            type="button"
            aria-label="Pause watch target"
            onClick={() => void handleStatusUpdate('paused')}
            disabled={loading}
            style={actionButtonStyle}
          >
            Pause
          </button>
        ) : null}

        {watchTarget?.status === 'paused' ? (
          <button
            type="button"
            aria-label="Resume watch target"
            onClick={() => void handleStatusUpdate('active')}
            disabled={loading}
            style={actionButtonStyle}
          >
            Resume
          </button>
        ) : null}

        {watchTarget ? (
          <button
            type="button"
            aria-label="Run watch target now"
            onClick={() => void handleRunNow()}
            disabled={loading || watchTarget.status === 'disabled'}
            style={actionButtonStyle}
          >
            Run Now
          </button>
        ) : null}

        {watchTarget ? (
          <button
            type="button"
            aria-label="Remove watch target"
            onClick={() => void handleRemove()}
            disabled={loading}
            style={{
              ...actionButtonStyle,
              borderColor: '#fecaca',
              color: '#b91c1c',
            }}
          >
            Remove
          </button>
        ) : null}
      </div>

      {message ? (
        <div
          role="status"
          style={{
            borderRadius: 10,
            padding: '10px 12px',
            background: state === 'error' ? '#fef2f2' : '#f8fafc',
            color: state === 'error' ? '#b91c1c' : '#334155',
            fontSize: 12,
          }}
        >
          {message}
        </div>
      ) : null}
    </section>
  )
}
