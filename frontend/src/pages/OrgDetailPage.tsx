import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts'
import { isWatchAlertUiEnabled } from '../api/watchAlerts'
import { WatchButton } from '../components/WatchButton'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || 'http://localhost:8000'

interface OrgDetail {
  id: string
  name: string
  english_name: string | null
  short_name: string | null
  country: string | null
  city: string | null
  type: string | null
  denomination: string | null
  website: string | null
  founded_year: string | null
  member_count: number | null
  employee_count: number | null
  annual_revenue: string | null
  description: string | null
  mission_statement: string | null
  leader: {
    name: string | null
    title: string | null
    bio_url: string | null
  }
  scores: {
    people: { total: number; grade: string }
    digital: { total: number; grade: string }
    intel: { total: number; grade: string }
    composite: { total: number }
  }
  flags: Record<string, boolean | null>
  social: Record<string, string | null>
}

interface Relation {
  relation_id: string
  relation_type: string
  direction: string
  confidence: number
  other_org: { id: string; name: string; country: string | null }
  investment: { amount: string; currency: string; round: string | null } | null
  evidence: Evidence | null
}

interface Evidence {
  url: string | null
  date: string | null
  source: string | null
  verified: boolean
}

interface IntelItem {
  id: string
  title: string | null
  category: string | null
  source_name: string | null
  ingested_at: string | null
}

const cardStyle: React.CSSProperties = {
  border: '1px solid #e2e8f0',
  borderRadius: 16,
  padding: 20,
  background: '#fff',
  boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
}

