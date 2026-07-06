import { useEffect, useRef, useState } from 'react'
import { listWatchTargetSignals } from '../api/watchAlerts'
import { useAuth } from '../auth/useAuth'
import { getWatchAlertIdentityMode, getWatchAlertInvalidConfigMessage } from '../features/watchAlerts/identity'
import {
  type WatchSeverity,
  type WatchSignal,
  type WatchSignalListParams,
  type WatchSignalType,
  WatchAlertApiError,
} from '../types/watchAlerts'

interface SignalListProps {
  watchTargetId: string
}

const signalTypeOptions: Array<{ value: '' | WatchSignalType; label: string }> = [
  { value: '', label: 'All types' },
  { value: 'new_intelligence', label: 'new_intelligence' },
  { value: 'website_change', label: 'website_change' },
  { value: 'new_news', label: 'new_news' },
  { value: 'new_video', label: 'new_video' },
  { value: 'leadership_change', label: 'leadership_change' },
  { value: 'contact_change', label: 'contact_change' },
  { value: 'score_change', label: 'score_change' },
  { value: 'relation_change', label: 'relation_change' },
]

const severityOptions: Array<{ value: '' | WatchSeverity; label: string }> = [
  { value: '', label: 'All severities' },
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
  { value: 'critical', label: 'critical' },
]

function getErrorMessage(error: unknown) {
  if (error instanceof WatchAlertApiError) {
    return error.userMessage
  }
  return 'Request failed. Please try again.'
}

