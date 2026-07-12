import type {
  ActionPlanEvidence,
  ContactEvidence,
  DecisionRationale,
  EvidenceBriefAudit,
  EvidenceSections,
  PartnershipEvidenceBriefPayload,
  RecommendationEvidence,
  RiskRegisterItem,
  ScoreEvidence,
  RelationshipEvidence,
} from '../types/partnershipEvidenceBrief'

interface EvidenceBriefCardProps {
  payload: PartnershipEvidenceBriefPayload
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

const renderRecommendedContact = (contact: ContactEvidence['recommended_contact']) => {
  if (!contact) {
    return <div style={{ fontSize: '13px', color: '#6b7280' }}>recommended_contact: none</div>
  }

  return (
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>recommended_contact.type: {contact.type}</div>
      <div>recommended_contact.value: {contact.type === 'none' ? 'none' : contact.value || 'N/A'}</div>
      <div>recommended_contact.is_verified: {String(Boolean(contact.is_verified))}</div>
      <div>
        {contact.source_url ? (
          <a href={contact.source_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
            recommended_contact.source_url: {contact.source_url}
          </a>
        ) : (
          <span style={{ color: '#64748b' }}>recommended_contact.source_url: N/A</span>
        )}
      </div>
    </div>
  )
}

const renderDecisionRationale = (decisionRationale: DecisionRationale) => (
  <div style={{ display: 'grid', gap: '12px' }} data-testid="evidence-brief-card-rationale">
    <div style={snapshotCardStyle}>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>headline</div>
      <div style={{ fontSize: '14px', color: '#0f172a', fontWeight: 600 }}>{decisionRationale.headline || 'N/A'}</div>
    </div>
    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>reason_codes</div>
      {renderListOrNone(decisionRationale.reason_codes || [])}
    </div>
    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>supporting_points</div>
      {renderListOrNone(decisionRationale.supporting_points || [])}
    </div>
    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>limiting_factors</div>
      {renderListOrNone(decisionRationale.limiting_factors || [])}
    </div>
  </div>
)

const renderScoreEvidence = (scoreEvidence: ScoreEvidence) => (
  <div style={snapshotCardStyle}>
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>score_evidence</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>people_score: {scoreEvidence.people_score ?? 'N/A'}</div>
      <div>digital_score: {scoreEvidence.digital_score ?? 'N/A'}</div>
      <div>intel_score: {scoreEvidence.intel_score ?? 'N/A'}</div>
      <div>
        strengths:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(scoreEvidence.strengths || [])}</div>
      </div>
      <div>
        weaknesses:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(scoreEvidence.weaknesses || [])}</div>
      </div>
      <div>
        warnings:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(scoreEvidence.warnings || [])}</div>
      </div>
    </div>
  </div>
)

const renderRelationshipEvidence = (relationshipEvidence: RelationshipEvidence) => (
  <div style={snapshotCardStyle}>
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>relationship_evidence</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>has_relationship_path: {String(Boolean(relationshipEvidence.has_relationship_path))}</div>
      <div>relationship_count: {relationshipEvidence.relationship_count}</div>
      <div>strongest_relationship_type: {relationshipEvidence.strongest_relationship_type || 'N/A'}</div>
      <div>
        relationship_path_summary:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(relationshipEvidence.relationship_path_summary || [])}</div>
      </div>
      <div>
        warnings:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(relationshipEvidence.warnings || [])}</div>
      </div>
    </div>
  </div>
)

const renderContactEvidence = (contactEvidence: ContactEvidence) => (
  <div style={snapshotCardStyle}>
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>contact_evidence</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>has_website: {String(Boolean(contactEvidence.has_website))}</div>
      <div>has_email: {String(Boolean(contactEvidence.has_email))}</div>
      <div>has_phone: {String(Boolean(contactEvidence.has_phone))}</div>
      <div>has_social: {String(Boolean(contactEvidence.has_social))}</div>
      <div>contact_count: {contactEvidence.contact_count}</div>
      <div>verified_contact_count: {contactEvidence.verified_contact_count}</div>
      <div>missing_source_count: {contactEvidence.missing_source_count}</div>
      <div>{renderRecommendedContact(contactEvidence.recommended_contact)}</div>
      <div>
        warnings:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(contactEvidence.warnings || [])}</div>
      </div>
    </div>
  </div>
)

