import type { ContactPayload, ContactPoint } from '../types/contactIntelligence'

interface ContactCardProps {
  payload: ContactPayload
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

const formatWarning = (warning: string) => {
  if (warning === 'field_level_source_missing') {
    return '字段级来源缺失'
  }
  if (warning === 'contact_missing') {
    return '当前数据库没有记录公开联系方式'
  }
  return warning
}

const getContactDisplayLabel = (contact: ContactPoint) => {
  if (contact.type !== 'social_profile') {
    return contact.label || contact.type
  }
  const platform = String(contact.platform || '').trim().toLowerCase()
  const platformMap: Record<string, string> = {
    facebook: 'Facebook',
    youtube: 'YouTube',
    telegram: 'Telegram',
    twitter: 'Twitter',
    linkedin: 'LinkedIn',
    instagram: 'Instagram',
    whatsapp: 'WhatsApp',
    tiktok: 'TikTok',
  }
  return platformMap[platform] || contact.label || contact.platform || 'Social'
}

const getDisplayValue = (contact: ContactPoint) => contact.normalized_value || contact.value || 'N/A'

export function ContactCard({ payload }: ContactCardProps) {
  const organization = payload.organization
  const contacts = Array.isArray(payload.contacts) ? payload.contacts : []
  const warnings = Array.isArray(payload.warnings) ? payload.warnings : []
  const summary = payload.summary
  const emptyState = !organization || payload.found === false || contacts.length === 0

  return (
    <section style={shellStyle} data-testid="contact-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '16px' }}>
        <div>
          <div style={{ fontSize: '16px', fontWeight: 800, color: '#111827', marginBottom: '4px' }}>公开联系方式</div>
          <div style={{ fontSize: '13px', color: '#6b7280' }}>仅展示数据库记录，不做前端猜测或文本硬解析。</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span style={chipStyle}>contacts {summary?.contact_count ?? 0}</span>
          <span style={chipStyle}>verified {summary?.verified_count ?? 0}</span>
          <span style={chipStyle}>missing_source {summary?.missing_source_count ?? 0}</span>
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
          data-testid="contact-card-organization"
        >
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={labelStyle}>机构名称</div>
            <div style={{ ...valueStyle, fontSize: '18px' }}>{organization.name}</div>
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
            <div style={labelStyle}>组织级置信度</div>
            <div style={valueStyle}>{organization.organization_confidence ?? 'N/A'}</div>
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
        data-testid="contact-card-summary"
      >
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>官网数量</div>
          <div style={valueStyle}>{summary?.website_count ?? 0}</div>
        </div>
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>邮箱数量</div>
          <div style={valueStyle}>{summary?.email_count ?? 0}</div>
        </div>
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>电话数量</div>
          <div style={valueStyle}>{summary?.phone_count ?? 0}</div>
        </div>
        <div style={{ padding: '12px', borderRadius: '12px', background: '#f8fafc', border: '1px solid #e2e8f0' }}>
          <div style={labelStyle}>社媒数量</div>
          <div style={valueStyle}>{summary?.social_count ?? 0}</div>
        </div>
      </div>

      <div style={{ marginBottom: '16px' }} data-testid="contact-card-warnings">
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
                {formatWarning(warning)}
              </div>
            ))}
          </div>
        )}
      </div>

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
          data-testid="contact-card-empty"
        >
          当前数据库没有记录这个机构的公开联系方式。
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '12px' }} data-testid="contact-card-contacts">
          {contacts.map((contact) => (
            <div
              key={contact.id}
              style={{
                padding: '14px',
                borderRadius: '12px',
                border: '1px solid #dbeafe',
                background: '#f8fbff',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '8px' }}>
                <div style={{ fontSize: '15px', fontWeight: 700, color: '#1e3a8a' }}>{getContactDisplayLabel(contact)}</div>
                <span style={chipStyle}>{contact.type}</span>
              </div>
              <div style={{ fontSize: '14px', color: '#111827', fontWeight: 600, marginBottom: '8px' }}>{getDisplayValue(contact)}</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px', fontSize: '13px', color: '#334155' }}>
                <div>verification_status: {contact.verification_status || 'unverified'}</div>
                <div>is_verified: {String(Boolean(contact.is_verified))}</div>
                <div>confidence: {contact.confidence ?? 'N/A'}</div>
                <div>usage: {contact.usage || 'N/A'}</div>
                <div>source_name: {contact.source_name || 'N/A'}</div>
              </div>
              <div style={{ marginTop: '8px', fontSize: '13px' }}>
                {contact.source_url ? (
                  <a href={contact.source_url} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
                    source_url: {contact.source_url}
                  </a>
                ) : (
                  <span style={{ color: '#64748b' }}>source_url: N/A</span>
                )}
              </div>
              <div style={{ marginTop: '8px', display: 'grid', gap: '6px' }}>
                {(contact.warnings || []).length === 0 ? (
                  <div style={{ fontSize: '13px', color: '#6b7280' }}>contact_warnings: none</div>
                ) : (
                  contact.warnings.map((warning, index) => (
                    <div
                      key={`${contact.id}-${warning}-${index}`}
                      style={{
                        fontSize: '13px',
                        color: '#92400e',
                        background: '#fffbeb',
                        border: '1px solid #fde68a',
                        borderRadius: '8px',
                        padding: '8px 10px',
                      }}
                    >
                      {formatWarning(warning)}
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