function isSafeHttpUrl(value: string | null) {
  return Boolean(value && /^https?:\/\//i.test(value))
}

function formatJsonValue(value: WatchSignal['old_value_json']) {
  if (value === null) {
    return '--'
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }

  const serialized = JSON.stringify(value, null, 2)
  if (serialized.length <= 400) {
    return serialized
  }
  return `${serialized.slice(0, 400)}\n...`
}

function SeverityBadge({ severity }: { severity: WatchSeverity }) {
  const colorMap: Record<WatchSeverity, { bg: string; color: string }> = {
    low: { bg: '#ecfeff', color: '#155e75' },
    medium: { bg: '#fef3c7', color: '#92400e' },
    high: { bg: '#fee2e2', color: '#b91c1c' },
    critical: { bg: '#ede9fe', color: '#6d28d9' },
  }

  return (
    <span
      style={{
        padding: '4px 8px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        ...colorMap[severity],
      }}
    >
      {severity}
    </span>
  )
}

export function SignalList({ watchTargetId }: SignalListProps) {
  const { refreshUser, status, user } = useAuth()
  const identityMode = getWatchAlertIdentityMode()
  const authenticatedMode = identityMode === 'authenticated-user'
  const [items, setItems] = useState<WatchSignal[]>([])
  const [page, setPage] = useState(1)
  const [pageSize] = useState(5)
  const [total, setTotal] = useState(0)
  const [signalType, setSignalType] = useState<'' | WatchSignalType>('')
  const [severity, setSeverity] = useState<'' | WatchSeverity>('')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const requestSequenceRef = useRef(0)
  const controllerRef = useRef<AbortController | null>(null)

  const clearData = () => {
    setItems([])
    setTotal(0)
    setErrorMessage(null)
  }

  const loadSignals = async (params?: Partial<WatchSignalListParams>) => {
    if (!watchTargetId) {
      clearData()
      return
    }

    if (identityMode === 'invalid') {
      clearData()
      setErrorMessage(getWatchAlertInvalidConfigMessage())
      return
    }

    if (authenticatedMode && status !== 'authenticated') {
      clearData()
      return
    }

    controllerRef.current?.abort()
    const requestSequence = requestSequenceRef.current + 1
    requestSequenceRef.current = requestSequence
    const controller = new AbortController()
    controllerRef.current = controller

    setLoading(true)
    setErrorMessage(null)

    try {
      const response = await listWatchTargetSignals(
        watchTargetId,
        {
          signal_type: (params?.signal_type ?? signalType) || undefined,
          severity: (params?.severity ?? severity) || undefined,
          page: params?.page ?? page,
          page_size: pageSize,
        },
        { signal: controller.signal },
      )
      if (requestSequenceRef.current !== requestSequence) {
        return
      }
      setItems(response.items)
      setTotal(response.total)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return
      }
      if (requestSequenceRef.current !== requestSequence) {
        return
      }
      if (authenticatedMode && error instanceof WatchAlertApiError && error.status === 401) {
        clearData()
        await refreshUser()
        return
      }
      setErrorMessage(getErrorMessage(error))
      setItems([])
      setTotal(0)
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null
      }
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSignals()
    return () => {
      controllerRef.current?.abort()
    }
  }, [authenticatedMode, identityMode, page, refreshUser, severity, signalType, status, user?.public_id, watchTargetId])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <section
      aria-label="Watch signals"
      style={{
        borderTop: '1px solid #e2e8f0',
        paddingTop: 16,
        display: 'grid',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'end' }}>
        <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
          <span>Signal type</span>
          <select
            aria-label="Filter signals by type"
            value={signalType}
            onChange={(event) => {
              setPage(1)
              setSignalType(event.target.value as '' | WatchSignalType)
            }}
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
          >
            {signalTypeOptions.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
          <span>Severity</span>
          <select
            aria-label="Filter signals by severity"
            value={severity}
            onChange={(event) => {
              setPage(1)
              setSeverity(event.target.value as '' | WatchSeverity)
            }}
            style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
          >
            {severityOptions.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={() => void loadSignals({ page: 1 })}
          style={{
            padding: '8px 12px',
            borderRadius: 8,
            border: '1px solid #cbd5e1',
            background: '#fff',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>

      {loading ? <div style={{ color: '#64748b', fontSize: 13 }}>Loading signals...</div> : null}
      {errorMessage ? <div style={{ color: '#b91c1c', fontSize: 13 }}>{errorMessage}</div> : null}
      {!loading && !errorMessage && items.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 13 }}>No signals yet.</div>
      ) : null}

      {!loading && !errorMessage && items.length > 0 ? (
        <div style={{ display: 'grid', gap: 12 }}>
          {items.map((item) => (
            <article
              key={item.id}
              style={{
                border: '1px solid #e2e8f0',
                borderRadius: 12,
                padding: 14,
                background: '#fff',
                display: 'grid',
                gap: 10,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 10,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a' }}>{item.title}</div>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                    {item.signal_type} | {new Date(item.detected_at).toLocaleString()}
                  </div>
                </div>
                <SeverityBadge severity={item.severity} />
              </div>

              <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.6 }}>{item.summary || '--'}</div>

              <div style={{ display: 'grid', gap: 10 }}>
                <div>
                  <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Old value</div>
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      background: '#f8fafc',
                      borderRadius: 10,
                      padding: 10,
                      fontSize: 12,
                      color: '#0f172a',
                    }}
                  >
                    {formatJsonValue(item.old_value_json)}
                  </pre>
                </div>

                <div>
                  <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>New value</div>
                  <pre
                    style={{
                      margin: 0,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      background: '#f8fafc',
                      borderRadius: 10,
                      padding: 10,
                      fontSize: 12,
                      color: '#0f172a',
                    }}
                  >
                    {formatJsonValue(item.new_value_json)}
                  </pre>
                </div>
              </div>

              <div style={{ fontSize: 12, color: '#475569' }}>
                Source:
                {isSafeHttpUrl(item.source_url) ? (
                  <a
                    href={item.source_url ?? undefined}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: '#2563eb', marginLeft: 6 }}
                  >
                    Open source
                  </a>
                ) : (
                  <span style={{ marginLeft: 6 }}>--</span>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {!loading && !errorMessage && totalPages > 1 ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            aria-label="Previous signals page"
            disabled={page <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
          >
            Previous
          </button>
          <span style={{ fontSize: 12, color: '#475569' }}>
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            aria-label="Next signals page"
            disabled={page >= totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
          >
            Next
          </button>
        </div>
      ) : null}
    </section>
  )
}