const renderRecommendationEvidence = (recommendationEvidence: RecommendationEvidence) => (
  <div style={snapshotCardStyle}>
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>recommendation_evidence</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>recommendation_score: {recommendationEvidence.recommendation_score ?? 'N/A'}</div>
      <div>priority: {recommendationEvidence.priority || 'N/A'}</div>
      <div>confidence: {recommendationEvidence.confidence ?? 0}</div>
      <div>
        reason_codes:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(recommendationEvidence.reason_codes || [])}</div>
      </div>
      <div>
        risks:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(recommendationEvidence.risks || [])}</div>
      </div>
      <div>
        warnings:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(recommendationEvidence.warnings || [])}</div>
      </div>
    </div>
  </div>
)

const renderActionPlanEvidence = (actionPlanEvidence: ActionPlanEvidence) => (
  <div style={snapshotCardStyle}>
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>action_plan_evidence</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>plan_available: {String(Boolean(actionPlanEvidence.plan_available))}</div>
      <div>blocked: {String(Boolean(actionPlanEvidence.blocked))}</div>
      <div>step_count: {actionPlanEvidence.step_count}</div>
      <div>recommended_channel: {actionPlanEvidence.recommended_channel || 'N/A'}</div>
      <div>risk_level: {actionPlanEvidence.risk_level || 'N/A'}</div>
      <div>
        first_steps:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(actionPlanEvidence.first_steps || [])}</div>
      </div>
      <div>
        warnings:
        <div style={{ marginTop: '6px' }}>{renderListOrNone(actionPlanEvidence.warnings || [])}</div>
      </div>
    </div>
  </div>
)

const renderEvidenceSections = (evidenceSections: EvidenceSections) => (
  <div
    style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}
    data-testid="evidence-brief-card-evidence"
  >
    {renderScoreEvidence(evidenceSections.score_evidence)}
    {renderRelationshipEvidence(evidenceSections.relationship_evidence)}
    {renderContactEvidence(evidenceSections.contact_evidence)}
    {renderRecommendationEvidence(evidenceSections.recommendation_evidence)}
    {renderActionPlanEvidence(evidenceSections.action_plan_evidence)}
  </div>
)

const renderRiskRegisterItem = (item: RiskRegisterItem, index: number) => (
  <div
    key={`${item.risk_code}-${index}`}
    style={{
      padding: '12px',
      borderRadius: '10px',
      background: '#fff7ed',
      border: '1px solid #fed7aa',
      display: 'grid',
      gap: '6px',
      fontSize: '13px',
      color: '#9a3412',
    }}
  >
    <div>risk_code: {item.risk_code}</div>
    <div>severity: {item.severity}</div>
    <div>description: {item.description}</div>
    <div>mitigation: {item.mitigation}</div>
  </div>
)

const renderAudit = (audit: EvidenceBriefAudit) => (
  <div style={{ display: 'grid', gap: '12px' }} data-testid="evidence-brief-card-audit">
    <div style={snapshotCardStyle}>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>audit</div>
      <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
        <div>generated_by: {audit.generated_by}</div>
        <div>no_llm: {String(Boolean(audit.no_llm))}</div>
      </div>
    </div>
    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>source_modules</div>
      {renderListOrNone(audit.source_modules || [])}
    </div>
    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>missing_modules</div>
      {renderListOrNone(audit.missing_modules || [])}
    </div>
  </div>
)

