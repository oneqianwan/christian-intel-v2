import { useEffect, useMemo, useState } from 'react'

interface CoverageMetric {
  label: string
  current: number
  target: number
  percentage: number
  target_percentage: number
  gap: number
  tier: string
}

interface DashboardData {
  total_organizations: number
  generated_at: string
  metrics: Record<string, CoverageMetric>
}

interface Tier1CoverageData {
  total_t1: number
  generated_at: string
  metrics: Record<string, CoverageMetric>
}

interface Tier1Gap {
  id: string
  name: string
  english_name: string | null
  country: string
  url_tier: string | null
  official_website: string | null
  leader_name: string | null
  missing_fields: string[]
}

interface PeopleCandidate {
  candidate_id: string
  org_id: string
  org_name: string
  org_country: string
  official_website: string | null
  candidate_name: string
  candidate_title: string
  confidence: number
  extraction_method: string
  source_url: string | null
  status: string
}

interface QualitySummary {
  total: number
  avg_score: number
  min_score: number
  max_score: number
  below_target: number
  top_10_weakest: Array<{
    name: string
    score: number
    missing: string[]
  }>
}

interface QualityOrganization {
  id: string
  name: string
  score: number
  field_scores: Record<string, number>
  missing_fields: string[]
  rank: number
  needs_attention: boolean
}

interface QualityResponse {
  summary: QualitySummary
  organizations: QualityOrganization[]
}

interface BulkResultItem {
  org_name: string
  status: string
  new_score?: number
  message: string
}

interface BulkEntryResponse {
  total: number
  success: number
  failed: number
  results: BulkResultItem[]
  error?: string
}

interface RecommendationItem {
  id: string
  name: string
  country: string
  website: string | null
  tier: string
  current_score: number
  missing_fields: string[]
}

interface OverviewGap {
  field: string
  coverage: number
  target: number
}

interface OverviewData {
  total_organizations: number
  tier_counts: {
    T1: number
    T2: number
  }
  countries_covered: number
  coverage: Record<string, number>
  gap_priority: OverviewGap[]
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000'

const pageStyle: React.CSSProperties = {
  minHeight: '100vh',
  overflow: 'auto',
  background: '#f8fafc',
  padding: '24px',
}

const containerStyle: React.CSSProperties = {
  maxWidth: '1180px',
  margin: '0 auto',
}

const sectionTitleStyle: React.CSSProperties = {
  fontSize: 18,
  fontWeight: 700,
  marginBottom: 12,
}

const qualityFieldLabels: Record<string, string> = {
  website: 'Website',
  people: 'People',
  contact: 'Contact',
  about: 'About',
  mission: 'Mission',
  vision: 'Vision',
  programs: 'Programs',
  ai_score: 'AI',
  digital_score: 'Digital',
  social: 'Social',
  funding: 'Funding',
}

const qualityFieldMaxScores: Record<string, number> = {
  website: 10,
  people: 15,
  contact: 5,
  about: 10,
  mission: 8,
  vision: 5,
  programs: 7,
  ai_score: 10,
  digital_score: 10,
  social: 5,
  funding: 5,
}

export function Dashboard() {
  const [activeTab, setActiveTab] = useState<'overview' | 'operations'>('overview')
  const [coverage, setCoverage] = useState<DashboardData | null>(null)
  const [tier1Coverage, setTier1Coverage] = useState<Tier1CoverageData | null>(null)
  const [selectedDocField, setSelectedDocField] = useState<string | null>(null)
  const [qualityRefreshKey, setQualityRefreshKey] = useState(0)
  const [gaps, setGaps] = useState<Tier1Gap[]>([])
  const [gapField, setGapField] = useState('website')
  const [showQuickEntry, setShowQuickEntry] = useState(false)
  const [quickEntryText, setQuickEntryText] = useState('')
  const [quickEntrySubmitting, setQuickEntrySubmitting] = useState(false)
  const [quickEntryMessage, setQuickEntryMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [candidates, setCandidates] = useState<PeopleCandidate[]>([])
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void fetchCoverage()
    void fetchTier1Coverage()
    void fetchGaps('website')
    void fetchCandidates()
  }, [])

  const fetchCoverage = async () => {
    try {
      setError(null)
      const res = await fetch(`${API_BASE}/api/dashboard/coverage`)
      if (!res.ok) {
        throw new Error(`coverage api failed: ${res.status}`)
      }
      const data = (await res.json()) as DashboardData
      setCoverage(data)
    } catch (e) {
      console.error('Failed to fetch coverage:', e)
      setError('Coverage API 拉取失败，请确认后端已启动。')
    }
  }

