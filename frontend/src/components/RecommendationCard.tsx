import type {
  ContactSnapshot,
  PartnershipRecommendation,
  PartnershipRecommendationPayload,
  RelationshipSnapshot,
  ScoreSnapshot,
} from '../types/partnershipRecommendation'

interface RecommendationCardProps {
  payload: PartnershipRecommendationPayload
  errorMessage?: string | null
}

const shellStyle: React.CSSProperties = {
  border: '1px solid #e5e7eb',
  borderRadius: '14px',
  background: '#fff',
  padding: '16px',
}

const chipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '4px 8px',
  borderRadius: '999px',
  fontSize: '12px',
  fontWeight: 600,
  background: '#eff6ff',
  color: '#1d4ed8',
}

const labelStyle: React.CSSProperties = {
  fontSize: '12px',
  color: '#6b7280',
}

const valueStyle: React.CSSProperties = {
  fontSize: '14px',
  color: '#111827',
  fontWeight: 600,
}

const snapshotCardStyle: React.CSSProperties = {
  padding: '12px',
  borderRadius: '10px',
  background: '#f8fafc',
  border: '1px solid #e2e8f0',
}

const renderListOrNone = (items: string[]) => {
  if (!items.length) {
    return <div style={{ fontSize: '13px', color: '#6b7280' }}>none</div>
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
      {items.map((item, index) => (
        <span
          key={`${item}-${index}`}
          style={{
            padding: '4px 8px',
            borderRadius: '999px',
            fontSize: '12px',
            background: '#f1f5f9',
            color: '#334155',
          }}
        >
          {item}
        </span>
      ))}
    </div>
  )
}

const renderScoreSnapshot = (scoreSnapshot: ScoreSnapshot) => (
  <div style={snapshotCardStyle} data-testid="recommendation-score-snapshot">
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>score_snapshot</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>people_score: {scoreSnapshot.people_score ?? 'N/A'}</div>
      <div>digital_score: {scoreSnapshot.digital_score ?? 'N/A'}</div>
      <div>intel_score: {scoreSnapshot.intel_score ?? 'N/A'}</div>
    </div>
  </div>
)

const renderRelationshipSnapshot = (relationshipSnapshot: RelationshipSnapshot) => (
  <div style={snapshotCardStyle} data-testid="recommendation-relationship-snapshot">
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>relationship_snapshot</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>has_relationship_path: {String(Boolean(relationshipSnapshot.has_relationship_path))}</div>
      <div>relationship_count: {relationshipSnapshot.relationship_count}</div>
      <div>strongest_relationship_type: {relationshipSnapshot.strongest_relationship_type || 'N/A'}</div>
      <div>
        relationship_path_summary:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(relationshipSnapshot.relationship_path_summary || [])}</div>
      </div>
    </div>
  </div>
)

const renderContactSnapshot = (contactSnapshot: ContactSnapshot) => (
  <div style={snapshotCardStyle} data-testid="recommendation-contact-snapshot">
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>contact_snapshot</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>has_website: {String(Boolean(contactSnapshot.has_website))}</div>
      <div>has_email: {String(Boolean(contactSnapshot.has_email))}</div>
      <div>has_phone: {String(Boolean(contactSnapshot.has_phone))}</div>
      <div>has_social: {String(Boolean(contactSnapshot.has_social))}</div>
      <div>contact_count: {contactSnapshot.contact_count}</div>
      <div>verified_contact_count: {contactSnapshot.verified_contact_count}</div>
      <div>missing_source_count: {contactSnapshot.missing_source_count}</div>
    </div>
  </div>
)