export function OrgDetailPage() {
  const { orgId } = useParams<{ orgId: string }>()
  const navigate = useNavigate()
  const showWatchUi = isWatchAlertUiEnabled()
  const [org, setOrg] = useState<OrgDetail | null>(null)
  const [relations, setRelations] = useState<Relation[]>([])
  const [timeline, setTimeline] = useState<IntelItem[]>([])
  const [loading, setLoading] = useState(true)
  const relationTypeMap: Record<string, string> = {
    invested_in: '投资',
    co_invested: '共同投资',
    partnered_with: '合作',
  }

  useEffect(() => {
    if (!orgId) {
      setLoading(false)
      return
    }

    void fetchOrg()
    void fetchRelations()
    void fetchTimeline()
  }, [orgId])

  const fetchOrg = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/org/${orgId}`)
      if (!res.ok) throw new Error('fetch org failed')
      const data = (await res.json()) as OrgDetail
      setOrg(data)
    } catch (e) {
      console.error('Failed to fetch organization detail:', e)
      setOrg(null)
    } finally {
      setLoading(false)
    }
  }

  const fetchRelations = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/org/${orgId}/relations`)
      if (!res.ok) throw new Error('fetch relations failed')
      const data = await res.json()
      setRelations(Array.isArray(data.relations) ? data.relations : [])
    } catch (e) {
      console.error('Failed to fetch relations:', e)
      setRelations([])
    }
  }

  const fetchTimeline = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/dashboard/org/${orgId}/timeline?limit=20`)
      if (!res.ok) throw new Error('fetch timeline failed')
      const data = await res.json()
      setTimeline(Array.isArray(data.items) ? data.items : [])
    } catch (e) {
      console.error('Failed to fetch timeline:', e)
      setTimeline([])
    }
  }

  const radarData = org
    ? [
        { dimension: 'People', score: org.scores.people.total, fullMark: 100 },
        { dimension: 'Digital', score: org.scores.digital.total, fullMark: 100 },
        { dimension: 'Intel', score: org.scores.intel.total, fullMark: 100 },
      ]
    : []

  const activeFlags = org
    ? Object.entries(org.flags)
        .filter(([, value]) => Boolean(value))
        .map(([key]) => key.replace(/_/g, ' '))
    : []

  if (loading) return <div style={{ padding: 40 }}>Loading...</div>
  if (!org) return <div style={{ padding: 40 }}>Organization not found</div>

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 32px', background: '#f8fafc', minHeight: '100vh' }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
        <button
          onClick={() => navigate('/dashboard')}
          style={{
            padding: '6px 16px',
            border: '1px solid #ddd',
            borderRadius: 6,
            background: '#fff',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          鈫?Back to Dashboard
        </button>
        {showWatchUi ? (
          <button
            type="button"
            onClick={() => navigate('/watchlist')}
            style={{
              padding: '6px 16px',
              border: '1px solid #ddd',
              borderRadius: 6,
              background: '#fff',
              cursor: 'pointer',
              fontSize: 13,
            }}
          >
            Watchlist
          </button>
        ) : null}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 24, flexWrap: 'wrap' }}>
        {[
          { id: '6f0dfcb9-23c7-48ba-8304-3d13725291d5', label: 'Albanian Orthodox (A)', grade: 'A' },
          { id: '41b40cae-b189-4ac9-aec1-e8403145de55', label: 'Victory PH (B)', grade: 'B' },
          { id: '64a4debf-6f93-4f9d-b10c-b3e925d261c5', label: 'Free Methodist (B)', grade: 'B' },
          { id: '9e92e7ca-0e6f-4c61-9772-e053b3b7a87b', label: 'SBC (C)', grade: 'C' },
          { id: '68e53497-1315-4a7c-9ae1-1aeb345e15c0', label: 'Anglican NA (C)', grade: 'C' },
        ].map((sample) => (
          <button
            key={sample.id}
            onClick={() => navigate(`/dashboard/org/${sample.id}`)}
            style={{
              padding: '6px 14px',
              borderRadius: 20,
              border: '1px solid #ddd',
              background: orgId === sample.id ? '#e3f2fd' : '#fff',
              color: orgId === sample.id ? '#1976d2' : '#555',
              fontSize: 12,
              cursor: 'pointer',
              fontWeight: orgId === sample.id ? 600 : 400,
            }}
          >
            {sample.label}
          </button>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 16,
          marginBottom: 32,
        }}
      >
        <div>
          <h1 style={{ margin: '0 0 8px', fontSize: 28, color: '#0f172a' }}>{org.name}</h1>
          {org.english_name && org.english_name !== org.name ? (
            <div style={{ color: '#888', fontSize: 14 }}>{org.english_name}</div>
          ) : null}
          <div style={{ color: '#666', fontSize: 13, marginTop: 8 }}>
            {[org.type, org.country, org.city, org.denomination].filter(Boolean).join(' · ')}
          </div>
          {org.website ? (
            <a href={org.website} target="_blank" rel="noopener noreferrer" style={{ color: '#1976d2', fontSize: 13 }}>
              {org.website}
            </a>
          ) : null}
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 42, fontWeight: 'bold', color: '#1a1a1a' }}>{org.scores.composite.total}</div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
            <span
              style={{
                padding: '4px 14px',
                borderRadius: 6,
                fontSize: 14,
                fontWeight: 'bold',
                background:
                  org.scores.composite.total >= 120
                    ? '#4caf50'
                    : org.scores.composite.total >= 90
                      ? '#8bc34a'
                      : org.scores.composite.total >= 60
                        ? '#ffc107'
                        : org.scores.composite.total >= 30
                          ? '#ff9800'
                          : '#f44336',
                color:
                  org.scores.composite.total >= 60 && org.scores.composite.total < 90
                    ? '#333'
                    : '#fff',
              }}
            >
              {org.scores.composite.total >= 120
                ? 'A'
                : org.scores.composite.total >= 90
                  ? 'B'
                  : org.scores.composite.total >= 60
                    ? 'C'
                    : org.scores.composite.total >= 30
                      ? 'D'
                      : 'F'}
            </span>
            <span style={{ fontSize: 12, color: '#888' }}>Composite</span>
          </div>
        </div>
      </div>

      {showWatchUi ? (
        <div style={{ marginBottom: 24 }}>
          <WatchButton entityId={org.id} entityType="organization" />
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div>
          <div style={{ ...cardStyle, marginBottom: 24 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Score Radar</h3>
            <ResponsiveContainer width="100%" height={280}>
              <RadarChart data={radarData}>
                <PolarGrid />
                <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 12 }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
                <Radar
                  name={org.name}
                  dataKey="score"
                  stroke="#2196f3"
                  fill="#2196f3"
                  fillOpacity={0.3}
                  strokeWidth={2}
                />
              </RadarChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 24, marginTop: 8 }}>
              {(['people', 'digital', 'intel'] as const).map((key) => (
                <div key={key} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 20, fontWeight: 'bold' }}>{org.scores[key].total}</div>
                  <div style={{ fontSize: 11, color: '#888', textTransform: 'capitalize' }}>
                    {key} · {org.scores[key].grade}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ ...cardStyle, marginBottom: 24 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Organization Profile</h3>
            <table style={{ width: '100%', fontSize: 13, lineHeight: 2 }}>
              <tbody>
                {org.founded_year ? (
                  <tr>
                    <td style={{ color: '#888', width: 120 }}>Founded</td>
                    <td>{org.founded_year}</td>
                  </tr>
                ) : null}
                {org.member_count ? (
                  <tr>
                    <td style={{ color: '#888' }}>Members</td>
                    <td>{org.member_count.toLocaleString()}</td>
                  </tr>
                ) : null}
                {org.employee_count ? (
                  <tr>
                    <td style={{ color: '#888' }}>Employees</td>
                    <td>{org.employee_count.toLocaleString()}</td>
                  </tr>
                ) : null}
                {org.leader.name ? (
                  <tr>
                    <td style={{ color: '#888' }}>Leader</td>
                    <td>
                      {org.leader.name}
                      {org.leader.title ? ` (${org.leader.title})` : ''}
                    </td>
                  </tr>
                ) : null}
                {org.annual_revenue ? (
                  <tr>
                    <td style={{ color: '#888' }}>Revenue</td>
                    <td>{org.annual_revenue}</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
            {org.description ? (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>Description</div>
                <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.6 }}>{org.description}</div>
              </div>
            ) : null}
            {org.mission_statement ? (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 6 }}>Mission</div>
                <div style={{ fontSize: 13, color: '#334155', lineHeight: 1.6 }}>{org.mission_statement}</div>
              </div>
            ) : null}
            {activeFlags.length > 0 ? (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>Signals</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {activeFlags.map((flag) => (
                    <span
                      key={flag}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 999,
                        fontSize: 11,
                        background: '#eef2ff',
                        color: '#4338ca',
                      }}
                    >
                      {flag}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div>
          <div style={{ ...cardStyle, marginBottom: 24 }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Relations · {relations.length}</h3>
            {relations.length === 0 ? (
              <div style={{ color: '#999', fontSize: 13 }}>No relations recorded yet</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {relations.map((relation) => (
                  <div
                    key={relation.relation_id}
                    style={{ padding: '12px 14px', background: '#f8f8f8', borderRadius: 8, fontSize: 13 }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 6 }}>
                      <span
                        style={{
                          padding: '2px 8px',
                          borderRadius: 4,
                          fontSize: 11,
                          background: relation.direction === 'outgoing' ? '#e3f2fd' : '#f3e5f5',
                          color: relation.direction === 'outgoing' ? '#1976d2' : '#7b1fa2',
                          marginRight: 8,
                        }}
                      >
                        {relation.direction === 'outgoing' ? '→' : '←'} {relationTypeMap[relation.relation_type] || relation.relation_type}
                      </span>
                      <a
                        href={`/dashboard/org/${relation.other_org.id}`}
                        onClick={(e) => {
                          e.preventDefault()
                          navigate(`/dashboard/org/${relation.other_org.id}`)
                        }}
                        style={{ color: '#1976d2', textDecoration: 'none', fontWeight: 500 }}
                      >
                        {relation.other_org.name}
                      </a>
                      <span style={{ color: '#999', marginLeft: 8 }}>{relation.other_org.country}</span>
                    </div>

                    {relation.investment ? (
                      <div
                        style={{
                          marginLeft: 36,
                          marginTop: 6,
                          padding: '6px 10px',
                          background: '#fff3e0',
                          borderRadius: 6,
                          fontSize: 12,
                        }}
                      >
                        <span style={{ fontWeight: 600, color: '#e65100' }}>
                          {relation.investment.currency} {relation.investment.amount}
                        </span>
                        {relation.investment.round ? (
                          <span style={{ color: '#888', marginLeft: 8 }}>· {relation.investment.round}</span>
                        ) : null}
                        {relation.evidence && relation.evidence.verified ? (
                          <span style={{ color: '#4caf50', marginLeft: 8 }}>✓ Verified</span>
                        ) : null}
                        {relation.evidence && relation.evidence.url ? (
                          <a
                            href={relation.evidence.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: '#1976d2', marginLeft: 8, fontSize: 11 }}
                          >
                            Source →
                          </a>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={cardStyle}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Intelligence Timeline · {timeline.length}</h3>
            {timeline.length === 0 ? (
              <div style={{ color: '#999', fontSize: 13 }}>No intelligence items yet</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {timeline.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      padding: '12px',
                      borderLeft: '3px solid #2196f3',
                      background: '#f8fafc',
                      borderRadius: '0 8px 8px 0',
                    }}
                  >
                    <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 4 }}>{item.title || 'Untitled'}</div>
                    <div style={{ fontSize: 11, color: '#888' }}>
                      {[item.source_name, item.category].filter(Boolean).join(' · ')}
                      {item.ingested_at ? ` · ${new Date(item.ingested_at).toLocaleDateString()}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
