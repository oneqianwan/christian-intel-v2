interface GlobalIntelCardProps {
  title: string
  content: string
  sourceName: string
  sourceUrl: string
  publishedAt?: string
  confidence?: string
}

export function GlobalIntelCard({
  title,
  content,
  sourceName,
  sourceUrl,
  publishedAt,
  confidence,
}: GlobalIntelCardProps) {
  const confidenceStyle = confidence === 'HIGH'
    ? { background: '#dcfce7', color: '#166534' }
    : confidence === 'MEDIUM'
      ? { background: '#fef3c7', color: '#854d0e' }
      : { background: '#e5e7eb', color: '#4b5563' }

  return (
    <div style={{
      borderRadius: '12px',
      border: '1px solid #c7d2fe',
      background: 'linear-gradient(135deg, #eef2ff 0%, #ffffff 100%)',
      padding: '16px',
      boxShadow: '0 6px 16px rgba(79, 70, 229, 0.08)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
        <span style={{
          padding: '3px 10px',
          fontSize: '12px',
          fontWeight: 600,
          background: '#c7d2fe',
          color: '#4338ca',
          borderRadius: '999px',
        }}>
          全球
        </span>
        <span style={{ fontSize: '12px', color: '#6b7280' }}>{sourceName}</span>
      </div>

      <div style={{ fontSize: '16px', fontWeight: 700, color: '#111827', marginBottom: '8px', lineHeight: 1.4 }}>
        {title}
      </div>

      <div style={{
        fontSize: '14px',
        color: '#374151',
        lineHeight: 1.7,
        marginBottom: '12px',
        display: '-webkit-box',
        WebkitLineClamp: 4,
        WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {content}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', fontSize: '12px', color: '#6b7280', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {confidence && (
            <span style={{
              ...confidenceStyle,
              borderRadius: '999px',
              padding: '3px 8px',
              fontWeight: 600,
            }}>
              {confidence}
            </span>
          )}
          {publishedAt && <span>{publishedAt}</span>}
        </div>
        <a
          href={sourceUrl || '#'}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: '#4338ca', textDecoration: 'none', fontWeight: 600 }}
        >
          来源
        </a>
      </div>
    </div>
  )
}

export default GlobalIntelCard