const renderRecommendationItem = (item: PartnershipRecommendation, index: number) => (
  <div
    key={`${item.target_org.id}-${index}`}
    style={{
      padding: '14px',
      borderRadius: '12px',
      border: '1px solid #dbeafe',
      background: '#f8fbff',
      display: 'grid',
      gap: '12px',
    }}
  >
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
      <div>
        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e3a8a' }}>{item.target_org.name}</div>
        <div style={{ fontSize: '13px', color: '#475569', marginTop: '4px' }}>
          {[item.target_org.country, item.target_org.city, item.target_org.denomination].filter(Boolean).join(' · ') || 'N/A'}
        </div>
      </div>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <span style={chipStyle}>score {item.recommendation_score}</span>
        <span style={chipStyle}>priority {item.priority}</span>
        <span style={chipStyle}>confidence {item.confidence}</span>
      </div>
    </div>

    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>recommendation_score: {item.recommendation_score}</div>
      <div>priority: {item.priority}</div>
      <div>confidence: {item.confidence}</div>
      <div>recommended_next_action: {item.recommended_next_action}</div>
      <div>explanation: {item.explanation}</div>
      <div>target_source_name: {item.target_org.source_name || 'N/A'}</div>
      <div>
        {item.target_org.source_url ? (
          <a href={item.target_org.source_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
            target_source_url: {item.target_org.source_url}
          </a>
        ) : (
          <span style={{ color: '#64748b' }}>target_source_url: N/A</span>
        )}
      </div>
    </div>

    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>reason_codes</div>
      {renderListOrNone(item.reason_codes || [])}
    </div>

    <div style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
      {renderScoreSnapshot(item.score_snapshot)}
      {renderRelationshipSnapshot(item.relationship_snapshot)}
      {renderContactSnapshot(item.contact_snapshot)}
    </div>

    <div style={{ display: 'grid', gap: '10px' }}>
      <div>
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>risks</div>
        {renderListOrNone(item.risks || [])}
      </div>
      <div>
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>warnings</div>
        {renderListOrNone(item.warnings || [])}
      </div>
    </div>
  </div>
)

export function RecommendationCard({ payload, errorMessage = null }: RecommendationCardProps) {
  const organization = payload.organization
  const summary = payload.summary
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : []
  const recommendations = Array.isArray(payload.recommendations) ? payload.recommendations : []
  const emptyState = !organization || payload.found === false || recommendations.length === 0

  return (
    <section style={shellStyle} data-testid="recommendation-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <div>
          <div style={{ fontSize: '16px', fontWeight: 800, color: '#111827', marginBottom: '4px' }}>合作对象推荐</div>
          <div style={{ fontSize: '13px', color: '#6b7280' }}>仅展示后端规则化 recommendations payload，不做前端猜测或文本硬解析。</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span style={chipStyle}>recommended {summary?.recommended_count ?? 0}</span>
          <span style={chipStyle}>high_priority {summary?.high_priority_count ?? 0}</span>
          <span style={chipStyle}>warnings {summary?.warning_count ?? 0}</span>
        </div>
      </div>

      {organization ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: '12px',
            padding: '14px',
            borderRadius: '12px',
            background: '#f8fafc',
            border: '1px solid #e2e8f0',
            marginBottom: '16px',
          }}
          data-testid="recommendation-card-organization"
        >
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={labelStyle}>当前机构</div>
            <div style={{ ...valueStyle, fontSize: '18px' }}>{organization.name}</div>
          </div>
          <div>
            <div style={labelStyle}>来源名称</div>
            <div style={valueStyle}>{organization.source_name || 'N/A'}</div>
          </div>
          <div>
            <div style={labelStyle}>来源链接</div>
            <div style={{ ...valueStyle, fontWeight: 500 }}>
              {organization.source_url ? (
                <a href={organization.source_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
                  {organization.source_url}
                </a>
              ) : (
                'N/A'
              )}
            </div>
          </div>
          <div>
            <div style={labelStyle}>最近更新</div>
            <div style={valueStyle}>{organization.updated_at || 'N/A'}</div>
          </div>
        </div>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '12px',
          marginBottom: '16px',
        }}
        data-testid="recommendation-card-summary"
      >
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>候选机构数</div>
          <div style={valueStyle}>{summary?.candidate_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>推荐数量</div>
          <div style={valueStyle}>{summary?.recommended_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>高优先级数量</div>
          <div style={valueStyle}>{summary?.high_priority_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>可联系候选数量</div>
          <div style={valueStyle}>{summary?.with_contact_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>存在关系路径数量</div>
          <div style={valueStyle}>{summary?.with_relationship_path_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>warning 数量</div>
          <div style={valueStyle}>{summary?.warning_count ?? 0}</div>
        </div>
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="recommendation-card-warnings">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>Warnings</div>
        {warnings.length === 0 ? (
          <div style={{ fontSize: '13px', color: '#6b7280' }}>无 warnings</div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {warnings.map((warning, index) => (
              <div
                key={`${warning}-${index}`}
                style={{
                  padding: '10px 12px',
                  borderRadius: '10px',
                  border: '1px solid #fde68a',
                  background: '#fffbeb',
                  color: '#92400e',
                  fontSize: '13px',
                }}
              >
                {warning}
              </div>
            ))}
          </div>
        )}
      </div>

      {errorMessage ? (
        <div
          style={{
            marginBottom: '16px',
            color: '#b91c1c',
            fontSize: '13px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            padding: '12px 14px',
            borderRadius: 10,
          }}
          data-testid="recommendation-card-error"
        >
          {errorMessage}
        </div>
      ) : null}

      {emptyState ? (
        <div
          style={{
            padding: '18px',
            borderRadius: '12px',
            border: '1px dashed #cbd5e1',
            background: '#f8fafc',
            color: '#475569',
            fontSize: '14px',
          }}
          data-testid="recommendation-card-empty"
        >
          当前数据库没有足够候选生成推荐。
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '12px' }} data-testid="recommendation-card-list">
          {recommendations.map(renderRecommendationItem)}
        </div>
      )}
    </section>
  )
}
