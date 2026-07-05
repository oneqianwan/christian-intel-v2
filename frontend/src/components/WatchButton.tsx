import { useEffect, useMemo, useState } from 'react'
import {
  createWatchTarget,
  deleteWatchTarget,
  isWatchAlertUiEnabled,
  listWatchTargets,
  runWatchTarget,
  updateWatchTarget,
} from '../api/watchAlerts'
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
  if (error instanceof WatchAlertApiError) {
    return error.userMessage
  }
  return 'Request failed. Please try again.'
}

async function findExistingWatchTarget(entityId: string, entityType: WatchEntityType) {
  let page = 1
  let total = 0
  const pageSize = 100

  do {
    const response = await listWatchTargets({ entity_type: entityType, page, page_size: pageSize })
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
  const featureEnabled = isWatchAlertUiEnabled()
  const [watchTarget, setWatchTarget] = useState<WatchTarget | null>(null)
  const [frequency, setFrequency] = useState<WatchFrequency>('daily')
  const [state, setState] = useState<WatchButtonViewState>('loading')
  const [message, setMessage] = useState<string | null>(null)

  const loading = useMemo(
    () => ['loading', 'creating', 'updating', 'running', 'removing'].includes(state),
    [state],
  )

  const refreshTarget = async () => {
    if (!featureEnabled || !entityId) {
      return
    }

    setState('loading')
    setMessage(null)

    try {
      const existing = await findExistingWatchTarget(entityId, entityType)
      setWatchTarget(existing)
      setFrequency(existing?.frequency ?? 'daily')
      setState(existing?.status ?? 'not_watched')
    } catch (error) {
      setWatchTarget(null)
      setState('error')
      setMessage(getErrorMessage(error))
    }
  }

  useEffect(() => {
    void refreshTarget()
    // Current callers pass stable literal entityType values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, featureEnabled])

  if (!featureEnabled || !entityId) {
    return null
  }

  const handleCreate = async () => {
    setState('creating')
    setMessage(null)

    try {
      await createWatchTarget({
        entity_id: entityId,
        entity_type: entityType,
        frequency,
      })
      setMessage('Added to watchlist.')
      await refreshTarget()
    } catch (error) {
      setState('error')
      setMessage(getErrorMessage(error))
    }
  }

  const handleStatusUpdate = async (status: WatchTarget['status']) => {
    if (!watchTarget) return

    setState('updating')
    setMessage(null)

    try {
      await updateWatchTarget(watchTarget.id, { status })
      setMessage(status === 'paused' ? 'Watch paused.' : 'Watch resumed.')
      await refreshTarget()
    } catch (error) {
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    }
  }

  const handleFrequencyUpdate = async (nextFrequency: WatchFrequency) => {
    if (!watchTarget) return

    setState('updating')
    setMessage(null)

    try {
      await updateWatchTarget(watchTarget.id, { frequency: nextFrequency })
      setMessage('Frequency updated.')
      await refreshTarget()
    } catch (error) {
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    }
  }

  const handleRunNow = async () => {
    if (!watchTarget) return

    setState('running')
    setMessage(null)

    try {
      await runWatchTarget(watchTarget.id)
      setMessage('Watch run triggered.')
      await refreshTarget()
    } catch (error) {
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
    }
  }

  const handleRemove = async () => {
    if (!watchTarget) return

    setState('removing')
    setMessage(null)

    try {
      await deleteWatchTarget(watchTarget.id)
      setWatchTarget(null)
      setFrequency('daily')
      setState('not_watched')
      setMessage('Removed from watchlist.')
    } catch (error) {
      setState(watchTarget.status)
      setMessage(getErrorMessage(error))
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
                    : '#eff6ff',
            color:
              state === 'active'
                ? '#166534'
                : state === 'paused'
                  ? '#92400e'
                  : state === 'disabled'
                    ? '#475569'
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
