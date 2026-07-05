import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import {
  dismissAlert,
  dispatchWatchAlertUnreadRefresh,
  isWatchAlertUiEnabled,
  listAlerts,
  listWatchTargets,
  markAlertRead,
  markAllAlertsRead,
} from '../api/watchAlerts'
import {
  type AlertStatus,
  type WatchAlert,
  type WatchSeverity,
  type WatchTarget,
  WatchAlertApiError,
} from '../types/watchAlerts'

const pageSizeOptions = [10, 20, 50]

function getAlertErrorMessage(error: unknown) {
  if (error instanceof WatchAlertApiError) {
    if (error.status === 401) {
      return '登录状态已失效，请重新登录'
    }
    if (error.status === 404) {
      return '通知不存在'
    }
    if (error.status === 409) {
      return '通知状态已发生变化，请刷新'
    }
    if (error.status === 422) {
      return '请求参数无效'
    }
    if (error.status === 503) {
      return 'Watch / Alert 功能当前未启用'
    }
    return error.userMessage
  }

  return '操作失败，请稍后重试'
}

function isSafeHttpUrl(value: string | null) {
  return Boolean(value && /^https?:\/\//i.test(value))
}

function formatDateTime(value: string | null) {
  if (!value) {
    return '—'
  }

  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString()
}

function SeverityBadge({ severity }: { severity: WatchSeverity }) {
  const colorMap: Record<WatchSeverity, { background: string; color: string }> = {
    low: { background: '#ecfeff', color: '#155e75' },
    medium: { background: '#fef3c7', color: '#92400e' },
    high: { background: '#fee2e2', color: '#b91c1c' },
    critical: { background: '#ede9fe', color: '#6d28d9' },
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

function StatusBadge({ status }: { status: AlertStatus }) {
  const colorMap: Record<AlertStatus, { background: string; color: string; label: string }> = {
    unread: { background: '#dbeafe', color: '#1d4ed8', label: 'Unread' },
    read: { background: '#dcfce7', color: '#166534', label: 'Read' },
    dismissed: { background: '#e2e8f0', color: '#475569', label: 'Dismissed' },
  }

  return (
    <span
      style={{
        padding: '4px 8px',
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        ...colorMap[status],
      }}
    >
      {colorMap[status].label}
    </span>
  )
}

async function loadAllWatchTargets() {
  const items: WatchTarget[] = []
  let page = 1
  const pageSize = 100
  let total = 0

  do {
    const response = await listWatchTargets({
      page,
      page_size: pageSize,
    })
    items.push(...response.items)
    total = response.total
    page += 1
  } while ((page - 1) * pageSize < total)

  return items
}

export function AlertsPage() {
  const navigate = useNavigate()
  const featureEnabled = isWatchAlertUiEnabled()
  const [items, setItems] = useState<WatchAlert[]>([])
  const [watchTargets, setWatchTargets] = useState<WatchTarget[]>([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<'' | AlertStatus>('')
  const [severityFilter, setSeverityFilter] = useState<'' | WatchSeverity>('')
  const [watchTargetFilter, setWatchTargetFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [actionState, setActionState] = useState<{ id: string; action: 'read' | 'dismiss' } | null>(null)
  const [readAllLoading, setReadAllLoading] = useState(false)
  const [expandedSummaryId, setExpandedSummaryId] = useState<string | null>(null)

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / pageSize)), [pageSize, total])
  const hasUnreadAlerts = useMemo(() => items.some((item) => item.status === 'unread'), [items])
  const watchTargetLabelMap = useMemo(
    () =>
      Object.fromEntries(
        watchTargets.map((target) => [
          target.id,
          `${target.entity_type}: ${target.entity_id}`,
        ]),
      ),
    [watchTargets],
  )

  const loadAlertPage = async (nextPage = page, preserveData = false) => {
    setLoading(true)
    setErrorMessage(null)

    try {
      const response = await listAlerts({
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
        watch_target_id: watchTargetFilter || undefined,
        page: nextPage,
        page_size: pageSize,
      })

      if (response.total > 0 && response.items.length === 0 && nextPage > 1) {
        setPage(nextPage - 1)
        return
      }

      setItems(response.items)
      setTotal(response.total)
    } catch (error) {
      if (!preserveData) {
        setItems([])
        setTotal(0)
      }
      setErrorMessage(getAlertErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!featureEnabled) {
      return
    }

    void loadAlertPage(page)
    // Filters and paging intentionally drive loading from here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureEnabled, page, pageSize, statusFilter, severityFilter, watchTargetFilter])

  useEffect(() => {
    if (!featureEnabled) {
      return
    }

    const loadFilterTargets = async () => {
      try {
        setWatchTargets(await loadAllWatchTargets())
      } catch {
        setWatchTargets([])
      }
    }

    void loadFilterTargets()
  }, [featureEnabled])

  if (!featureEnabled) {
    return <Navigate to="/dashboard" replace />
  }

  const executeRowAction = async (
    alertId: string,
    action: 'read' | 'dismiss',
    callback: () => Promise<WatchAlert>,
  ) => {
    setActionState({ id: alertId, action })
    setActionMessage(null)
    setErrorMessage(null)

    try {
      await callback()
      await loadAlertPage(page, true)
      dispatchWatchAlertUnreadRefresh()
      setActionMessage(action === 'read' ? '通知已标记为已读' : '通知已忽略')
    } catch (error) {
      setErrorMessage(getAlertErrorMessage(error))
    } finally {
      setActionState(null)
    }
  }

  const handleMarkAllRead = async () => {
    setReadAllLoading(true)
    setActionMessage(null)
    setErrorMessage(null)

    try {
      const updatedCount = await markAllAlertsRead()
      await loadAlertPage(page, true)
      dispatchWatchAlertUnreadRefresh()
      setActionMessage(`已全部标记已读，本次更新 ${updatedCount} 条`)
    } catch (error) {
      setErrorMessage(getAlertErrorMessage(error))
    } finally {
      setReadAllLoading(false)
    }
  }

  return (
    <div
      style={{
        maxWidth: 1280,
        margin: '0 auto',
        padding: '24px 20px 48px',
        background: '#f8fafc',
        minHeight: '100vh',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: 12,
          flexWrap: 'wrap',
          marginBottom: 20,
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: 28, color: '#0f172a' }}>Alerts</h1>
          <div style={{ fontSize: 13, color: '#64748b', marginTop: 6 }}>
            Review unread, read, and dismissed notifications from your watch targets.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              background: '#fff',
              cursor: 'pointer',
            }}
          >
            Back to Dashboard
          </button>
          <button
            type="button"
            onClick={() => navigate('/watchlist')}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              background: '#fff',
              cursor: 'pointer',
            }}
          >
            Watchlist
          </button>
          <button
            type="button"
            onClick={() => navigate('/')}
            style={{
              padding: '8px 14px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              background: '#fff',
              cursor: 'pointer',
            }}
          >
            Back to Chat
          </button>
        </div>
      </div>

      <div
        style={{
          border: '1px solid #e2e8f0',
          borderRadius: 16,
          padding: 16,
          background: '#fff',
          display: 'grid',
          gap: 14,
          marginBottom: 20,
        }}
      >
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'end' }}>
          <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
            <span>Status</span>
            <select
              aria-label="Filter alerts by status"
              value={statusFilter}
              onChange={(event) => {
                setPage(1)
                setStatusFilter(event.target.value as '' | AlertStatus)
              }}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
            >
              <option value="">All statuses</option>
              <option value="unread">Unread</option>
              <option value="read">Read</option>
              <option value="dismissed">Dismissed</option>
            </select>
          </label>

          <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
            <span>Severity</span>
            <select
              aria-label="Filter alerts by severity"
              value={severityFilter}
              onChange={(event) => {
                setPage(1)
                setSeverityFilter(event.target.value as '' | WatchSeverity)
              }}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
            >
              <option value="">All severities</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </label>

          {watchTargets.length > 0 ? (
            <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
              <span>Watch target</span>
              <select
                aria-label="Filter alerts by watch target"
                value={watchTargetFilter}
                onChange={(event) => {
                  setPage(1)
                  setWatchTargetFilter(event.target.value)
                }}
                style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
              >
                <option value="">All watch targets</option>
                {watchTargets.map((target) => (
                  <option key={target.id} value={target.id}>
                    {target.entity_type}: {target.entity_id}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
            <span>Page size</span>
            <select
              aria-label="Select alerts page size"
              value={pageSize}
              onChange={(event) => {
                setPage(1)
                setPageSize(Number(event.target.value))
              }}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
            >
              {pageSizeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => void loadAlertPage(page, true)}
            disabled={loading}
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              background: '#fff',
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            Refresh
          </button>

          <button
            type="button"
            onClick={() => void handleMarkAllRead()}
            disabled={!hasUnreadAlerts || readAllLoading}
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid #cbd5e1',
              background: !hasUnreadAlerts || readAllLoading ? '#f8fafc' : '#fff',
              cursor: !hasUnreadAlerts || readAllLoading ? 'not-allowed' : 'pointer',
              fontWeight: 600,
            }}
          >
            {readAllLoading ? 'Marking...' : 'Mark All Read'}
          </button>
        </div>
      </div>

      {actionMessage ? (
        <div
          role="status"
          style={{
            marginBottom: 16,
            borderRadius: 10,
            padding: '10px 12px',
            background: '#eff6ff',
            color: '#1d4ed8',
            fontSize: 13,
          }}
        >
          {actionMessage}
        </div>
      ) : null}

      {errorMessage ? (
        <div
          style={{
            marginBottom: 16,
            borderRadius: 10,
            padding: '10px 12px',
            background: '#fef2f2',
            color: '#b91c1c',
            fontSize: 13,
          }}
        >
          <div>{errorMessage}</div>
          <button
            type="button"
            onClick={() => void loadAlertPage(page, true)}
            style={{
              marginTop: 10,
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid #fecaca',
              background: '#fff',
              color: '#b91c1c',
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      ) : null}

      {loading && items.length === 0 ? (
        <div style={{ color: '#64748b', fontSize: 14, marginBottom: 16 }}>Loading alerts...</div>
      ) : null}

      {!loading && !errorMessage && items.length === 0 ? (
        <div
          style={{
            border: '1px solid #e2e8f0',
            borderRadius: 16,
            padding: 24,
            background: '#fff',
            display: 'grid',
            gap: 12,
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>暂无通知</div>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            当前筛选条件下没有可显示的通知。
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Link
              to="/watchlist"
              style={{
                padding: '8px 14px',
                borderRadius: 8,
                border: '1px solid #cbd5e1',
                background: '#fff',
                color: '#0f172a',
                textDecoration: 'none',
              }}
            >
              前往 Watchlist
            </Link>
          </div>
        </div>
      ) : null}

      {items.length > 0 ? (
        <div style={{ display: 'grid', gap: 16 }}>
          {items.map((item) => {
            const busy = actionState?.id === item.id
            const showFullSummary = expandedSummaryId === item.id
            const summary = item.summary || '—'
            const shouldTruncate = summary.length > 180

            return (
              <article
                key={item.id}
                style={{
                  border: '1px solid #e2e8f0',
                  borderRadius: 16,
                  padding: 16,
                  background: '#fff',
                  display: 'grid',
                  gap: 12,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 12,
                    flexWrap: 'wrap',
                    alignItems: 'center',
                  }}
                >
                  <div style={{ display: 'grid', gap: 6 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>{item.title}</div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                      <StatusBadge status={item.status} />
                      <SeverityBadge severity={item.severity} />
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: '#64748b' }}>
                    Created: {formatDateTime(item.created_at)}
                  </div>
                </div>

                <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.6 }}>
                  {shouldTruncate && !showFullSummary ? `${summary.slice(0, 180)}...` : summary}
                  {shouldTruncate ? (
                    <button
                      type="button"
                      onClick={() => setExpandedSummaryId(showFullSummary ? null : item.id)}
                      style={{
                        marginLeft: 8,
                        border: 'none',
                        background: 'transparent',
                        color: '#2563eb',
                        cursor: 'pointer',
                        padding: 0,
                      }}
                    >
                      {showFullSummary ? 'Collapse' : 'Expand'}
                    </button>
                  ) : null}
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: 12,
                    fontSize: 13,
                    color: '#334155',
                  }}
                >
                  <div>
                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Watch target</div>
                    <div>{watchTargetLabelMap[item.watch_target_id] || item.watch_target_id}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Signal ID</div>
                    <div>{item.signal_id || '—'}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Read at</div>
                    <div>{formatDateTime(item.read_at)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Dismissed at</div>
                    <div>{formatDateTime(item.dismissed_at)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>Source URL</div>
                    {isSafeHttpUrl(item.source_url) ? (
                      <a href={item.source_url ?? undefined} target="_blank" rel="noopener noreferrer">
                        Open source
                      </a>
                    ) : (
                      <span>—</span>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {item.status === 'unread' ? (
                    <button
                      type="button"
                      aria-label={`Mark alert ${item.id} as read`}
                      disabled={busy || readAllLoading}
                      onClick={() =>
                        void executeRowAction(item.id, 'read', async () => markAlertRead(item.id))
                      }
                      style={{
                        padding: '8px 12px',
                        borderRadius: 8,
                        border: '1px solid #cbd5e1',
                        background: '#fff',
                        cursor: busy || readAllLoading ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {busy && actionState?.action === 'read' ? 'Marking...' : 'Mark Read'}
                    </button>
                  ) : null}

                  {item.status !== 'dismissed' ? (
                    <button
                      type="button"
                      aria-label={`Dismiss alert ${item.id}`}
                      disabled={busy || readAllLoading}
                      onClick={() =>
                        void executeRowAction(item.id, 'dismiss', async () => dismissAlert(item.id))
                      }
                      style={{
                        padding: '8px 12px',
                        borderRadius: 8,
                        border: '1px solid #fecaca',
                        background: '#fff',
                        color: '#b91c1c',
                        cursor: busy || readAllLoading ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {busy && actionState?.action === 'dismiss' ? 'Dismissing...' : 'Ignore'}
                    </button>
                  ) : (
                    <span style={{ fontSize: 12, color: '#64748b', alignSelf: 'center' }}>Already dismissed</span>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      ) : null}

      {!loading && items.length > 0 && totalPages > 1 ? (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 20 }}>
          <button
            type="button"
            aria-label="Previous alerts page"
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
            aria-label="Next alerts page"
            disabled={page >= totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  )
}