  const fetchTier1Coverage = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/coverage/tier1`)
      if (!res.ok) {
        throw new Error(`tier1 coverage api failed: ${res.status}`)
      }
      const data = (await res.json()) as Tier1CoverageData
      setTier1Coverage(data)
    } catch (e) {
      console.error('Failed to fetch T1 coverage:', e)
      setTier1Coverage(null)
    }
  }

  const fetchGaps = async (field: string) => {
    setLoading(true)
    setGapField(field)
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/tier1-gaps?field=${encodeURIComponent(field)}`)
      if (!res.ok) {
        throw new Error(`tier1-gaps api failed: ${res.status}`)
      }
      const data = await res.json()
      setGaps(Array.isArray(data.organizations) ? data.organizations : [])
    } catch (e) {
      console.error('Failed to fetch gaps:', e)
      setGaps([])
    } finally {
      setLoading(false)
    }
  }

  const fetchCandidates = async () => {
    setCandidateLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/people-candidates?status=pending&limit=20`)
      if (!res.ok) {
        throw new Error(`people-candidates api failed: ${res.status}`)
      }
      const data = await res.json()
      setCandidates(Array.isArray(data.candidates) ? data.candidates : [])
    } catch (e) {
      console.error('Failed to fetch candidates:', e)
      setCandidates([])
    } finally {
      setCandidateLoading(false)
    }
  }

  const reviewCandidate = async (candidateId: string, action: 'approved' | 'rejected') => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/people-candidates/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_id: candidateId, action, notes: 'mobile-review' }),
      })
      if (!res.ok) {
        throw new Error(`review api failed: ${res.status}`)
      }
      setCandidates((prev) => prev.filter((candidate) => candidate.candidate_id !== candidateId))
      if (action === 'approved') {
        void fetchCoverage()
        void fetchTier1Coverage()
        if (gapField === 'people') {
          void fetchGaps('people')
        }
      }
    } catch (e) {
      console.error('Review failed:', e)
    }
  }

  const submitQuickEntries = async () => {
    const lines = quickEntryText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)

    if (lines.length === 0) {
      setQuickEntryMessage('请先输入至少一条记录。')
      return
    }

    setQuickEntrySubmitting(true)
    setQuickEntryMessage(null)

    let success = 0
    for (const line of lines) {
      const parts = line.split('|').map((part) => part.trim())
      if (parts.length < 2) {
        continue
      }

      const [orgName, leaderName, title] = parts
      try {
        const res = await fetch(`${API_BASE}/api/dashboard/quick-people-entry`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            org_name: orgName,
            leader_name: leaderName,
            leader_title: title || 'Leader',
            notes: 'dashboard-quick-entry',
          }),
        })
        if (res.ok) {
          success += 1
        }
      } catch (e) {
        console.error('Quick entry failed:', e)
      }
    }

    const summary = `Submitted ${success}/${lines.length} entries`
    alert(summary)
    setQuickEntryMessage(summary)
    setQuickEntryText('')
    setQuickEntrySubmitting(false)
    void fetchCoverage()
    void fetchTier1Coverage()
    void fetchCandidates()
    if (gapField === 'people') {
      void fetchGaps('people')
    }
  }

  const p0Metrics = useMemo(
    () => Object.entries(coverage?.metrics || {}).filter(([, metric]) => metric.tier === 'P0'),
    [coverage],
  )
  const p1Metrics = useMemo(
    () => Object.entries(coverage?.metrics || {}).filter(([, metric]) => metric.tier === 'P1'),
    [coverage],
  )

  const handleWorkbenchSaved = async () => {
    await Promise.all([fetchCoverage(), fetchTier1Coverage()])
    setQualityRefreshKey((prev) => prev + 1)
  }

  if (!coverage) {
    return (
      <div style={pageStyle}>
        <div style={containerStyle}>
          <div style={{ padding: 20, background: '#fff', borderRadius: 14, border: '1px solid #e2e8f0' }}>
            {error || 'Loading...'}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={pageStyle}>
      <div style={containerStyle}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 30, fontWeight: 800, marginBottom: 8, color: '#0f172a' }}>Christian Intel Dashboard</h1>
          <p style={{ color: '#64748b', fontSize: 14 }}>
            全球基督教行业情报平台 | {coverage.total_organizations} Organizations | Updated:{' '}
            {new Date(coverage.generated_at).toLocaleString()}
          </p>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 24, flexWrap: 'wrap' }}>
          <button
            onClick={() => setActiveTab('overview')}
            style={{
              padding: '10px 16px',
              borderRadius: 999,
              border: '1px solid',
              borderColor: activeTab === 'overview' ? '#2563eb' : '#cbd5e1',
              background: activeTab === 'overview' ? '#2563eb' : '#fff',
              color: activeTab === 'overview' ? '#fff' : '#334155',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Overview
          </button>
          <button
            onClick={() => setActiveTab('operations')}
            style={{
              padding: '10px 16px',
              borderRadius: 999,
              border: '1px solid',
              borderColor: activeTab === 'operations' ? '#2563eb' : '#cbd5e1',
              background: activeTab === 'operations' ? '#2563eb' : '#fff',
              color: activeTab === 'operations' ? '#fff' : '#334155',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Operations
          </button>
        </div>

        {activeTab === 'overview' ? (
          <OverviewPanel apiBase={API_BASE} onOpenOperations={() => setActiveTab('operations')} />
        ) : (
          <>
            <section style={{ marginBottom: 28 }}>
              <h2 style={{ ...sectionTitleStyle, color: '#dc2626' }}>P0 Critical</h2>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: 16,
                }}
              >
                {p0Metrics.map(([key, metric]) => (
                  <MetricCard key={key} metricKey={key} metric={metric} />
                ))}
              </div>
            </section>

            <section style={{ marginBottom: 28 }}>
              <h2 style={{ ...sectionTitleStyle, color: '#ea580c' }}>P1 Important</h2>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: 16,
                }}
              >
                {p1Metrics.map(([key, metric]) => (
                  <MetricCard key={key} metricKey={key} metric={metric} />
                ))}
              </div>
            </section>

            {tier1Coverage ? (
              <section style={{ marginBottom: 28 }}>
                <h2 style={{ ...sectionTitleStyle, color: '#7c3aed' }}>T1 Top 300 Coverage</h2>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: 16,
                  }}
                >
                  {Object.entries(tier1Coverage.metrics).map(([key, metric]) => (
                    <MetricCard key={key} metricKey={key} metric={metric} />
                  ))}
                </div>
              </section>
            ) : null}

            <QualityPanel apiBase={API_BASE} refreshKey={qualityRefreshKey} onSelectField={setSelectedDocField} />

            <section
              style={{
                marginBottom: 28,
                padding: 18,
                background: '#fff7ed',
                border: '2px solid #fdba74',
                borderRadius: 16,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <span style={{ fontSize: 28, lineHeight: 1 }}>!</span>
                <h2 style={{ fontSize: 20, fontWeight: 800, color: '#9a3412', margin: 0 }}>
                  People Coverage Needs Your Input
                </h2>
              </div>

              <div style={{ color: '#9a3412', marginBottom: 14 }}>
                <div style={{ fontWeight: 700 }}>
                  Current: {tier1Coverage?.metrics?.people?.current || 0} / 300 (
                  {tier1Coverage?.metrics?.people?.percentage || 0}%)
                </div>
                <div style={{ fontSize: 13, marginTop: 6 }}>
                  People is the biggest gap. Your industry knowledge is the most efficient data source.
                </div>
              </div>

              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button
                  onClick={() => void fetchGaps('people')}
                  style={{
                    padding: '10px 14px',
                    background: '#ea580c',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 10,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  View T1 People Gaps
                </button>
                <button
                  onClick={() => setShowQuickEntry((prev) => !prev)}
                  style={{
                    padding: '10px 14px',
                    background: '#fff',
                    color: '#c2410c',
                    border: '2px solid #ea580c',
                    borderRadius: 10,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  {showQuickEntry ? 'Hide Quick Entry' : 'Quick Manual Entry'}
                </button>
              </div>

              {showQuickEntry ? (
                <div
                  style={{
                    marginTop: 16,
                    padding: 14,
                    background: '#fff',
                    borderRadius: 12,
                    border: '1px solid #fed7aa',
                  }}
                >
                  <div style={{ fontWeight: 700, color: '#0f172a', marginBottom: 6 }}>Quick People Entry</div>
                  <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
                    Format: Org Name | Leader Name | Title (one per line)
                  </div>
                  <textarea
                    rows={6}
                    value={quickEntryText}
                    onChange={(e) => setQuickEntryText(e.target.value)}
                    placeholder={
                      "Christ's Commission Fellowship | Peter Tan-Chi | Senior Pastor\nVictory Philippines | Steve Murrell | Founding Pastor"
                    }
                    style={{
                      width: '100%',
                      padding: 12,
                      borderRadius: 10,
                      border: '1px solid #cbd5e1',
                      fontSize: 13,
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                      resize: 'vertical',
                      minHeight: 140,
                      boxSizing: 'border-box',
                    }}
                  />
                  <button
                    onClick={() => void submitQuickEntries()}
                    disabled={quickEntrySubmitting}
                    style={{
                      marginTop: 10,
                      width: '100%',
                      padding: '11px 14px',
                      background: quickEntrySubmitting ? '#94a3b8' : '#16a34a',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 10,
                      fontWeight: 700,
                      cursor: quickEntrySubmitting ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {quickEntrySubmitting ? 'Submitting...' : 'Submit Entries'}
                  </button>
                  {quickEntryMessage ? (
                    <div style={{ marginTop: 8, fontSize: 12, color: '#475569' }}>{quickEntryMessage}</div>
                  ) : null}
                </div>
              ) : null}
            </section>

            <section style={{ marginBottom: 28 }}>
              <h2 style={{ ...sectionTitleStyle, color: '#0f172a' }}>T1 Gaps (Top 300 Priority)</h2>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
                {['website', 'people', 'about', 'mission'].map((field) => (
                  <button
                    key={field}
                    onClick={() => void fetchGaps(field)}
                    style={{
                      padding: '8px 14px',
                      borderRadius: 999,
                      border: '1px solid',
                      borderColor: gapField === field ? '#2563eb' : '#cbd5e1',
                      background: gapField === field ? '#2563eb' : '#fff',
                      color: gapField === field ? '#fff' : '#334155',
                      cursor: 'pointer',
                      fontSize: 13,
                      fontWeight: 600,
                    }}
                  >
                    {field} gaps
                  </button>
                ))}
              </div>

              {loading ? (
                <div style={{ padding: 18, color: '#64748b' }}>Loading...</div>
              ) : (
                <div style={{ display: 'grid', gap: 12 }}>
                  {gaps.slice(0, 20).map((org) => (
                    <div
                      key={org.id}
                      style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: 14,
                        padding: 16,
                        background: '#fff',
                        boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: 12,
                          alignItems: 'flex-start',
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>{org.name}</div>
                          <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
                            {org.country}
                            {org.english_name ? ` | ${org.english_name}` : ''}
                            {org.url_tier ? ` | URL ${org.url_tier}` : ''}
                          </div>
                        </div>
                        <div
                          style={{
                            fontSize: 12,
                            color: '#b91c1c',
                            background: '#fee2e2',
                            padding: '6px 10px',
                            borderRadius: 999,
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {org.missing_fields.join(', ')}
                        </div>
                      </div>

                      {org.official_website ? (
                        <div
                          style={{
                            marginTop: 10,
                            fontSize: 12,
                            color: '#2563eb',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {org.official_website}
                        </div>
                      ) : null}
                    </div>
                  ))}

                  {gaps.length > 20 ? (
                    <div style={{ textAlign: 'center', color: '#64748b', fontSize: 13, padding: '6px 0' }}>
                      + {gaps.length - 20} more...
                    </div>
                  ) : null}
                </div>
              )}
            </section>

            <section>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  marginBottom: 12,
                }}
              >
                <h2 style={{ ...sectionTitleStyle, color: '#0f172a', marginBottom: 0 }}>People Candidates (待审核)</h2>
                <button
                  onClick={() => void fetchCandidates()}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 10,
                    border: 'none',
                    background: '#2563eb',
                    color: '#fff',
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  Refresh
                </button>
              </div>

              {candidateLoading ? (
                <div style={{ padding: 18, color: '#64748b' }}>Loading candidates...</div>
              ) : candidates.length === 0 ? (
                <div
                  style={{
                    textAlign: 'center',
                    color: '#64748b',
                    fontSize: 14,
                    padding: '18px 0',
                    background: '#fff',
                    border: '1px solid #e2e8f0',
                    borderRadius: 14,
                  }}
                >
                  No pending candidates.
                  <button
                    onClick={() => void fetchCandidates()}
                    style={{
                      marginLeft: 8,
                      background: 'transparent',
                      border: 'none',
                      color: '#2563eb',
                      textDecoration: 'underline',
                      cursor: 'pointer',
                      fontSize: 14,
                    }}
                  >
                    Check again
                  </button>
                </div>
              ) : (
                <div style={{ display: 'grid', gap: 12 }}>
                  {candidates.map((candidate) => (
                    <div
                      key={candidate.candidate_id}
                      style={{
                        border: '1px solid #fcd34d',
                        borderRadius: 14,
                        padding: 16,
                        background: '#fefce8',
                        boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
                      }}
                    >
                      <div style={{ marginBottom: 12 }}>
                        <div style={{ fontSize: 20, fontWeight: 800, color: '#0f172a' }}>{candidate.candidate_name}</div>
                        <div style={{ color: '#1d4ed8', fontWeight: 700, marginTop: 4 }}>{candidate.candidate_title}</div>
                        <div style={{ fontSize: 13, color: '#475569', marginTop: 8 }}>
                          {candidate.org_name} ({candidate.org_country})
                        </div>
                        <div
                          style={{
                            fontSize: 12,
                            color: '#94a3b8',
                            marginTop: 6,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {candidate.official_website || 'No official website'}
                        </div>
                        <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
                          Confidence: {Math.round((candidate.confidence || 0) * 100)}% | Method:{' '}
                          {candidate.extraction_method}
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
                        <button
                          onClick={() => void reviewCandidate(candidate.candidate_id, 'approved')}
                          style={{
                            flex: 1,
                            padding: '10px 12px',
                            borderRadius: 10,
                            border: 'none',
                            background: '#16a34a',
                            color: '#fff',
                            fontWeight: 700,
                            cursor: 'pointer',
                          }}
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => void reviewCandidate(candidate.candidate_id, 'rejected')}
                          style={{
                            flex: 1,
                            padding: '10px 12px',
                            borderRadius: 10,
                            border: 'none',
                            background: '#ef4444',
                            color: '#fff',
                            fontWeight: 700,
                            cursor: 'pointer',
                          }}
                        >
                          Reject
                        </button>
                      </div>

                      {candidate.source_url ? (
                        <a
                          href={candidate.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            display: 'block',
                            textAlign: 'center',
                            fontSize: 12,
                            color: '#2563eb',
                            marginTop: 10,
                            textDecoration: 'underline',
                          }}
                        >
                          View Source Page
                        </a>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
      {selectedDocField ? (
        <FieldGapPanel
          field={selectedDocField}
          apiBase={API_BASE}
          onClose={() => setSelectedDocField(null)}
          onEntrySaved={() => void handleWorkbenchSaved()}
        />
      ) : null}
    </div>
  )
}

function OverviewPanel({
  apiBase,
  onOpenOperations,
}: {
  apiBase: string
  onOpenOperations: () => void
}) {
  const [data, setData] = useState<OverviewData | null>(null)
  const [qualityData, setQualityData] = useState<QualityResponse | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const [overviewRes, qualityRes] = await Promise.all([
          fetch(`${apiBase}/api/dashboard/overview`),
          fetch(`${apiBase}/api/dashboard/quality-scores?limit=10`),
        ])

        if (!overviewRes.ok) {
          throw new Error(`overview api failed: ${overviewRes.status}`)
        }

        const overviewJson = (await overviewRes.json()) as OverviewData
        const qualityJson = qualityRes.ok ? ((await qualityRes.json()) as QualityResponse) : null

        if (!cancelled) {
          setData(overviewJson)
          setQualityData(qualityJson)
        }
      } catch (error) {
        console.error('Failed to fetch overview:', error)
        if (!cancelled) {
          setData(null)
          setQualityData(null)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [apiBase])

  if (!data) {
    return (
      <div style={{ padding: 20, background: '#fff', borderRadius: 16, border: '1px solid #e2e8f0' }}>
        Loading...
      </div>
    )
  }

  const { coverage, gap_priority } = data
  const weakest = qualityData?.summary?.top_10_weakest || []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div
        style={{
          padding: 24,
          borderRadius: 20,
          background: 'linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%)',
          border: '1px solid #dbeafe',
        }}
      >
        <div style={{ fontSize: 14, color: '#2563eb', fontWeight: 700, marginBottom: 8 }}>行业产品首页</div>
        <div style={{ fontSize: 28, fontWeight: 800, color: '#0f172a', marginBottom: 8 }}>全球基督教行业全景</div>
        <div style={{ color: '#475569', fontSize: 15, lineHeight: 1.6 }}>
          投资人第一眼看到机构总量、国家覆盖、核心字段成熟度与最优先缺口，快速判断 Christian Intel 的数据资产厚度。
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 16,
        }}
      >
        <OverviewStatCard
          title="Total Organizations"
          value={data.total_organizations}
          subtitle={`T1: ${data.tier_counts.T1} | T2: ${data.tier_counts.T2}`}
          colors={{ bg: '#eff6ff', border: '#bfdbfe', text: '#1d4ed8', value: '#1e3a8a' }}
        />
        <OverviewStatCard
          title="Countries Covered"
          value={data.countries_covered}
          subtitle="Global coverage footprint"
          colors={{ bg: '#ecfdf5', border: '#bbf7d0', text: '#15803d', value: '#14532d' }}
        />
        <OverviewStatCard
          title="Deep Profile (T1)"
          value={`${coverage.deep_profile}%`}
          subtitle="Structured crawl completion"
          colors={{ bg: '#f5f3ff', border: '#ddd6fe', text: '#7c3aed', value: '#4c1d95' }}
        />
        <OverviewStatCard
          title="People (T1)"
          value={`${coverage.people}%`}
          subtitle="Leadership graph readiness"
          colors={{ bg: '#fff7ed', border: '#fed7aa', text: '#ea580c', value: '#9a3412' }}
        />
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.3fr) minmax(0, 1fr)',
          gap: 16,
        }}
      >
        <section style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 16, padding: 20 }}>
          <h3 style={{ fontSize: 18, fontWeight: 800, marginBottom: 16, color: '#0f172a' }}>T1 Data Coverage</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {Object.entries(coverage).map(([field, pct]) => (
              <CoverageBar key={field} field={field} pct={pct} />
            ))}
          </div>
        </section>

        <section style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 16, padding: 20 }}>
          <h3 style={{ fontSize: 18, fontWeight: 800, marginBottom: 16, color: '#0f172a' }}>
            Priority Gaps - Fix These First
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
            {gap_priority.map((gap) => (
              <div
                key={gap.field}
                style={{
                  border: '1px solid #e2e8f0',
                  borderRadius: 14,
                  padding: 14,
                  textAlign: 'center',
                  background: '#fafafa',
                }}
              >
                <div style={{ fontSize: 28, fontWeight: 800, color: '#dc2626' }}>{gap.coverage}%</div>
                <div style={{ fontSize: 14, color: '#0f172a', fontWeight: 700, textTransform: 'capitalize' }}>
                  {gap.field}
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>target: {gap.target}%</div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 16, padding: 20 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
            marginBottom: 16,
            flexWrap: 'wrap',
          }}
        >
          <h3 style={{ fontSize: 18, fontWeight: 800, color: '#0f172a', margin: 0 }}>Weakest 10 Organizations</h3>
          <button
            onClick={onOpenOperations}
            style={{
              padding: '9px 14px',
              borderRadius: 10,
              border: 'none',
              background: '#2563eb',
              color: '#fff',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Open Operations Workbench
          </button>
        </div>

        {weakest.length === 0 ? (
          <div style={{ color: '#64748b' }}>Quality data unavailable.</div>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {weakest.map((org, index) => (
              <div
                key={`${org.name}-${index}`}
                style={{
                  padding: 14,
                  border: '1px solid #e2e8f0',
                  borderRadius: 12,
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 12,
                  alignItems: 'center',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 800, color: '#0f172a' }}>
                    #{index + 1} {org.name}
                  </div>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                    Score: {org.score} | Missing: {org.missing?.slice(0, 3).join(', ')}
                  </div>
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: org.score >= 60 ? '#16a34a' : '#dc2626' }}>
                  {org.score}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function OverviewStatCard({
  title,
  value,
  subtitle,
  colors,
}: {
  title: string
  value: string | number
  subtitle: string
  colors: { bg: string; border: string; text: string; value: string }
}) {
  return (
    <div
      style={{
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: 16,
        padding: 18,
      }}
    >
      <div style={{ fontSize: 13, color: colors.text, marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 32, fontWeight: 800, color: colors.value }}>{value}</div>
      <div style={{ fontSize: 12, color: colors.text, marginTop: 6 }}>{subtitle}</div>
    </div>
  )
}

function CoverageBar({ field, pct }: { field: string; pct: number }) {
  const color = pct >= 70 ? '#22c55e' : pct >= 40 ? '#eab308' : '#ef4444'

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
        <span style={{ color: '#0f172a', fontWeight: 700, textTransform: 'capitalize' }}>
          {field.replace('_', ' ')}
        </span>
        <span style={{ color, fontWeight: 700 }}>{pct}%</span>
      </div>
      <div style={{ width: '100%', height: 10, background: '#e2e8f0', borderRadius: 999 }}>
        <div
          style={{
            width: `${Math.min(pct, 100)}%`,
            height: '100%',
            background: color,
            borderRadius: 999,
          }}
        />
      </div>
    </div>
  )
}

function QualityPanel({
  apiBase,
  refreshKey,
  onSelectField,
}: {
  apiBase: string
  refreshKey: number
  onSelectField: (field: string) => void
}) {
  const [qualityData, setQualityData] = useState<QualityResponse | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/api/dashboard/quality-scores?limit=300`)
        if (!res.ok) {
          throw new Error(`quality-scores api failed: ${res.status}`)
        }
        const data = (await res.json()) as QualityResponse
        if (!cancelled && data.summary) {
          setQualityData(data)
        }
      } catch (error) {
        console.error('Failed to fetch quality scores:', error)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [apiBase, refreshKey])

  if (!qualityData) {
    return (
      <section
        style={{
          marginBottom: 28,
          padding: 20,
          background: '#fff',
          borderRadius: 16,
          border: '1px solid #e2e8f0',
          color: '#64748b',
        }}
      >
        Loading Quality Scores...
      </section>
    )
  }

  const summary = qualityData.summary
  const orgs = qualityData.organizations || []

  const fieldAvgs: Record<string, number> = {}
  Object.entries(qualityFieldLabels).forEach(([field]) => {
    const total = orgs.reduce((sum, org) => sum + (org.field_scores?.[field] || 0), 0)
    const maxPossible = orgs.length * (qualityFieldMaxScores[field] || 1)
    fieldAvgs[field] = maxPossible > 0 ? Math.round((total / maxPossible) * 100) : 0
  })

  const weakestOrgs = orgs.filter((org) => org.needs_attention).slice(0, 10)

  return (
    <section style={{ marginBottom: 28 }}>
      <h2 style={{ fontSize: 20, fontWeight: 800, marginBottom: 16, color: '#0f172a' }}>
        Data Operation Center - T1 Quality Overview
      </h2>

      <div
        style={{
          padding: 14,
          background: summary.avg_score < 30 ? '#fef2f2' : '#f0fdf4',
          border: `1px solid ${summary.avg_score < 30 ? '#fecaca' : '#bbf7d0'}`,
          borderRadius: 12,
          marginBottom: 16,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 14,
        }}
      >
        <span style={{ fontWeight: 800, color: '#0f172a' }}>T1 Average Quality: {summary.avg_score}/100</span>
        <span style={{ color: '#b91c1c', fontWeight: 700 }}>{summary.below_target} organizations below target</span>
        <span style={{ color: '#64748b', fontSize: 13 }}>
          range: {summary.min_score} - {summary.max_score}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 12,
          marginBottom: 20,
        }}
      >
        {Object.entries(qualityFieldLabels).map(([field, label]) => {
          const pct = fieldAvgs[field] || 0
          const color = pct >= 80 ? '#16a34a' : pct >= 50 ? '#d97706' : '#dc2626'

          return (
            <button
              key={field}
              onClick={() => onSelectField(field)}
              style={{
                padding: 12,
                border: '1px solid #e2e8f0',
                borderRadius: 12,
                cursor: 'pointer',
                textAlign: 'center',
                background: '#fff',
              }}
            >
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 24, fontWeight: 800, color }}>{pct}%</div>
            </button>
          )
        })}
      </div>

      <h3 style={{ fontSize: 16, fontWeight: 800, marginBottom: 12, color: '#0f172a' }}>
        Top 10 Weakest - Fix These First
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {weakestOrgs.map((org) => {
          const focusField = org.missing_fields?.[0] || 'people'
          return (
            <div
              key={org.id}
              style={{
                padding: 12,
                border: '1px solid #e2e8f0',
                borderRadius: 10,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 12,
                background: '#fff',
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 800, color: '#0f172a' }}>
                  #{org.rank} {org.name}
                </div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                  Score: {org.score} | Missing: {org.missing_fields?.slice(0, 3).join(', ')}
                  {org.missing_fields?.length > 3 ? ` +${org.missing_fields.length - 3} more` : ''}
                </div>
              </div>
              <button
                onClick={() => onSelectField(focusField)}
                style={{
                  padding: '6px 12px',
                  background: '#2563eb',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 8,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                Fix
              </button>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function FieldGapPanel({
  field,
  apiBase,
  onClose,
  onEntrySaved,
}: {
  field: string
  apiBase: string
  onClose: () => void
  onEntrySaved: () => void
}) {
  const [gaps, setGaps] = useState<Tier1Gap[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [entryMode, setEntryMode] = useState<string | null>(null)
  const [entryValue, setEntryValue] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [lastResult, setLastResult] = useState<{ success?: boolean; message?: string; error?: string } | null>(null)
  const [bulkMode, setBulkMode] = useState(false)
  const [bulkText, setBulkText] = useState('')
  const [bulkSubmitting, setBulkSubmitting] = useState(false)
  const [bulkResult, setBulkResult] = useState<BulkEntryResponse | null>(null)
  const [recommendations, setRecommendations] = useState<RecommendationItem[]>([])
  const [recommendLoading, setRecommendLoading] = useState(false)

  const fieldLabelMap: Record<string, string> = {
    website: 'Website URL',
    people: 'People (Leader)',
    contact: 'Contact',
    about: 'About',
    mission: 'Mission',
    vision: 'Vision',
    programs: 'Programs',
    ai_score: 'AI Score',
    digital_score: 'Digital Score',
    social: 'Social',
    funding: 'Funding',
  }

  const entryHints: Record<string, string> = {
    people: 'Leader Name | Title (e.g. Peter Tan-Chi | Senior Pastor)',
    website: 'https://www.example.org',
    contact: 'email@example.org',
    about: 'Organization description text...',
    mission: 'Mission statement text...',
    vision: 'Vision statement text...',
    ai_score: '1-5 (e.g. 3)',
    digital_score: '1-5 (e.g. 3)',
    social: 'https://facebook.com/example',
  }

  const loadRecommendations = async (): Promise<RecommendationItem[]> => {
    setRecommendLoading(true)
    try {
      const res = await fetch(`${apiBase}/api/dashboard/recommend-next?field=${encodeURIComponent(field)}`)
      if (!res.ok) {
        throw new Error(`recommend-next api failed: ${res.status}`)
      }
      const data = await res.json()
      const nextRecommendations = Array.isArray(data.recommendations) ? data.recommendations : []
      setRecommendations(nextRecommendations)
      return nextRecommendations
    } catch (recommendError) {
      console.error('Failed to fetch recommendations:', recommendError)
      setRecommendations([])
      return []
    } finally {
      setRecommendLoading(false)
    }
  }

  const pickNextOrg = (availableGaps: Tier1Gap[], recommendedOrgs: RecommendationItem[]) => {
    if (availableGaps.length === 0) {
      return null
    }

    for (const recommendation of recommendedOrgs) {
      const matchedGap = availableGaps.find((gap) => gap.id === recommendation.id)
      if (matchedGap) {
        return matchedGap
      }
    }

    return availableGaps[0] || null
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setEntryMode(null)
    setEntryValue('')
    setLastResult(null)
    setBulkMode(false)
    setBulkText('')
    setBulkResult(null)

    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/api/dashboard/tier1-gaps?field=${encodeURIComponent(field)}&limit=30`)
        if (!res.ok) {
          throw new Error(`tier1-gaps api failed: ${res.status}`)
        }
        const data = await res.json()
        if (!cancelled) {
          setGaps(Array.isArray(data.organizations) ? data.organizations : [])
        }
      } catch (loadError) {
        console.error('Failed to fetch field gaps:', loadError)
        if (!cancelled) {
          setError('Gap list failed to load.')
          setGaps([])
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()
    void loadRecommendations()
    return () => {
      cancelled = true
    }
  }, [apiBase, field])

  const submitEntry = async (orgId: string) => {
    if (!entryValue.trim()) {
      return
    }

    setSubmitting(true)
    setLastResult(null)

    try {
      const res = await fetch(`${apiBase}/api/dashboard/inline-entry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          org_id: orgId,
          field,
          value: entryValue,
          notes: 'gap-workbench',
        }),
      })

      const result = (await res.json()) as { success?: boolean; message?: string; error?: string; org_name?: string }
      if (result.success) {
        const remainingGaps = gaps.filter((gap) => gap.id !== orgId)

        setEntryValue('')
        setGaps(remainingGaps)
        onEntrySaved()
        const refreshedRecommendations = await loadRecommendations()
        const nextOrg = pickNextOrg(remainingGaps, refreshedRecommendations)

        if (nextOrg && nextOrg.id !== orgId) {
          setLastResult({
            success: true,
            message: `Updated ${field} for ${result.org_name || 'organization'}. Auto-selected next recommended org: ${nextOrg.name}. Continue entering...`,
          })
          window.setTimeout(() => {
            setEntryMode(nextOrg.id)
            setEntryValue('')
          }, 300)
        } else {
          setEntryMode(null)
          setLastResult(result)
        }
      } else {
        setLastResult({ error: result.error || 'Failed' })
      }
    } catch (submitError) {
      setLastResult({ error: String(submitError) })
    } finally {
      setSubmitting(false)
    }
  }

  const submitBulk = async () => {
    if (!bulkText.trim()) {
      return
    }

    setBulkSubmitting(true)
    setBulkResult(null)
    setLastResult(null)

    try {
      const lines = bulkText
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)

      const entries = lines
        .map((line) => {
          const parts = line.split('|').map((part) => part.trim())
          return {
            org_name: parts[0] || '',
            value: parts.slice(1, 3).join(' | ').trim(),
            notes: parts[3] || '',
          }
        })
        .filter((entry) => entry.org_name && entry.value)

      const res = await fetch(`${apiBase}/api/dashboard/inline-entry/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field, entries }),
      })
      const result = (await res.json()) as BulkEntryResponse
      setBulkResult(result)

      const successNames =
        result.results?.filter((item) => item.status === 'success').map((item) => item.org_name.toLowerCase()) || []
      if (successNames.length > 0) {
        setGaps((prev) =>
          prev.filter((gap) => {
            const gapName = gap.name.toLowerCase()
            return !successNames.some((name) => gapName.includes(name) || name.includes(gapName))
          }),
        )
        setBulkText('')
        onEntrySaved()
        void loadRecommendations()
      }
    } catch (bulkError) {
      setBulkResult({ total: 0, success: 0, failed: 0, results: [], error: String(bulkError) })
    } finally {
      setBulkSubmitting(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(15, 23, 42, 0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        padding: 20,
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          background: '#fff',
          padding: 20,
          borderRadius: 16,
          maxWidth: 680,
          width: '100%',
          maxHeight: '80vh',
          overflow: 'auto',
          boxShadow: '0 24px 80px rgba(15, 23, 42, 0.25)',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
            gap: 12,
          }}
        >
          <h3 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: '#0f172a' }}>
            {fieldLabelMap[field] || field} Gaps ({gaps.length} remaining)
          </h3>
          <button
            onClick={onClose}
            style={{ fontSize: 20, border: 'none', background: 'transparent', cursor: 'pointer', color: '#64748b' }}
          >
            x
          </button>
        </div>

        {lastResult?.success ? (
          <div
            style={{
              padding: 10,
              background: '#dcfce7',
              borderRadius: 8,
              marginBottom: 12,
              color: '#166534',
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            {lastResult.message}
          </div>
        ) : null}
        {lastResult?.error ? (
          <div
            style={{
              padding: 10,
              background: '#fee2e2',
              borderRadius: 8,
              marginBottom: 12,
              color: '#b91c1c',
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            {lastResult.error}
          </div>
        ) : null}

        {loading ? <div style={{ color: '#64748b' }}>Loading...</div> : null}
        {error ? <div style={{ color: '#b91c1c' }}>{error}</div> : null}

        {!loading && !error ? (
          gaps.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: 40,
                color: '#16a34a',
                fontSize: 18,
                fontWeight: 800,
              }}
            >
              All caught up! No more {fieldLabelMap[field]} gaps.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {gaps.slice(0, 15).map((org) => (
                <div
                  key={org.id}
                  style={{
                    padding: 12,
                    border: entryMode === org.id ? '2px solid #2563eb' : '1px solid #e2e8f0',
                    borderRadius: 10,
                    background: entryMode === org.id ? '#eff6ff' : recommendations[0]?.id === org.id ? '#fff7ed' : '#fff',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'flex-start',
                      gap: 12,
                      marginBottom: entryMode === org.id ? 8 : 0,
                    }}
                  >
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, color: '#0f172a' }}>{org.name}</div>
                      <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                        {org.country}
                        {org.official_website ? ` | ${org.official_website}` : ''}
                      </div>
                    </div>

                    {entryMode !== org.id ? (
                      <button
                        onClick={() => {
                          setEntryMode(org.id)
                          setEntryValue('')
                          setLastResult(null)
                        }}
                        style={{
                          padding: '6px 14px',
                          background: '#dc2626',
                          color: '#fff',
                          border: 'none',
                          borderRadius: 8,
                          cursor: 'pointer',
                          fontSize: 13,
                          fontWeight: 700,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        + Add
                      </button>
                    ) : null}
                  </div>

                  {entryMode === org.id ? (
                    <div style={{ marginTop: 8 }}>
                      <input
                        type="text"
                        value={entryValue}
                        onChange={(e) => setEntryValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            void submitEntry(org.id)
                          }
                        }}
                        placeholder={entryHints[field] || 'Enter value...'}
                        style={{
                          width: '100%',
                          padding: 10,
                          border: '1px solid #cbd5e1',
                          borderRadius: 8,
                          fontSize: 14,
                          marginBottom: 8,
                          boxSizing: 'border-box',
                        }}
                        autoFocus
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          onClick={() => void submitEntry(org.id)}
                          disabled={submitting || !entryValue.trim()}
                          style={{
                            flex: 1,
                            padding: '8px 16px',
                            background: submitting ? '#94a3b8' : '#16a34a',
                            color: '#fff',
                            border: 'none',
                            borderRadius: 8,
                            cursor: submitting ? 'not-allowed' : 'pointer',
                            fontWeight: 700,
                          }}
                        >
                          {submitting ? 'Saving...' : 'Submit'}
                        </button>
                        <button
                          onClick={() => {
                            setEntryMode(null)
                            setEntryValue('')
                          }}
                          style={{
                            padding: '8px 16px',
                            background: '#e2e8f0',
                            border: 'none',
                            borderRadius: 8,
                            cursor: 'pointer',
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}

              {gaps.length > 15 ? (
                <div style={{ textAlign: 'center', color: '#64748b', padding: 8 }}>+ {gaps.length - 15} more...</div>
              ) : null}

              {!bulkMode ? (
                <button
                  onClick={() => setBulkMode(true)}
                  style={{
                    padding: '10px 20px',
                    background: '#2563eb',
                    color: '#fff',
                    border: 'none',
                    borderRadius: 8,
                    cursor: 'pointer',
                    marginTop: 8,
                    width: '100%',
                    fontWeight: 700,
                  }}
                >
                  Switch to Bulk Paste Mode
                </button>
              ) : (
                <div
                  style={{
                    marginTop: 8,
                    padding: 16,
                    background: '#f8fafc',
                    borderRadius: 12,
                    border: '1px solid #e2e8f0',
                  }}
                >
                  <div style={{ fontWeight: 800, marginBottom: 8, color: '#0f172a' }}>Bulk Paste Entry</div>
                  <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8 }}>
                    Format: Organization Name | Value (one per line)
                    {field === 'people' ? (
                      <>
                        <br />
                        Example: Christ&apos;s Commission Fellowship | Peter Tan-Chi | Senior Pastor
                      </>
                    ) : null}
                  </div>
                  <textarea
                    value={bulkText}
                    onChange={(e) => setBulkText(e.target.value)}
                    placeholder={'Org Name | Value\nOrg Name | Value\n...'}
                    style={{
                      width: '100%',
                      padding: 10,
                      border: '1px solid #cbd5e1',
                      borderRadius: 8,
                      fontSize: 13,
                      minHeight: 120,
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                      boxSizing: 'border-box',
                    }}
                  />
                  <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                    <button
                      onClick={() => void submitBulk()}
                      disabled={bulkSubmitting || !bulkText.trim()}
                      style={{
                        flex: 1,
                        padding: '10px',
                        background: bulkSubmitting ? '#94a3b8' : '#16a34a',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 8,
                        cursor: bulkSubmitting ? 'not-allowed' : 'pointer',
                        fontWeight: 700,
                      }}
                    >
                      {bulkSubmitting
                        ? 'Submitting...'
                        : `Submit ${bulkText.split('\n').filter((line) => line.trim()).length} entries`}
                    </button>
                    <button
                      onClick={() => {
                        setBulkMode(false)
                        setBulkText('')
                        setBulkResult(null)
                      }}
                      style={{
                        padding: '10px 20px',
                        background: '#e2e8f0',
                        border: 'none',
                        borderRadius: 8,
                        cursor: 'pointer',
                      }}
                    >
                      Cancel
                    </button>
                  </div>

                  {bulkResult ? (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 10,
                        borderRadius: 8,
                        background: bulkResult.error ? '#fee2e2' : '#dcfce7',
                      }}
                    >
                      {bulkResult.error ? (
                        <div style={{ color: '#b91c1c', fontWeight: 700 }}>{bulkResult.error}</div>
                      ) : (
                        <div>
                          <div style={{ fontWeight: 800, color: '#166534' }}>
                            {bulkResult.success} success, {bulkResult.failed} failed
                          </div>
                          {bulkResult.results?.filter((item) => item.status === 'not_found').length ? (
                            <details style={{ marginTop: 8, fontSize: 12 }}>
                              <summary style={{ color: '#92400e', cursor: 'pointer' }}>
                                {bulkResult.results.filter((item) => item.status === 'not_found').length} not found -
                                click to see
                              </summary>
                              <div style={{ marginTop: 4, color: '#475569' }}>
                                {bulkResult.results
                                  .filter((item) => item.status === 'not_found')
                                  .map((item) => item.org_name)
                                  .join(', ')}
                              </div>
                            </details>
                          ) : null}
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              )}

              <SmartRecommend
                recommendations={recommendations}
                loading={recommendLoading}
                onPick={(orgId) => {
                  setEntryMode(orgId)
                  setEntryValue('')
                  setBulkMode(false)
                  setLastResult(null)
                }}
              />
            </div>
          )
        ) : null}
      </div>
    </div>
  )
}

function SmartRecommend({
  recommendations,
  loading,
  onPick,
}: {
  recommendations: RecommendationItem[]
  loading: boolean
  onPick: (orgId: string) => void
}) {
  if (loading) {
    return <div style={{ color: '#64748b', marginTop: 20 }}>Loading recommendations...</div>
  }

  if (recommendations.length === 0) {
    return null
  }

  return (
    <div style={{ marginTop: 20, padding: 16, background: '#fef3c7', borderRadius: 12, border: '1px solid #fcd34d' }}>
      <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 8, color: '#92400e' }}>
        Top 5 Most Urgent - Fix These First
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {recommendations.map((rec, index) => (
          <div
            key={rec.id}
            style={{
              padding: 10,
              background: '#fff',
              borderRadius: 8,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 700, color: '#0f172a' }}>
                #{index + 1} {rec.name}
                {index === 0 ? (
                  <span
                    style={{
                      marginLeft: 8,
                      fontSize: 11,
                      fontWeight: 800,
                      color: '#92400e',
                      background: '#fde68a',
                      borderRadius: 999,
                      padding: '2px 8px',
                    }}
                  >
                    CURRENT BEST
                  </span>
                ) : null}
              </div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
                Tier: {rec.tier} | Score: {rec.current_score} | Missing: {rec.missing_fields?.join(', ')}
              </div>
            </div>
            <button
              onClick={() => onPick(rec.id)}
              style={{
                padding: '4px 12px',
                background: '#dc2626',
                color: '#fff',
                border: 'none',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 12,
                whiteSpace: 'nowrap',
              }}
            >
              Next
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function MetricCard({ metricKey, metric }: { metricKey: string; metric: CoverageMetric }) {
  const progress = metric.percentage
  const color =
    progress >= 80 ? '#22c55e' : progress >= 50 ? '#eab308' : progress >= 20 ? '#f97316' : '#ef4444'

  return (
    <div
      key={metricKey}
      style={{
        border: '1px solid #e2e8f0',
        borderRadius: 16,
        background: '#fff',
        padding: 18,
        boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
      }}
    >
      <div style={{ fontSize: 13, color: '#64748b', marginBottom: 6 }}>{metric.label}</div>
      <div style={{ fontSize: 30, fontWeight: 800, color: '#0f172a', marginBottom: 12 }}>
        {metric.current}
        <span style={{ fontSize: 14, fontWeight: 500, color: '#94a3b8' }}> / {metric.target}</span>
      </div>
      <div style={{ width: '100%', height: 10, borderRadius: 999, background: '#e2e8f0', marginBottom: 8 }}>
        <div
          style={{
            width: `${Math.min(progress, 100)}%`,
            height: '100%',
            borderRadius: 999,
            background: color,
          }}
        />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#64748b' }}>
        <span>{progress}%</span>
        <span>target: {metric.target_percentage}%</span>
      </div>
      <div style={{ marginTop: 8, fontSize: 12, color: '#94a3b8' }}>gap: {metric.gap}</div>
    </div>
  )
}

export default Dashboard
