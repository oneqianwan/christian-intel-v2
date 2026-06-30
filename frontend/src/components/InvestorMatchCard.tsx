import { useState } from 'react'

export interface ScoreDetail {
  label: string
  weight: string
  max: number
  got: number
  status: 'match' | 'partial' | 'miss' | 'neutral' | 'boost' | 'none'
  detail: string
}

export interface InvestorMatch {
  name: string
  name_en?: string
  type_label: string
  stage_focus?: string[]
  focus_areas?: string[]
  country?: string
  region_focus?: string[]
  website?: string
  score: number
  score_label: string
  match_reasons: string[]
  thesis?: string
  check_size?: string
  score_breakdown?: Record<string, ScoreDetail>
}

interface InvestorMatchCardProps {
  matches: InvestorMatch[]
  projectDescription?: string
  onCreateTask?: (investorName: string) => void
  onGenerateEmail?: (investorName: string) => void
}

export function InvestorMatchCard({
  matches,
  projectDescription,
  onCreateTask,
  onGenerateEmail,
}: InvestorMatchCardProps) {
  const [feedbackStatus, setFeedbackStatus] = useState<Record<string, string>>({})

  if (!matches.length) return null

  const getScoreColor = (status: ScoreDetail['status']) => {
    switch (status) {
      case 'match':
        return '#22c55e'
      case 'partial':
        return '#f59e0b'
      case 'miss':
        return '#d1d5db'
      case 'boost':
        return '#3b82f6'
      case 'neutral':
        return '#9ca3af'
      default:
        return '#d1d5db'
    }
  }

  const getScoreWidth = (got: number, max: number) => {
    if (!max) return '0%'
    const ratio = Math.max(0, Math.min(100, (got / max) * 100))
    return `${ratio}%`
  }

  const submitFeedback = async (type: string, investorName: string) => {
    try {
      const response = await fetch('http://localhost:8000/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-session-id': 'session-1' },
        body: JSON.stringify({
          feedback_type: type,
          related_investor: investorName,
          content: `用户对 ${investorName} 的匹配反馈: ${type}`,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      setFeedbackStatus((prev) => ({ ...prev, [investorName]: type === 'match_useful' ? '已记录为有用' : '已记录为没用' }))
    } catch (e) {
      console.error('Feedback failed:', e)
      setFeedbackStatus((prev) => ({ ...prev, [investorName]: '提交失败' }))
    }
  }

  return (
    <div style={{ display: 'grid', gap: '12px' }}>
      {projectDescription && (
        <div
          style={{
            background: '#fffbeb',
            border: '1px solid #fcd34d',
            borderRadius: '12px',
            padding: '12px 14px',
          }}
        >
          <div style={{ fontSize: '12px', color: '#d97706', fontWeight: 700, marginBottom: '4px' }}>项目画像</div>
          <div style={{ fontSize: '14px', color: '#78350f', lineHeight: 1.6 }}>{projectDescription}</div>
        </div>
      )}

      {matches.map((match, idx) => (
        <div
          key={`${match.name}-${idx}`}
          style={{
            borderRadius: '14px',
            border: '1px solid #e5e7eb',
            background: '#fff',
            padding: '16px',
            boxShadow: '0 6px 18px rgba(15, 23, 42, 0.06)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start', marginBottom: '10px' }}>
            <div>
              <div style={{ fontSize: '15px', fontWeight: 700, color: '#111827' }}>{match.name}</div>
              {match.name_en && <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>{match.name_en}</div>}
            </div>
            <span
              style={{
                padding: '4px 10px',
                borderRadius: '999px',
                fontSize: '12px',
                fontWeight: 700,
                background: match.score >= 7 ? '#dcfce7' : match.score >= 5 ? '#dbeafe' : '#f3f4f6',
                color: match.score >= 7 ? '#15803d' : match.score >= 5 ? '#1d4ed8' : '#4b5563',
                whiteSpace: 'nowrap',
              }}
            >
              {match.score_label} {match.score}/10
            </span>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '10px' }}>
            <span style={{ padding: '3px 8px', borderRadius: '8px', fontSize: '12px', background: '#f3f4f6', color: '#4b5563' }}>
              {match.type_label}
            </span>
            {match.country && (
              <span style={{ padding: '3px 8px', borderRadius: '8px', fontSize: '12px', background: '#f3f4f6', color: '#4b5563' }}>
                {match.country}
              </span>
            )}
            {match.check_size && match.check_size !== '未知' && (
              <span style={{ padding: '3px 8px', borderRadius: '8px', fontSize: '12px', background: '#f3f4f6', color: '#4b5563' }}>
                {match.check_size}
              </span>
            )}
          </div>

          {match.match_reasons.length > 0 && (
            <div style={{ fontSize: '12px', color: '#4b5563', marginBottom: '8px', lineHeight: 1.7 }}>
              <span style={{ fontWeight: 700 }}>匹配理由：</span>
              {match.match_reasons.join('；')}
            </div>
          )}

          {match.score_breakdown && (
            <div
              style={{
                marginTop: '10px',
                marginBottom: '10px',
                borderTop: '1px solid #f3f4f6',
                paddingTop: '10px',
                display: 'grid',
                gap: '8px',
              }}
            >
              <div style={{ fontSize: '10px', color: '#6b7280', fontWeight: 700 }}>匹配拆解</div>
              {Object.values(match.score_breakdown).map((item, idx) => (
                <div key={`${match.name}-score-${idx}`}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '10px', color: '#4b5563' }}>
                    <span>
                      {item.label} <span style={{ color: '#9ca3af' }}>({item.weight})</span>
                    </span>
                    <span>
                      {item.got}/{item.max}
                    </span>
                  </div>
                  <div
                    style={{
                      width: '100%',
                      background: '#f3f4f6',
                      borderRadius: '999px',
                      height: '6px',
                      marginTop: '4px',
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '6px',
                        borderRadius: '999px',
                        width: getScoreWidth(item.got, item.max),
                        background: getScoreColor(item.status),
                      }}
                    />
                  </div>
                  <div style={{ fontSize: '9px', color: '#9ca3af', marginTop: '4px', lineHeight: 1.5 }}>{item.detail}</div>
                </div>
              ))}
            </div>
          )}

          {match.stage_focus && match.stage_focus.length > 0 && (
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px' }}>
              阶段偏好：{match.stage_focus.join(' / ')}
            </div>
          )}

          {match.focus_areas && match.focus_areas.length > 0 && (
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px' }}>
              关注领域：{match.focus_areas.join(' / ')}
            </div>
          )}

          {match.thesis && (
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '12px', lineHeight: 1.6 }}>
              {match.thesis}
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginTop: '10px' }}>
            {match.website && (
              <a href={match.website} target="_blank" rel="noopener noreferrer" style={{ fontSize: '12px', color: '#4f46e5', textDecoration: 'none' }}>
                官网
              </a>
            )}
            {onCreateTask && (
              <button
                onClick={() => onCreateTask(match.name)}
                style={{ border: 'none', borderRadius: '8px', padding: '6px 10px', fontSize: '12px', background: '#f3f4f6', color: '#374151', cursor: 'pointer' }}
              >
                ➕ 跟踪任务
              </button>
            )}
            {onGenerateEmail && (
              <button
                onClick={() => onGenerateEmail(match.name)}
                style={{ border: 'none', borderRadius: '8px', padding: '6px 10px', fontSize: '12px', background: '#e0e7ff', color: '#4338ca', cursor: 'pointer' }}
              >
                ✉️ 生成邮件
              </button>
            )}
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              flexWrap: 'wrap',
              marginTop: '12px',
              paddingTop: '10px',
              borderTop: '1px solid #f3f4f6',
            }}
          >
            <span style={{ fontSize: '12px', color: '#9ca3af' }}>这个推荐有用吗？</span>
            <button
              onClick={() => submitFeedback('match_useful', match.name)}
              style={{
                border: 'none',
                borderRadius: '8px',
                padding: '4px 8px',
                fontSize: '12px',
                background: '#f0fdf4',
                color: '#16a34a',
                cursor: 'pointer',
              }}
            >
              👍 有用
            </button>
            <button
              onClick={() => submitFeedback('match_not_useful', match.name)}
              style={{
                border: 'none',
                borderRadius: '8px',
                padding: '4px 8px',
                fontSize: '12px',
                background: '#fef2f2',
                color: '#dc2626',
                cursor: 'pointer',
              }}
            >
              👎 没用
            </button>
            {feedbackStatus[match.name] && (
              <span style={{ fontSize: '12px', color: feedbackStatus[match.name] === '提交失败' ? '#dc2626' : '#6b7280' }}>
                {feedbackStatus[match.name]}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