export function EvidenceBriefCard({ payload, errorMessage = null }: EvidenceBriefCardProps) {
  const organization = payload.organization
  const targetOrg = payload.target_org
  const summary = payload.summary
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : []
  const riskRegister = Array.isArray(payload.risk_register) ? payload.risk_register : []
  const recommendedNextActions = Array.isArray(payload.recommended_next_actions) ? payload.recommended_next_actions : []
  const doNotProceedIf = Array.isArray(payload.do_not_proceed_if) ? payload.do_not_proceed_if : []
  const briefUnavailable = !summary?.brief_available
  const emptyState = !organization || payload.found === false || briefUnavailable

  return (
    <section style={shellStyle} data-testid="evidence-brief-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <div>
          <div style={{ fontSize: '16px', fontWeight: 800, color: '#111827', marginBottom: '4px' }}>合作证据简报</div>
          <div style={{ fontSize: '13px', color: '#6b7280' }}>仅展示后端规则化 evidence_brief payload，不做前端猜测或文本硬解析。</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span style={chipStyle}>decision {summary?.decision || 'N/A'}</span>
          <span style={chipStyle}>priority {summary?.priority || 'N/A'}</span>
          <span style={chipStyle}>risk {summary?.risk_level || 'N/A'}</span>
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
          data-testid="evidence-brief-card-organization"
        >
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={labelStyle}>当前机构</div>
            <div style={{ ...valueStyle, fontSize: '18px' }}>{organization.name}</div>
          </div>
          <div>
            <div style={labelStyle}>目标机构</div>
            <div style={valueStyle}>{targetOrg?.name || 'N/A'}</div>
          </div>
          <div>
            <div style={labelStyle}>机构来源名称</div>
            <div style={valueStyle}>{organization.source_name || 'N/A'}</div>
          </div>
          <div>
            <div style={labelStyle}>机构来源链接</div>
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
        data-testid="evidence-brief-card-summary"
      >
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>brief_available</div>
          <div style={valueStyle}>{String(Boolean(summary?.brief_available))}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>decision</div>
          <div style={valueStyle}>{summary?.decision || 'N/A'}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>priority</div>
          <div style={valueStyle}>{summary?.priority || 'N/A'}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>confidence</div>
          <div style={valueStyle}>{summary?.confidence ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>risk_level</div>
          <div style={valueStyle}>{summary?.risk_level || 'N/A'}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>evidence_count</div>
          <div style={valueStyle}>{summary?.evidence_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>missing_evidence_count</div>
          <div style={valueStyle}>{summary?.missing_evidence_count ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>recommended_channel</div>
          <div style={valueStyle}>{summary?.recommended_channel || 'N/A'}</div>
        </div>
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
          data-testid="evidence-brief-card-error"
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
            marginBottom: '16px',
          }}
          data-testid="evidence-brief-card-empty"
        >
          当前数据库没有足够证据生成合作证据简报。
        </div>
      ) : null}

      <div style={{ marginBottom: '16px' }}>
        {renderDecisionRationale(payload.decision_rationale)}
      </div>

      <div style={{ marginBottom: '16px' }}>
        {renderEvidenceSections(payload.evidence_sections)}
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="evidence-brief-card-risk-register">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>risk_register</div>
        {riskRegister.length === 0 ? (
          <div style={{ fontSize: '13px', color: '#6b7280' }}>none</div>
        ) : (
          <div style={{ display: 'grid', gap: '10px' }}>
            {riskRegister.map(renderRiskRegisterItem)}
          </div>
        )}
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="evidence-brief-card-recommended-actions">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>recommended_next_actions</div>
        {renderListOrNone(recommendedNextActions)}
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="evidence-brief-card-do-not-proceed">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>do_not_proceed_if</div>
        {renderListOrNone(doNotProceedIf)}
      </div>

      <div style={{ marginBottom: '16px' }}>
        {renderAudit(payload.audit)}
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="evidence-brief-card-warnings">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>warnings</div>
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
    </section>
  )
}
