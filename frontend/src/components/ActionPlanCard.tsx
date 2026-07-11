import type {
  ActionPlanContactUsage,
  ActionPlanEvidence,
  ActionPlanStep,
  PartnershipActionPlanPayload,
} from '../types/partnershipActionPlan'

interface ActionPlanCardProps {
  payload: PartnershipActionPlanPayload
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

const renderUsesContact = (usesContact: ActionPlanContactUsage) => (
  <div style={snapshotCardStyle}>
    <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>uses_contact</div>
    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>type: {usesContact.type}</div>
      <div>value: {usesContact.type === 'none' ? 'none' : usesContact.value || 'N/A'}</div>
      <div>is_verified: {String(Boolean(usesContact.is_verified))}</div>
      <div>
        {usesContact.source_url ? (
          <a href={usesContact.source_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
            source_url: {usesContact.source_url}
          </a>
        ) : (
          <span style={{ color: '#64748b' }}>source_url: N/A</span>
        )}
      </div>
    </div>
  </div>
)

const renderEvidenceSnapshot = (evidence: ActionPlanEvidence) => (
  <div
    style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}
    data-testid="action-plan-card-evidence"
  >
    <div style={snapshotCardStyle}>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>score_snapshot</div>
      <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
        <div>people_score: {evidence.score_snapshot.people_score ?? 'N/A'}</div>
        <div>digital_score: {evidence.score_snapshot.digital_score ?? 'N/A'}</div>
        <div>intel_score: {evidence.score_snapshot.intel_score ?? 'N/A'}</div>
      </div>
    </div>

    <div style={snapshotCardStyle}>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>relationship_snapshot</div>
      <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
        <div>has_relationship_path: {String(Boolean(evidence.relationship_snapshot.has_relationship_path))}</div>
        <div>relationship_count: {evidence.relationship_snapshot.relationship_count}</div>
        <div>strongest_relationship_type: {evidence.relationship_snapshot.strongest_relationship_type || 'N/A'}</div>
        <div>
          relationship_path_summary:
          <div style={{ marginTop: '6px' }}>{renderListOrNone(evidence.relationship_snapshot.relationship_path_summary || [])}</div>
        </div>
      </div>
    </div>

    <div style={snapshotCardStyle}>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>contact_snapshot</div>
      <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
        <div>has_website: {String(Boolean(evidence.contact_snapshot.has_website))}</div>
        <div>has_email: {String(Boolean(evidence.contact_snapshot.has_email))}</div>
        <div>has_phone: {String(Boolean(evidence.contact_snapshot.has_phone))}</div>
        <div>has_social: {String(Boolean(evidence.contact_snapshot.has_social))}</div>
        <div>contact_count: {evidence.contact_snapshot.contact_count}</div>
        <div>verified_contact_count: {evidence.contact_snapshot.verified_contact_count}</div>
        <div>missing_source_count: {evidence.contact_snapshot.missing_source_count}</div>
      </div>
    </div>

    <div style={snapshotCardStyle}>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a', marginBottom: '8px' }}>recommendation_snapshot</div>
      <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
        <div>target_org_id: {evidence.recommendation_snapshot.target_org_id || 'N/A'}</div>
        <div>target_org_name: {evidence.recommendation_snapshot.target_org_name || 'N/A'}</div>
        <div>recommendation_score: {evidence.recommendation_snapshot.recommendation_score}</div>
        <div>priority: {evidence.recommendation_snapshot.priority}</div>
        <div>confidence: {evidence.recommendation_snapshot.confidence}</div>
        <div>recommended_next_action: {evidence.recommendation_snapshot.recommended_next_action}</div>
        <div>
          reason_codes:
          <div style={{ marginTop: '6px' }}>{renderListOrNone(evidence.recommendation_snapshot.reason_codes || [])}</div>
        </div>
        <div>
          risks:
          <div style={{ marginTop: '6px' }}>{renderListOrNone(evidence.recommendation_snapshot.risks || [])}</div>
        </div>
        <div>
          warnings:
          <div style={{ marginTop: '6px' }}>{renderListOrNone(evidence.recommendation_snapshot.warnings || [])}</div>
        </div>
      </div>
    </div>
  </div>
)

const renderActionPlanStep = (step: ActionPlanStep) => (
  <div
    key={`${step.step_number}-${step.title}`}
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
        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e3a8a' }}>
          {step.step_number}. {step.title}
        </div>
        <div style={{ fontSize: '13px', color: '#475569', marginTop: '4px' }}>{step.description}</div>
      </div>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <span style={chipStyle}>{step.action_type}</span>
        <span style={chipStyle}>{step.channel}</span>
        <span style={chipStyle}>priority {step.priority}</span>
      </div>
    </div>

    <div style={{ display: 'grid', gap: '6px', fontSize: '13px', color: '#334155' }}>
      <div>step_number: {step.step_number}</div>
      <div>action_type: {step.action_type}</div>
      <div>channel: {step.channel}</div>
      <div>priority: {step.priority}</div>
      <div>
        depends_on:
        <div style={{ marginTop: '6px' }}>{step.depends_on.length ? step.depends_on.join(', ') : 'none'}</div>
      </div>
    </div>

    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>required_evidence</div>
      {renderListOrNone(step.required_evidence || [])}
    </div>

    {renderUsesContact(step.uses_contact)}

    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>risk_flags</div>
      {renderListOrNone(step.risk_flags || [])}
    </div>

    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>success_criteria</div>
      {renderListOrNone(step.success_criteria || [])}
    </div>

    <div>
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>do_not_proceed_if</div>
      {renderListOrNone(step.do_not_proceed_if || [])}
    </div>
  </div>
)

export function ActionPlanCard({ payload, errorMessage = null }: ActionPlanCardProps) {
  const organization = payload.organization
  const targetOrg = payload.target_org
  const summary = payload.summary
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : []
  const actionPlan = Array.isArray(payload.action_plan) ? payload.action_plan : []
  const blocked = Boolean(summary?.blocked)
  const emptyState = !organization || payload.found === false || (!blocked && actionPlan.length === 0)

  return (
    <section style={shellStyle} data-testid="action-plan-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <div>
          <div style={{ fontSize: '16px', fontWeight: 800, color: '#111827', marginBottom: '4px' }}>合作行动计划</div>
          <div style={{ fontSize: '13px', color: '#6b7280' }}>仅展示后端规则化 action_plan payload，不做前端猜测或文本硬解析。</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span style={chipStyle}>steps {summary?.step_count ?? 0}</span>
          <span style={chipStyle}>blocked {String(Boolean(summary?.blocked))}</span>
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
          data-testid="action-plan-card-organization"
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
        data-testid="action-plan-card-summary"
      >
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>plan_available</div>
          <div style={valueStyle}>{String(Boolean(summary?.plan_available))}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>blocked</div>
          <div style={valueStyle}>{String(Boolean(summary?.blocked))}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>recommended_channel</div>
          <div style={valueStyle}>{summary?.recommended_channel || 'N/A'}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>risk_level</div>
          <div style={valueStyle}>{summary?.risk_level || 'N/A'}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>confidence</div>
          <div style={valueStyle}>{summary?.confidence ?? 0}</div>
        </div>
        <div style={snapshotCardStyle}>
          <div style={labelStyle}>step_count</div>
          <div style={valueStyle}>{summary?.step_count ?? 0}</div>
        </div>
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="action-plan-card-block-reasons">
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827', marginBottom: '8px' }}>block_reasons</div>
        {renderListOrNone(summary?.block_reasons || [])}
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="action-plan-card-warnings">
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
          data-testid="action-plan-card-error"
        >
          {errorMessage}
        </div>
      ) : null}

      {blocked ? (
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
          data-testid="action-plan-card-blocked"
        >
          当前数据库没有足够数据生成可执行行动计划。
        </div>
      ) : emptyState ? (
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
          data-testid="action-plan-card-empty"
        >
          当前数据库暂未返回可执行步骤。
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '12px', marginBottom: '16px' }} data-testid="action-plan-card-steps">
          {actionPlan.map(renderActionPlanStep)}
        </div>
      )}

      <div style={{ display: 'grid', gap: '12px' }}>
        <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827' }}>evidence snapshot</div>
        {renderEvidenceSnapshot(payload.evidence)}
      </div>
    </section>
  )
}
