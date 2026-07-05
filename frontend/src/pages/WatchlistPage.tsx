import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import {
  deleteWatchTarget,
  isWatchAlertUiEnabled,
  listWatchTargets,
  runWatchTarget,
  updateWatchTarget,
} from '../api/watchAlerts'
import { SignalList } from '../components/SignalList'
import {
  type WatchEntityType,
  type WatchFrequency,
  type WatchTarget,
  type WatchTargetStatus,
  WatchAlertApiError,
} from '../types/watchAlerts'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000'

function getErrorMessage(error: unknown) {
  if (error instanceof WatchAlertApiError) {
    return error.userMessage
  }
  return 'Request failed. Please try again.'
}

async function fetchOrganizationName(entityId: string) {
  const response = await fetch(`${API_BASE}/api/dashboard/org/${encodeURIComponent(entityId)}`)
  if (!response.ok) {
    return entityId
  }

  const payload = (await response.json()) as { name?: string }
  return payload.name || entityId
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : '--'
}

export function WatchlistPage() {
  const navigate = useNavigate()
  const featureEnabled = isWatchAlertUiEnabled()
  const [items, setItems] = useState<WatchTarget[]>([])
  const [entityNames, setEntityNames] = useState<Record<string, string>>({})
  const [page, setPage] = useState(1)
  const [pageSize] = useState(10)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<'' | WatchTargetStatus>('')
  const [entityTypeFilter, setEntityTypeFilter] = useState<'' | WatchEntityType>('')
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [actionState, setActionState] = useState<{ id: string; action: string } | null>(null)
  const [expandedSignalsFor, setExpandedSignalsFor] = useState<string | null>(null)

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / pageSize)), [pageSize, total])

  const loadWatchTargets = async (nextPage = page) => {
    setLoading(true)
    setErrorMessage(null)

    try {
      const response = await listWatchTargets({
        status: statusFilter || undefined,
        entity_type: entityTypeFilter || undefined,
        page: nextPage,
        page_size: pageSize,
      })

      setItems(response.items)
      setTotal(response.total)

      const organizationItems = response.items.filter((item) => item.entity_type === 'organization')
      const uniqueIds = [...new Set(organizationItems.map((item) => item.entity_id))]
      const names = await Promise.all(
        uniqueIds.map(async (entityId) => [entityId, await fetchOrganizationName(entityId)] as const),
      )
      setEntityNames((current) => ({
        ...current,
        ...Object.fromEntries(names),
      }))
    } catch (error) {
      setItems([])
      setTotal(0)
      setErrorMessage(getErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!featureEnabled) {
      return
    }
    void loadWatchTargets(page)
    // Pagination and filters intentionally drive loading from here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureEnabled, page, statusFilter, entityTypeFilter])

  if (!featureEnabled) {
    return <Navigate to="/dashboard" replace />
  }

  const runAction = async (targetId: string, action: string, callback: () => Promise<void>) => {
    setActionState({ id: targetId, action })
    setErrorMessage(null)
    try {
      await callback()
      await loadWatchTargets(page)
    } catch (error) {
      setErrorMessage(getErrorMessage(error))
    } finally {
      setActionState(null)
    }
  }

  const actionButtonStyle: React.CSSProperties = {
    padding: '7px 12px',
    borderRadius: 8,
    border: '1px solid #cbd5e1',
    background: '#fff',
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 600,
  }

  return (
    <div
      style={{
        maxWidth: 1200,
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
          <h1 style={{ margin: 0, fontSize: 28, color: '#0f172a' }}>Watchlist</h1>
          <div style={{ fontSize: 13, color: '#64748b', marginTop: 6 }}>
            Review, pause, resume, or manually run your watch targets.
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
              aria-label="Filter watch targets by status"
              value={statusFilter}
              onChange={(event) => {
                setPage(1)
                setStatusFilter(event.target.value as '' | WatchTargetStatus)
              }}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
            >
              <option value="">All statuses</option>
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="disabled">disabled</option>
            </select>
          </label>

          <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
            <span>Entity type</span>
            <select
              aria-label="Filter watch targets by entity type"
              value={entityTypeFilter}
              onChange={(event) => {
                setPage(1)
                setEntityTypeFilter(event.target.value as '' | WatchEntityType)
              }}
              style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
            >
              <option value="">All entity types</option>
              <option value="organization">organization</option>
              <option value="knowledge_entity">knowledge_entity</option>
            </select>
          </label>

          <button
            type="button"
            onClick={() => void loadWatchTargets(page)}
            disabled={loading}
            style={{ ...actionButtonStyle, alignSelf: 'end' }}
          >
            Retry
          </button>
        </div>
      </div>

      {loading ? <div style={{ color: '#64748b', fontSize: 14, marginBottom: 16 }}>Loading watchlist...</div> : null}
      {errorMessage ? <div style={{ color: '#b91c1c', fontSize: 14, marginBottom: 16 }}>{errorMessage}</div> : null}

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
          <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
            You are not watching any organizations yet.
          </div>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            Start from an organization detail page and click Watch.
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
              Browse organizations
            </button>
          </div>
        </div>
      ) : null}

      {!loading && items.length > 0 ? (
        <div style={{ display: 'grid', gap: 16 }}>
          {items.map((item) => {
            const busy = actionState?.id === item.id
            const isOrganization = item.entity_type === 'organization'

            return (
              <section
                key={item.id}
                style={{
                  border: '1px solid #e2e8f0',
                  borderRadius: 16,
                  background: '#fff',
                  padding: 16,
                  display: 'grid',
                  gap: 14,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 12,
                    flexWrap: 'wrap',
                    alignItems: 'start',
                  }}
                >
                  <div style={{ display: 'grid', gap: 6 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>
                      {entityNames[item.entity_id] || item.entity_id}
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b' }}>
                      entity_id: {item.entity_id} | entity_type: {item.entity_type}
                    </div>
                  </div>
                  <div
                    style={{
                      padding: '4px 10px',
                      borderRadius: 999,
                      background:
                        item.status === 'active'
                          ? '#dcfce7'
                          : item.status === 'paused'
                            ? '#fef3c7'
                            : '#e2e8f0',
                      color:
                        item.status === 'active'
                          ? '#166534'
                          : item.status === 'paused'
                            ? '#92400e'
                            : '#475569',
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  >
                    {item.status}
                  </div>
                </div>

                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
                    gap: 12,
                    fontSize: 13,
                    color: '#334155',
                  }}
                >
                  <div>
                    <div style={{ color: '#64748b', marginBottom: 4 }}>frequency</div>
                    <div>{item.frequency}</div>
                  </div>
                  <div>
                    <div style={{ color: '#64748b', marginBottom: 4 }}>last_checked_at</div>
                    <div>{formatDate(item.last_checked_at)}</div>
                  </div>
                  <div>
                    <div style={{ color: '#64748b', marginBottom: 4 }}>next_check_at</div>
                    <div>{formatDate(item.next_check_at)}</div>
                  </div>
                  <div>
                    <div style={{ color: '#64748b', marginBottom: 4 }}>last_success_at</div>
                    <div>{formatDate(item.last_success_at)}</div>
                  </div>
                  <div>
                    <div style={{ color: '#64748b', marginBottom: 4 }}>consecutive_failures</div>
                    <div>{item.consecutive_failures}</div>
                  </div>
                </div>

                {item.status === 'paused' && item.consecutive_failures > 0 ? (
                  <div
                    style={{
                      borderRadius: 10,
                      padding: '10px 12px',
                      background: '#fff7ed',
                      color: '#9a3412',
                      fontSize: 12,
                    }}
                  >
                    Monitoring may be paused because of repeated failures.
                  </div>
                ) : null}

                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                  <label style={{ display: 'grid', gap: 6, fontSize: 12, color: '#475569' }}>
                    <span>Frequency</span>
                    <select
                      aria-label={`Update frequency for ${item.entity_id}`}
                      value={item.frequency}
                      disabled={busy}
                      onChange={(event) =>
                        void runAction(item.id, 'frequency', async () => {
                          await updateWatchTarget(item.id, {
                            frequency: event.target.value as WatchFrequency,
                          })
                        })
                      }
                      style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid #cbd5e1', background: '#fff' }}
                    >
                      <option value="daily">daily</option>
                      <option value="weekly">weekly</option>
                      <option value="manual">manual</option>
                    </select>
                  </label>

                  {item.status === 'active' ? (
                    <button
                      type="button"
                      aria-label={`Pause ${item.entity_id}`}
                      disabled={busy}
                      onClick={() =>
                        void runAction(item.id, 'pause', async () => {
                          await updateWatchTarget(item.id, { status: 'paused' })
                        })
                      }
                      style={actionButtonStyle}
                    >
                      Pause
                    </button>
                  ) : null}

                  {item.status === 'paused' ? (
                    <button
                      type="button"
                      aria-label={`Resume ${item.entity_id}`}
                      disabled={busy}
                      onClick={() =>
                        void runAction(item.id, 'resume', async () => {
                          await updateWatchTarget(item.id, { status: 'active' })
                        })
                      }
                      style={actionButtonStyle}
                    >
                      Resume
                    </button>
                  ) : null}

                  <button
                    type="button"
                    aria-label={`Run ${item.entity_id} now`}
                    disabled={busy || item.status === 'disabled'}
                    onClick={() => void runAction(item.id, 'run', async () => void (await runWatchTarget(item.id)))}
                    style={actionButtonStyle}
                  >
                    Run Now
                  </button>

                  <button
                    type="button"
                    aria-label={`Toggle signals for ${item.entity_id}`}
                    disabled={busy}
                    onClick={() => setExpandedSignalsFor((current) => (current === item.id ? null : item.id))}
                    style={actionButtonStyle}
                  >
                    {expandedSignalsFor === item.id ? 'Hide Signals' : 'View Signals'}
                  </button>

                  {isOrganization ? (
                    <Link
                      to={`/dashboard/org/${item.entity_id}`}
                      style={{
                        ...actionButtonStyle,
                        textDecoration: 'none',
                        display: 'inline-flex',
                        alignItems: 'center',
                      }}
                    >
                      Open organization
                    </Link>
                  ) : null}

                  <button
                    type="button"
                    aria-label={`Remove ${item.entity_id}`}
                    disabled={busy}
                    onClick={() => void runAction(item.id, 'remove', async () => deleteWatchTarget(item.id))}
                    style={{ ...actionButtonStyle, color: '#b91c1c', borderColor: '#fecaca' }}
                  >
                    Remove
                  </button>
                </div>

                {expandedSignalsFor === item.id ? <SignalList watchTargetId={item.id} /> : null}
              </section>
            )
          })}
        </div>
      ) : null}

      {!loading && !errorMessage && items.length > 0 && totalPages > 1 ? (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 20 }}>
          <button
            type="button"
            aria-label="Previous watchlist page"
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
            aria-label="Next watchlist page"
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
