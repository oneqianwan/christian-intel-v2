import { useState } from 'react'

interface OntologyFilterProps {
  onFilter: (filterType: string, filterValue: string) => void
  disabled?: boolean
}

const ORG_TYPES = [
  { code: 'church_network', label: '教会网络' },
  { code: 'faithtech_startup', label: 'FaithTech' },
  { code: 'seminary', label: '神学院' },
  { code: 'mission_agency', label: '宣教机构' },
  { code: 'media_outlet', label: '基督教媒体' },
  { code: 'relief_org', label: '救援机构' },
]

const THEO_POSITIONS = [
  { code: 'charismatic', label: '灵恩派' },
  { code: 'evangelical', label: '福音派' },
  { code: 'pentecostal', label: '五旬节派' },
  { code: 'catholic', label: '天主教' },
  { code: 'interdenominational', label: '跨宗派' },
]

const INVESTOR_TYPES = [
  { code: 'faithtech_global', label: '🏦 投FaithTech的' },
  { code: 'foundation_global', label: '🏛️ 基督教基金会' },
  { code: 'southeast_asia', label: '🌏 东南亚投资方' },
  { code: 'match_me', label: '🔍 匹配我的项目' },
]

export function OntologyFilter({ onFilter, disabled }: OntologyFilterProps) {
  const [expanded, setExpanded] = useState(false)
  const [activeTag, setActiveTag] = useState<string | null>(null)

  const handleClick = (type: string, code: string) => {
    if (disabled) return
    const key = `${type}:${code}`
    if (activeTag === key) {
      setActiveTag(null)
    } else {
      setActiveTag(key)
      onFilter(type, code)
    }
  }

  return (
    <div style={{ background: 'transparent' }}>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0',
          fontSize: '12px',
          color: '#6b7280',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '14px' }}>⚡</span>
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#111827' }}>
              {expanded ? '收起快速筛选' : '快速筛选'}
            </div>
            <div style={{ fontSize: '11px', color: '#6b7280' }}>
              一键触发常用机构、教派和投资方问法
            </div>
          </div>
        </div>
        <span
          style={{
            width: '24px',
            height: '24px',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '999px',
            background: '#f3f4f6',
            color: '#6b7280',
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s ease',
            flexShrink: 0,
          }}
        >
          ▼
        </span>
      </button>

      {expanded && (
        <div
          style={{
            marginTop: '12px',
            padding: '12px',
            display: 'grid',
            gap: '10px',
            borderRadius: '14px',
            border: '1px solid #e5e7eb',
            background: '#f9fafb',
          }}
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontSize: '10px', color: '#9ca3af', marginRight: '4px', alignSelf: 'center', fontWeight: 700 }}>机构</span>
            {ORG_TYPES.map((item) => (
              <button
                key={item.code}
                type="button"
                disabled={disabled}
                onClick={() => handleClick('organization_type', item.code)}
                style={{
                  padding: '5px 10px',
                  fontSize: '11px',
                  borderRadius: '999px',
                  border: activeTag === `organization_type:${item.code}` ? '1px solid #111827' : '1px solid #d1d5db',
                  background: activeTag === `organization_type:${item.code}` ? '#111827' : '#fff',
                  color: activeTag === `organization_type:${item.code}` ? '#fff' : '#4b5563',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  opacity: disabled ? 0.55 : 1,
                  fontWeight: 600,
                }}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontSize: '10px', color: '#9ca3af', marginRight: '4px', alignSelf: 'center', fontWeight: 700 }}>教派</span>
            {THEO_POSITIONS.map((item) => (
              <button
                key={item.code}
                type="button"
                disabled={disabled}
                onClick={() => handleClick('theological_position', item.code)}
                style={{
                  padding: '5px 10px',
                  fontSize: '11px',
                  borderRadius: '999px',
                  border: activeTag === `theological_position:${item.code}` ? '1px solid #111827' : '1px solid #d1d5db',
                  background: activeTag === `theological_position:${item.code}` ? '#111827' : '#fff',
                  color: activeTag === `theological_position:${item.code}` ? '#fff' : '#4b5563',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  opacity: disabled ? 0.55 : 1,
                  fontWeight: 600,
                }}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            <span style={{ fontSize: '10px', color: '#9ca3af', marginRight: '4px', alignSelf: 'center', fontWeight: 700 }}>投资方</span>
            {INVESTOR_TYPES.map((item) => (
              <button
                key={item.code}
                type="button"
                disabled={disabled}
                onClick={() => handleClick('investor_query', item.code)}
                style={{
                  padding: '5px 10px',
                  fontSize: '11px',
                  borderRadius: '999px',
                  border: activeTag === `investor_query:${item.code}` ? '1px solid #d97706' : '1px solid #fcd34d',
                  background: activeTag === `investor_query:${item.code}` ? '#d97706' : '#fffbeb',
                  color: activeTag === `investor_query:${item.code}` ? '#fff' : '#b45309',
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  opacity: disabled ? 0.55 : 1,
                  fontWeight: 600,
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
