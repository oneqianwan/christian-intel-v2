import { useState, useRef, useEffect } from 'react'
import { useConversationStore } from '../stores/conversationStore'
import { useMessageStore } from '../stores/messageStore'
import { sendChatStream, fetchMessages, createConversation } from '../services/api'
import GlobalIntelCard from './GlobalIntelCard'
import AgentAlerts from './AgentAlerts'
import { CollectionPanel } from './CollectionPanel'
import { OntologyFilter } from './OntologyFilter'
import { InvestorMatchCard, type InvestorMatch } from './InvestorMatchCard'
import { TaskPanel } from './TaskPanel'
import { IntelGraph } from './IntelGraph'

type ChatAreaProps = {
  showSettings: boolean
  onToggleSettings: () => void
}

type SearchResult = {
  id: string
  title: string
  source: string
  country: string | null
  published_at: string | null
}

type BriefItem = {
  title: string
  source?: string
  publishedAt?: string
  url?: string
}

type IntelTag = {
  type: string
  text: string
}

type MatchPayload = {
  project_description?: string
  matches: InvestorMatch[]
}

type GraphPayload = {
  center_entity: string
  relations: Array<{
    entity: { name: string; type?: string }
    type: string
    direction?: string
    amount?: number
    description?: string
  }>
}

const TOOL_LABELS: Record<string, string> = {
  query_ontology: '机构分类与教会网络',
  query_organization_profile: '机构画像',
  query_graph: '关系图谱',
  query_fused: '融合情报分析',
  query_intelligence: '近期动态检索',
  query_database: '数据库检索',
  query_arda_country: '国家宗教基线',
  query_investors: '投资方检索',
  query_funding_rounds: '融资记录检索',
  match_investors: '投资方匹配',
  match_users: '潜在用户匹配',
  match_acquirers: '潜在收购方匹配',
  generate_outreach_email: '邮件草拟',
  create_task: '任务创建',
  get_agent_status: '后台采集状态',
}

const stripBracketMetaTag = (content: string, keyword: string): string => {
  const pattern = new RegExp(`\\[[^\\]]*${keyword}:\\s*[^\\]]+\\]\\s*`, 'gi')
  return content.replace(pattern, '')
}

const extractMetaPayload = <T,>(content: string, tagName: string): T | null => {
  const pattern = new RegExp(`\\[\\[${tagName}\\]\\]([\\s\\S]*?)\\[\\[\\/${tagName}\\]\\]`)
  const matched = content.match(pattern)
  if (!matched?.[1]) return null
  try {
    return JSON.parse(matched[1]) as T
  } catch {
    return null
  }
}

const stripMetaBlocks = (content: string): string =>
  content
    .replace(/\[\[MATCH_DATA\]\][\s\S]*?\[\[\/MATCH_DATA\]\]/g, '')
    .replace(/\[\[EMAIL_DATA\]\][\s\S]*?\[\[\/EMAIL_DATA\]\]/g, '')
    .replace(/\[\[GRAPH_DATA\]\][\s\S]*?\[\[\/GRAPH_DATA\]\]/g, '')
    .replace(/\[\[EXECUTIVE_REPORT\]\]/g, '')
    .trim()

const filterDSML = (content: string): string => {
  if (!content) return ''

  let filtered = content.replace(/<｜｜DSML｜｜tool_calls>[\s\S]*?<｜｜DSML｜｜\/tool_calls>/g, '')
  filtered = filtered.replace(/<｜｜DSML｜｜invoke[\s\S]*?<｜｜DSML｜｜\/invoke>/g, '')
  filtered = filtered.replace(/<｜｜DSML｜｜parameter[^>]*>[\s\S]*?<｜｜DSML｜｜\/parameter>/g, '')
  filtered = filtered.replace(/<｜｜DSML｜｜[^>]*>/g, '')
  filtered = filtered.replace(/<｜｜DSML｜｜\/[^>]*>/g, '')
  filtered = filtered.replace(/\n{3,}/g, '\n\n').trim()

  return filtered
}

const humanizeToolName = (toolName: string | null | undefined): string => {
  if (!toolName) return '查询中'
  return TOOL_LABELS[toolName] || toolName.replace(/_/g, ' ')
}

const sanitizeExecutiveEvidenceLine = (line: string): string => {
  const toolMatch = line.match(/^\s*-\s*\[([a-zA-Z0-9_]+)\]/)
  if (toolMatch) {
    const toolName = toolMatch[1]
    const confidenceMatch = line.match(/\(confidence:\s*(\d+)\)/i)
    const confidenceText = confidenceMatch ? `（内部置信度 ${confidenceMatch[1]}）` : ''
    return `- 已执行：${humanizeToolName(toolName)}${confidenceText}`
  }

  if (/^\s*-\s*\{.+\}\s*$/.test(line) || /'status':|'confidence':|'query_summary':/.test(line)) {
    return ''
  }

  if (/^\s*-\s*\[[^\]]+\]/.test(line) && line.includes('{')) {
    const fallbackTool = line.match(/^\s*-\s*\[([^\]]+)\]/)?.[1] || '查询'
    return `- 已执行：${humanizeToolName(fallbackTool)}`
  }

  if (/^\s*-\s*$/.test(line)) {
    return line
  }

  return line
}

const getDisplayContent = (content: string): string => {
  if (!content) return ''

  let cleaned = filterDSML(stripMetaBlocks(content))
  const lines = cleaned.split('\n')
  let inEvidenceSection = false

  const normalizedLines = lines
    .map((rawLine) => {
      const line = rawLine.trimEnd()
      if (/^###\s+Evidence$/i.test(line)) {
        inEvidenceSection = true
        return '### 分析依据'
      }
      if (/^###\s+Summary$/i.test(line)) return '### 分析结论'
      if (/^###\s+Key Findings$/i.test(line)) return '### 核心发现'
      if (/^###\s+Risk Assessment$/i.test(line)) return '### 风险提示'
      if (/^###\s+Recommendation$/i.test(line)) return '### 建议行动'
      if (/^###\s+Next Steps$/i.test(line)) return '### 下一步'
      if (/^##\s+Executive Report$/i.test(line)) return '## 分析结果'
      if (/^###\s+Confidence Score:/i.test(line)) {
        return line.replace(/^###\s+Confidence Score:/i, '### 置信度：')
      }
      if (/^针对「.+」的情报分析已完成，共执行\d+个子任务。$/.test(line)) {
        return line
          .replace(/^针对「(.+)」的情报分析已完成，共执行(\d+)个子任务。$/, '已完成「$1」分析，并核查 $2 个信息维度。')
      }
      if (/^基于\d+条证据的综合评估$/.test(line)) {
        return line.replace(/^基于(\d+)条证据的综合评估$/, '基于 $1 条内部证据的综合判断。')
      }

      if (/^###\s+/.test(line) && !/^###\s+分析依据$/.test(line)) {
        inEvidenceSection = false
      }

      if (/^Generated by Christian Intelligence Officer/i.test(line)) return ''
      if (/^Data sources:/i.test(line)) return ''

      if (inEvidenceSection) {
        return sanitizeExecutiveEvidenceLine(line)
      }
      return line
    })
    .join('\n')

  cleaned = normalizedLines
    .replace(/\[[^\]]*INSUFFICIENT DATA[^\]]*\]\s*/gi, '')
  cleaned = stripBracketMetaTag(cleaned, 'SOURCE')
  cleaned = stripBracketMetaTag(cleaned, 'CONFIDENCE')
  cleaned = cleaned
    .replace(/\n{3,}/g, '\n\n')
    .trim()

  return cleaned
}

const parseBriefItems = (content: string): BriefItem[] => {
  const lines = content.split('\n')
  const items: BriefItem[] = []
  let current: BriefItem | null = null

  for (const rawLine of lines) {
    const line = rawLine.trim()
    const titleMatch = line.match(/^(?:🔴|🟡|🟢)\s+\*\*\d+\.\s+(.+?)\*\*\s+\(评分:\s*([^)]+)\)/)
    if (titleMatch) {
      if (current) items.push(current)
      current = { title: titleMatch[1] }
      continue
    }

    if (!current) continue

    const sourceMatch = line.match(/^- 来源：(.+)$/)
    if (sourceMatch) {
      current.source = sourceMatch[1]
      continue
    }

    const timeMatch = line.match(/^- 时间：(.+)$/)
    if (timeMatch) {
      current.publishedAt = timeMatch[1]
      continue
    }

    const linkMatch = line.match(/^- \[查看原文\]\((.+)\)$/)
    if (linkMatch) {
      current.url = linkMatch[1]
    }
  }

  if (current) items.push(current)
  return items
}

const escapeHtml = (value: string): string =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const renderInlineMarkdown = (value: string): string => {
  let html = escapeHtml(value)
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  return html
}

const parseTableRow = (line: string): string[] =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())

const isTableSeparator = (line: string): boolean =>
  /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line.trim())

const renderMarkdown = (content: string): string => {
  const cleanContent = getDisplayContent(content)
  const lines = cleanContent.split('\n')
  const html: string[] = []
  let inList = false
  let inOrderedList = false

  const closeList = () => {
    if (inList) {
      html.push('</ul>')
      inList = false
    }
    if (inOrderedList) {
      html.push('</ol>')
      inOrderedList = false
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim()

    if (!line) {
      closeList()
      continue
    }

    if (/^---+$/.test(line)) {
      closeList()
      html.push('<hr />')
      continue
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.+)$/)
    if (headingMatch) {
      closeList()
      const level = headingMatch[1].length
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`)
      continue
    }

    const bulletMatch = line.match(/^[-*]\s+(.+)$/)
    if (bulletMatch) {
      if (!inList) {
        if (inOrderedList) {
          html.push('</ol>')
          inOrderedList = false
        }
        html.push('<ul>')
        inList = true
      }
      html.push(`<li>${renderInlineMarkdown(bulletMatch[1])}</li>`)
      continue
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/)
    if (orderedMatch) {
      if (!inOrderedList) {
        if (inList) {
          html.push('</ul>')
          inList = false
        }
        html.push('<ol>')
        inOrderedList = true
      }
      html.push(`<li>${renderInlineMarkdown(orderedMatch[1])}</li>`)
      continue
    }

    const nextLine = lines[index + 1]?.trim()
    if (line.includes('|') && nextLine && isTableSeparator(nextLine)) {
      closeList()
      const headerCells = parseTableRow(line)
      const tableRows: string[][] = []
      index += 2
      while (index < lines.length) {
        const rowLine = lines[index].trim()
        if (!rowLine || !rowLine.includes('|')) {
          index -= 1
          break
        }
        tableRows.push(parseTableRow(rowLine))
        index += 1
      }

      const thead = `<thead><tr>${headerCells.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join('')}</tr></thead>`
      const tbody = `<tbody>${tableRows
        .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
      html.push(`<div class="markdown-table-wrap"><table class="markdown-table">${thead}${tbody}</table></div>`)
      continue
    }

    closeList()
    html.push(`<p>${renderInlineMarkdown(line)}</p>`)
  }

  closeList()
  return html.join('')
}

const extractSection = (content: string, section: string): string => {
  const cleanContent = getDisplayContent(content)
  const lines = cleanContent.split('\n')
  let result = ''
  let inSection = false

  for (const line of lines) {
    if (line.includes(section)) {
      inSection = true
      result += `${line}\n`
      continue
    }

    if (inSection) {
      if (line.startsWith('#') || line.startsWith('###') || (line.startsWith('**') && !line.includes(section))) {
        break
      }
      result += `${line}\n`
    }
  }

  return result.trim()
}

const stripMarkdown = (value: string): string =>
  getDisplayContent(value)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^#+\s+/gm, '')
    .trim()

const extractTags = (content: string, sourcesCount: number, deliveryType?: string): IntelTag[] => {
  const tags: IntelTag[] = []
  const cleanContent = filterDSML(stripMetaBlocks(content))
  const sourceMatches = cleanContent.match(/\[SOURCE:\s*([^\]]+)\]/g)
  const sourceTotal = sourceMatches?.length || sourcesCount
  if (sourceTotal > 0) {
    tags.push({ type: 'source', text: `📎 ${sourceTotal}个来源` })
  }

  const confMatches = cleanContent.match(/\[CONFIDENCE:\s*([A-Z]+)\]/g)
  if (confMatches) {
    const levels = Array.from(new Set(
      confMatches
        .map((match) => match.match(/\[CONFIDENCE:\s*([A-Z]+)\]/)?.[1])
        .filter((level): level is string => Boolean(level))
    ))

    levels.forEach((level) => {
      const color = level === 'HIGH' ? 'high' : level === 'MEDIUM' ? 'medium' : 'low'
      tags.push({ type: `confidence-${color}`, text: `🔍 ${level}` })
    })
  }

  if (cleanContent.includes('建议行动')) {
    tags.push({ type: 'action', text: '⚡ 有建议行动' })
  }

  if (deliveryType === 'contact_partial') {
    tags.push({ type: 'completeness-partial', text: '⚠️ PARTIAL' })
  }

  return tags
}

function ChatArea({ showSettings, onToggleSettings }: ChatAreaProps) {
  const contentShellStyle = {
    width: '100%',
    maxWidth: '1180px',
    margin: '0 auto',
  } as const

  const assistantLogoSrc = '/logo-tight-b.png'
  const { currentId, addConversation } = useConversationStore()
  const { addMessage, getMessages } = useMessageStore()
  const [input, setInput] = useState('')
  const [lastQuery, setLastQuery] = useState('')
  const [bookmarkedItems, setBookmarkedItems] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [isThinking, setIsThinking] = useState(false)
  const [currentTool, setCurrentTool] = useState<string | null>(null)
  const [streamingContent, setStreamingContent] = useState('')
  const [taskRefreshToken, setTaskRefreshToken] = useState(0)
  const [userScrolled, setUserScrolled] = useState(false)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const prevMessageCountRef = useRef(0)
  const forceScrollRef = useRef(false)
  const userScrolledRef = useRef(false)
  const streamContentRef = useRef('')
  const abortControllerRef = useRef<AbortController | null>(null)

  const messages = currentId ? getMessages(currentId) : []

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior })
  }

  const renderAssistantAvatar = (
    frameSize = 58,
    imageSize = 54,
    background = '#eef2ff'
  ) => (
    <div
      style={{
        width: `${frameSize}px`,
        height: `${frameSize}px`,
        borderRadius: '999px',
        background,
        border: '1px solid #93c5fd',
        boxShadow: '0 0 0 3px rgba(219, 234, 254, 0.98), 0 12px 24px rgba(59, 130, 246, 0.2)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      <img
        src={assistantLogoSrc}
        alt="情报官"
        style={{ width: `${imageSize}px`, height: `${imageSize}px`, objectFit: 'contain' }}
      />
    </div>
  )

  const renderIntelContent = (content: string, sourcesCount: number, deliveryType?: string) => {
    const visibleContent = getDisplayContent(content)
    const conclusion = extractSection(visibleContent, '核心结论')
    const tags = extractTags(content, sourcesCount, deliveryType)
    const isPartialContact = deliveryType === 'contact_partial'

    return (
      <div className="intel-brief-card">
        {isPartialContact && (
          <div className="intel-warning-banner">
            ⚠️ 信息不完整：当前仅确认公共联系渠道，未找到公开负责人姓名。
          </div>
        )}
        {conclusion && (
          <div
            className="intel-conclusion"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(conclusion) }}
          />
        )}
        <div
          className="markdown-body"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(visibleContent) }}
        />
        {tags.length > 0 && (
          <div className="intel-tags">
            {tags.map((tag, index) => (
              <span key={`${tag.type}-${index}`} className={`intel-tag ${tag.type}`}>
                {tag.text}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  const renderGlobalContent = (msg: { content: string; sources: { name: string; url: string }[]; delivery_type?: string }) => {
    const visibleContent = getDisplayContent(msg.content)
    const conclusion = stripMarkdown(extractSection(visibleContent, '核心结论'))
    const summary = conclusion || stripMarkdown(visibleContent).slice(0, 220)
    const firstLine = stripMarkdown(visibleContent).split('\n').find((line) => line.trim()) || '全球情报简报'
    const firstSource = msg.sources[0] || { name: '全球来源', url: '' }
    const confidence = visibleContent.match(/\[CONFIDENCE:\s*([A-Z]+)\]/)?.[1]
    const publishedAt = visibleContent.match(/(\d{4}-\d{2}-\d{2})/)?.[1]

    return (
      <div style={{ display: 'grid', gap: '12px' }}>
        <GlobalIntelCard
          title={firstLine}
          content={summary}
          sourceName={firstSource.name || '全球来源'}
          sourceUrl={firstSource.url || '#'}
          publishedAt={publishedAt}
          confidence={confidence}
        />
        <div
          className="markdown-body"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(visibleContent) }}
        />
      </div>
    )
  }

  const handleCreateInvestorTask = async (investorName: string) => {
    try {
      const res = await fetch('http://localhost:8000/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: `联系 ${investorName}`,
          description: `通过投资方匹配推荐，需跟进联系 ${investorName}`,
          priority: 'high',
        }),
      })
      const data = await res.json()

      if (data.status === 'created') {
        setTaskRefreshToken((prev) => prev + 1)
        if (currentId) {
          addMessage(currentId, {
            id: `investor-task-${Date.now()}`,
            role: 'assistant' as const,
            content: `✅ 任务已创建：联系 ${investorName}`,
            sources: [],
            delivery_type: 'status_update',
            status: 'completed',
          })
          forceScrollRef.current = true
        }
        window.alert(`✅ 任务已创建：联系 ${investorName}`)
        return
      }

      window.alert('创建任务失败')
    } catch (e) {
      console.error('Create task failed:', e)
      window.alert('创建任务失败')
    }
  }

  const renderFeedbackCard = (
    title: string,
    description: string,
    tone: 'info' | 'warning' | 'success' | 'error' = 'info'
  ) => {
    const palette = {
      info: { bg: '#eff6ff', border: '#bfdbfe', title: '#1d4ed8', text: '#1e3a8a' },
      warning: { bg: '#fff7ed', border: '#fdba74', title: '#c2410c', text: '#9a3412' },
      success: { bg: '#ecfdf5', border: '#86efac', title: '#047857', text: '#166534' },
      error: { bg: '#fef2f2', border: '#fecaca', title: '#b91c1c', text: '#7f1d1d' },
    }[tone]

    return (
      <div
        style={{
          background: palette.bg,
          border: `1px solid ${palette.border}`,
          borderRadius: '12px',
          padding: '14px 16px',
        }}
      >
        <div style={{ fontSize: '13px', fontWeight: 800, color: palette.title, marginBottom: '6px' }}>{title}</div>
        <div style={{ fontSize: '14px', lineHeight: 1.7, color: palette.text }}>{description}</div>
      </div>
    )
  }

  const handleGenerateEmailFromMatch = (investorName: string) => {
    const question = `帮我写封邮件给${investorName}，项目是在菲律宾做基督教社交媒体`
    setInput(question)
    void handleSend(question)
  }

  useEffect(() => {
    const hasNewMessage = messages.length > prevMessageCountRef.current
    if ((hasNewMessage && !userScrolled) || forceScrollRef.current) {
      scrollToBottom(forceScrollRef.current ? 'smooth' : 'auto')
      forceScrollRef.current = false
      setUserScrolled(false)
      userScrolledRef.current = false
    }
    prevMessageCountRef.current = messages.length
  }, [messages])

  useEffect(() => {
    if (currentId) {
      fetchMessages(currentId).then((list: any[]) => {
        list.forEach((m) => useMessageStore.getState().addMessage(currentId, {
          id: m.id, role: m.role, content: m.content || '',
          sources: m.sources || [], delivery_type: m.delivery_type, status: m.status, scope: m.scope,
        }))
      })
    }
  }, [currentId])

  useEffect(() => {
    if (!currentId) return

    const syncMessages = async () => {
      try {
        const list = await fetchMessages(currentId)
        list.forEach((m: any) =>
          useMessageStore.getState().addMessage(currentId, {
            id: m.id,
            role: m.role,
            content: m.content || '',
            sources: m.sources || [],
            delivery_type: m.delivery_type,
            status: m.status,
            scope: m.scope,
          })
        )
      } catch (e) {
        console.error('同步消息失败:', e)
      }
    }

    const timer = window.setInterval(syncMessages, 2000)
    return () => window.clearInterval(timer)
  }, [currentId])

  useEffect(() => {
    setLastQuery('')
    setUserScrolled(false)
    setIsThinking(false)
    setCurrentTool(null)
    setStreamingContent('')
    streamContentRef.current = ''
    userScrolledRef.current = false
    forceScrollRef.current = true
  }, [currentId])

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort()
    }
  }, [])

  const handleScroll = () => {
    const container = chatContainerRef.current
    if (!container) return

    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight
    const isAtBottom = distanceToBottom <= 100
    setUserScrolled(!isAtBottom)
    userScrolledRef.current = !isAtBottom
  }

  useEffect(() => {
    const loadBookmarks = async () => {
      try {
        const resp = await fetch('http://localhost:8000/api/bookmarks')
        const data = await resp.json()
        const ids = new Set<string>((data || []).map((item: any) => item.item_id).filter(Boolean))
        setBookmarkedItems(ids)
      } catch (e) {
        console.error('加载收藏失败:', e)
      }
    }
    loadBookmarks()
  }, [])

  const detectCountry = (query: string): string => {
    const q = (query || '').toLowerCase()
    if (q.includes('美国') || q.includes('america') || q.includes('usa')) return '美国'
    if (q.includes('韩国') || q.includes('korea')) return '韩国'
    if (q.includes('尼日利亚') || q.includes('nigeria')) return '尼日利亚'
    if (q.includes('菲律宾') || q.includes('philippines')) return '菲律宾'
    return '菲律宾'
  }

  const exportBrief = async (convId: string | null) => {
    if (!convId || !lastQuery) return
    const country = detectCountry(lastQuery)
    const url = `http://localhost:8000/api/export/pdf?query=${encodeURIComponent(lastQuery)}&country=${encodeURIComponent(country)}`
    window.open(url, '_blank')
  }

  const findItemIdByTitle = async (title: string) => {
    const url = new URL('http://localhost:8000/api/search')
    url.searchParams.append('q', title)
    const country = detectCountry(lastQuery)
    if (country) url.searchParams.append('country', country)

    const resp = await fetch(url.toString())
    const data = await resp.json()
    const results = (data.results || []) as SearchResult[]
    const exact = results.find((item) => item.title === title)
    return exact?.id || results[0]?.id || null
  }

  const toggleBookmark = async (itemId: string | null, title: string) => {
    const titleKey = `title:${title}`
    const activeKey = itemId || titleKey

    try {
      if (bookmarkedItems.has(activeKey)) {
        setBookmarkedItems((prev) => {
          const next = new Set(prev)
          next.delete(activeKey)
          if (itemId) next.delete(itemId)
          next.delete(titleKey)
          return next
        })
        return
      }

      const resolvedId = itemId || await findItemIdByTitle(title)
      if (!resolvedId) {
        console.error('未找到可收藏的情报ID:', title)
        return
      }

      const url = new URL('http://localhost:8000/api/bookmarks')
      url.searchParams.append('item_id', resolvedId)
      url.searchParams.append('note', title)

      await fetch(url.toString(), {
        method: 'POST',
      })

      setBookmarkedItems((prev) => {
        const next = new Set(prev)
        next.add(resolvedId)
        next.add(titleKey)
        return next
      })
    } catch (e) {
      console.error('收藏失败:', e)
    }
  }

  const executeSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      setSearchLoading(true)
      const url = new URL('http://localhost:8000/api/search')
      url.searchParams.append('q', searchQuery.trim())

      const resp = await fetch(url.toString())
      const data = await resp.json()
      setSearchResults(data.results || [])
      setShowSearch(true)
    } catch (e) {
      console.error('搜索失败:', e)
      setSearchResults([])
      setShowSearch(true)
    } finally {
      setSearchLoading(false)
    }
  }

  const handleSend = async (overrideInput?: string) => {
    const trimmed = (overrideInput ?? input).trim()
    if (!trimmed) return
    setLastQuery(trimmed)

    const urlRegex = /^(https?:\/\/[^\s]+)$/
    const isUrl = urlRegex.test(trimmed)

    let convId = currentId
    if (!convId) {
      const conv = await createConversation(isUrl ? '链接分析' : trimmed.slice(0, 20))
      convId = conv.id
      addConversation(conv)
    }
    if (!convId) return

    const clientId = `local-user-${Date.now()}`
    const userMsg = {
      id: clientId,
      role: 'user' as const,
      content: trimmed,
      sources: [],
      delivery_type: 'text',
      status: 'completed',
      localOnly: true,
    }
    forceScrollRef.current = true
    setUserScrolled(false)
    userScrolledRef.current = false
    addMessage(convId, userMsg)
    setInput('')

    if (isUrl) {
      const msgId = `url-analysis-${Date.now()}`
      setIsLoading(true)
      forceScrollRef.current = true
      addMessage(convId, {
        id: msgId,
        role: 'assistant' as const,
        content: `🔍 正在分析链接：${trimmed}\n\n请稍候...`,
        sources: [],
        delivery_type: 'url_analysis',
        status: 'running',
      })

      try {
        const r = await fetch('http://localhost:8000/api/analyze-url', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: trimmed }),
        })
        const result = await r.json()

        let content = `## 🔗 链接分析报告\n\n`
        content += `**平台**：${result.platform || '未知'}\n`
        content += `**URL**：${result.url || trimmed}\n\n`

        if (result.status === 'success') {
          content += `### 📊 基础信息\n`
          content += `- 标题：${result.title || '未获取'}\n`
          content += `- 作者/账号：${result.author || result.nickname || '未知'}\n`
          content += `- 描述：${result.description ? String(result.description).substring(0, 200) : '无'}\n`

          if (result.stats) {
            content += `\n### 📈 互动数据\n`
            content += `- 👍 点赞：${typeof result.stats.likes === 'number' ? result.stats.likes.toLocaleString() : (result.stats.likes || 'N/A')}\n`
            content += `- 💬 评论：${typeof result.stats.comments === 'number' ? result.stats.comments.toLocaleString() : (result.stats.comments || 'N/A')}\n`
            content += `- 🔄 分享：${typeof result.stats.shares === 'number' ? result.stats.shares.toLocaleString() : (result.stats.shares || 'N/A')}\n`
            content += `- 👁️ 播放：${typeof result.stats.plays === 'number' ? result.stats.plays.toLocaleString() : (result.stats.plays || 'N/A')}\n`
          }

          if (result.llm_analysis) {
            content += `\n### 🤖 AI分析\n${result.llm_analysis}\n`
          }

          content += `\n---\n💡 提示：如确认此内容有价值，可手动录入情报系统。`
        } else {
          content += `⚠️ 抓取失败：${result.error || '未知错误'}\n`
          content += `\n可能原因：该链接需要登录、已被删除、或平台限制了访问。`
        }

        addMessage(convId, {
          id: msgId,
          role: 'assistant' as const,
          content: content,
          sources: [{ name: result.site_name || result.platform || '链接', url: result.url || trimmed }],
          delivery_type: 'url_analysis',
          status: 'completed',
        })
      } catch (e) {
        addMessage(convId, {
          id: msgId,
          role: 'assistant' as const,
          content: `⚠️ 分析请求失败，请检查后端服务是否运行正常。`,
          sources: [],
          delivery_type: 'error_notification',
          status: 'completed',
        })
      } finally {
        setIsLoading(false)
      }
      return
    }

    setIsLoading(true)
    streamContentRef.current = ''
    setStreamingContent('')
    setIsThinking(true)
    setCurrentTool(null)
    abortControllerRef.current?.abort()
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      await sendChatStream(userMsg.content, convId, (type, data) => {
        if (type === 'thinking') {
          setIsThinking(true)
          setCurrentTool(null)
          return
        }

        if (type === 'tool_call') {
          setIsThinking(false)
          setCurrentTool(data.name || '查询中...')
          if (!userScrolledRef.current) {
            forceScrollRef.current = true
          }
          return
        }

        if (type === 'content') {
          setIsThinking(false)
          setCurrentTool(null)
          streamContentRef.current += data.content || ''
          setStreamingContent(streamContentRef.current)
          if (!userScrolledRef.current) {
            forceScrollRef.current = true
          }
          return
        }

        if (type === 'done') {
          setIsThinking(false)
          setCurrentTool(null)
          const delivery = data.delivery || {}
          const fullContent = data.full_content || delivery.content || streamContentRef.current
          if (!userScrolledRef.current) {
            forceScrollRef.current = true
          }
          addMessage(convId!, {
            id: data.message_id || Date.now().toString(),
            role: 'assistant' as const,
            content: fullContent,
            sources: delivery.sources || [],
            delivery_type: delivery.delivery_type || 'text',
            status: 'completed',
            scope: delivery.scope || delivery.execution_summary?.scope,
          })
          streamContentRef.current = ''
          setStreamingContent('')
          abortControllerRef.current = null
          return
        }

        if (type === 'mission_created') {
          const missionId = data.mission_id || 'N/A'
          if (!userScrolledRef.current) {
            forceScrollRef.current = true
          }
          const missionMsg = {
            id: `mission-${missionId}`,
            role: 'assistant' as const,
            content: `🚀 ${data.message || '已启动采集任务'}\n\n任务ID: ${missionId}`,
            sources: [],
            delivery_type: 'mission_status',
            status: 'running',
          }
          addMessage(convId!, missionMsg)
          return
        }

        if (type === 'mission_progress') {
          if (!userScrolledRef.current) {
            forceScrollRef.current = true
          }
          const progressMsg = {
            id: `mission-progress-${data.request_id || 'current'}`,
            role: 'assistant' as const,
            content: `⏳ 采集中... (${data.jobs_done || 0}/${data.jobs_total || 0} 来源已完成)\n\n任务状态: ${data.mission_status || 'running'}`,
            sources: [],
            delivery_type: 'mission_status',
            status: 'running',
          }
          addMessage(convId!, progressMsg)
          return
        }

        if (type === 'error') {
          setIsThinking(false)
          setCurrentTool(null)
          streamContentRef.current = ''
          setStreamingContent('抱歉，处理出现问题，请重试。')
          if (!userScrolledRef.current) {
            forceScrollRef.current = true
          }
        }
      }, controller.signal)
    } catch (error: any) {
      setIsThinking(false)
      setCurrentTool(null)
      if (error?.name === 'AbortError') {
        setStreamingContent('已中断')
      } else {
        setStreamingContent('网络错误，请重试。')
      }
    } finally {
      setIsLoading(false)
      setIsThinking(false)
      setCurrentTool(null)
    }
  }

  const handleOntologyFilter = (filterType: string, filterValue: string) => {
    const questionMap: Record<string, Record<string, string>> = {
      organization_type: {
        church_network: '菲律宾有哪些教会网络？',
        faithtech_startup: '全球有哪些FaithTech公司？',
        seminary: '菲律宾有哪些神学院？',
        mission_agency: '菲律宾有哪些宣教机构？',
        media_outlet: '菲律宾有哪些基督教媒体？',
        relief_org: '菲律宾有哪些救援机构？',
      },
      theological_position: {
        charismatic: '菲律宾有哪些灵恩派组织？',
        evangelical: '菲律宾有哪些福音派教会？',
        pentecostal: '菲律宾有哪些五旬节派教会？',
        reformed: '菲律宾有哪些改革宗教会？',
        catholic: '菲律宾有哪些天主教组织？',
        interdenominational: '菲律宾有哪些跨宗派组织？',
      },
      investor_query: {
        faithtech_global: '全球有哪些投资FaithTech的投资机构？',
        foundation_global: '全球有哪些基督教基金会？',
        southeast_asia: '东南亚有哪些基督教投资机构？',
        match_me: '我是菲律宾做基督教社交媒体的，谁可能投我？',
      },
    }

    const question = questionMap[filterType]?.[filterValue]
    if (!question || isLoading) return
    setInput(question)
    void handleSend(question)
  }

  const handleAbort = () => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setIsLoading(false)
    setIsThinking(false)
    setCurrentTool(null)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!currentId) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '40px' }}>
        <h1 style={{ fontSize: '28px', marginBottom: '8px', color: '#1a1a1a' }}>基督教情报系统</h1>
        <p style={{ color: '#666', marginBottom: '8px' }}>输入问题，开始情报查询</p>
        <p style={{ color: '#999', fontSize: '13px' }}>支持：知识库问答、机构查询、动态追踪采集</p>
      </div>
    )
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, height: '100%' }}>
      <div style={{
        padding: '14px 24px 12px',
        borderBottom: '1px solid #e0e0e0',
        background: '#f8fafc',
        flexShrink: 0,
      }}>
        <div
          style={{
            ...contentShellStyle,
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            background: '#fff',
            border: '1px solid #e5e7eb',
            borderRadius: '16px',
            padding: '10px',
            boxShadow: '0 8px 24px rgba(15, 23, 42, 0.06)',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', marginBottom: '6px' }}>情报搜索</div>
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && executeSearch()}
              placeholder="搜索情报、机构、关键词..."
              style={{
                width: '100%',
                padding: '12px 14px',
                borderRadius: '12px',
                border: '1px solid #d1d5db',
                fontSize: '14px',
                outline: 'none',
                background: '#f9fafb',
                boxSizing: 'border-box',
              }}
            />
          </div>
          <button
            onClick={executeSearch}
            style={{
              padding: '12px 18px',
              borderRadius: '12px',
              border: 'none',
              background: 'linear-gradient(135deg, #4f46e5 0%, #4338ca 100%)',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 700,
              alignSelf: 'flex-end',
            }}
          >
            搜索
          </button>
          <button
            onClick={onToggleSettings}
            style={{
              border: '1px solid #d1d5db',
              background: showSettings ? '#eef2ff' : '#fff',
              borderRadius: '12px',
              padding: '12px 14px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              color: showSettings ? '#4338ca' : '#374151',
              whiteSpace: 'nowrap',
              alignSelf: 'flex-end',
            }}
          >
            {showSettings ? '关闭设置' : '打开设置'}
          </button>
        </div>
      </div>

      {/* 消息区域 */}
      <div
        ref={chatContainerRef}
        onScroll={handleScroll}
        style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', padding: '16px 24px' }}
      >
        <div style={contentShellStyle}>
          <AgentAlerts />
          <CollectionPanel />
          <TaskPanel refreshToken={taskRefreshToken} />
          {showSearch && (
            <div style={{ marginBottom: '20px', background: '#fff', border: '1px solid #e0e0e0', borderRadius: '14px', padding: '16px' }}>
              <div style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', color: '#1a1a1a' }}>
                搜索结果
              </div>
              {searchLoading && (
                <div style={{ fontSize: '13px', color: '#666' }}>搜索中...</div>
              )}
              {!searchLoading && searchResults.length === 0 && (
                <div style={{ fontSize: '13px', color: '#666' }}>未找到相关情报</div>
              )}
              {!searchLoading && searchResults.map((item) => (
                <div key={item.id} style={{ border: '1px solid #ececec', borderRadius: '10px', padding: '12px', marginBottom: '10px', background: '#fafafa' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '14px', fontWeight: 600, color: '#1a1a1a', marginBottom: '6px' }}>{item.title}</div>
                      <div style={{ fontSize: '12px', color: '#666' }}>
                        来源：{item.source} {item.country ? `| 国家：${item.country}` : ''} {item.published_at ? `| 时间：${item.published_at.slice(0, 10)}` : ''}
                      </div>
                    </div>
                    <button
                      onClick={() => toggleBookmark(item.id, item.title)}
                      style={{
                        padding: '4px 8px',
                        borderRadius: '6px',
                        border: '1px solid #e0e0e0',
                        background: bookmarkedItems.has(item.id) ? '#fef3c7' : '#fff',
                        fontSize: '12px',
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {bookmarkedItems.has(item.id) ? '⭐ 已收藏' : '☆ 收藏'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} style={{ marginBottom: '20px', display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            {msg.delivery_type === 'status_update' ? (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '2px 8px',
                color: '#6b7280',
                fontSize: '12px',
                lineHeight: 1.6,
              }}>
                <span>{filterDSML(msg.content)}</span>
              </div>
            ) : msg.delivery_type === 'agent_notification' ? (
              <div style={{
                maxWidth: '80%',
                padding: '14px 18px',
                borderRadius: '14px',
                background: 'linear-gradient(90deg, #eef2ff 0%, #f5f3ff 100%)',
                border: '1px solid #c7d2fe',
                color: '#1f2937',
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                  {renderAssistantAvatar(60, 56, '#eef4ff')}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#4f46e5', marginBottom: '6px' }}>
                      Agent自动通知
                    </div>
                    <div
                      className="markdown-body"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(filterDSML(msg.content)) }}
                    />
                  </div>
                </div>
              </div>
            ) : (
            (() => {
              const visibleContent = getDisplayContent(msg.content)
              const isIntelBrief =
                msg.role === 'assistant' &&
                ['intelligence_brief', 'analysis_brief', 'contact_partial', 'contact_full', 'global_brief'].includes(msg.delivery_type || '')
              const isGlobalBrief =
                msg.role === 'assistant' &&
                ((msg as any).scope === 'global' || msg.delivery_type === 'global_brief')
              const matchPayload = extractMetaPayload<MatchPayload>(msg.content, 'MATCH_DATA')
              const graphPayload = extractMetaPayload<GraphPayload>(msg.content, 'GRAPH_DATA')
              const hasMatchCard = msg.role === 'assistant' && !!matchPayload?.matches?.length
              const hasGraphCard = msg.role === 'assistant' && !!graphPayload?.relations?.length
              const cleanContent = getDisplayContent(msg.content)
              return (
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', maxWidth: '86%' }}>
              {msg.role === 'assistant' && renderAssistantAvatar(60, 56, '#eef4ff')}
              <div style={{
                maxWidth: msg.role === 'assistant' ? 'calc(100% - 72px)' : '80%',
                padding: '14px 18px',
                borderRadius: '14px',
                background: msg.role === 'user' ? '#4f46e5' : '#fff',
                color: msg.role === 'user' ? '#fff' : '#1a1a1a',
                border: msg.role === 'user' ? 'none' : '1px solid #e0e0e0',
                fontSize: '14px',
                lineHeight: '1.6',
                whiteSpace: 'pre-wrap',
              }}>
                {msg.role === 'assistant'
                  ? (msg.delivery_type === 'no_data'
                      ? renderFeedbackCard('当前数据不足', stripMarkdown(visibleContent), 'warning')
                      : msg.delivery_type === 'clarify'
                      ? renderFeedbackCard('需要你补充一点信息', stripMarkdown(visibleContent), 'info')
                      : msg.delivery_type === 'error_notification'
                      ? renderFeedbackCard('处理失败', stripMarkdown(visibleContent), 'error')
                      : msg.delivery_type === 'mission_status'
                      ? renderFeedbackCard('后台任务更新', stripMarkdown(visibleContent), 'success')
                      : isGlobalBrief
                      ? renderGlobalContent(msg)
                      : hasMatchCard
                      ? (
                          <div style={{ display: 'grid', gap: '12px' }}>
                            <InvestorMatchCard
                              matches={matchPayload?.matches || []}
                              projectDescription={matchPayload?.project_description}
                              onCreateTask={handleCreateInvestorTask}
                              onGenerateEmail={handleGenerateEmailFromMatch}
                            />
                            {cleanContent && (
                              <div
                                className="markdown-body"
                                dangerouslySetInnerHTML={{ __html: renderMarkdown(cleanContent) }}
                              />
                            )}
                          </div>
                        )
                      : hasGraphCard
                      ? (
                          <div style={{ display: 'grid', gap: '12px' }}>
                            <IntelGraph
                              centerEntity={graphPayload?.center_entity || ''}
                              relations={graphPayload?.relations || []}
                              width={580}
                              height={380}
                            />
                            {cleanContent && (
                              <div
                                className="markdown-body"
                                dangerouslySetInnerHTML={{ __html: renderMarkdown(cleanContent) }}
                              />
                            )}
                          </div>
                        )
                      : isIntelBrief
                      ? renderIntelContent(visibleContent, msg.sources.length, msg.delivery_type)
                      : (
                          <div
                            className="markdown-body"
                            dangerouslySetInnerHTML={{ __html: renderMarkdown(cleanContent) }}
                          />
                        ))
                  : getDisplayContent(msg.content)}
                {msg.role === 'assistant' && ['intelligence_brief', 'analysis_brief', 'contact_full'].includes(msg.delivery_type || '') && parseBriefItems(visibleContent).length > 0 && (
                  <div style={{ marginTop: '12px', display: 'grid', gap: '10px' }}>
                    {parseBriefItems(visibleContent).map((item) => {
                      const titleKey = `title:${item.title}`
                      return (
                        <div key={`${msg.id}-${item.title}`} style={{ border: '1px solid #ececec', borderRadius: '10px', padding: '12px', background: '#fafafa' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: '14px', fontWeight: 600, color: '#1a1a1a', marginBottom: '6px' }}>{item.title}</div>
                              <div style={{ fontSize: '12px', color: '#666' }}>
                                {item.source ? `来源：${item.source}` : '来源：N/A'}
                                {item.publishedAt ? ` | 时间：${item.publishedAt}` : ''}
                              </div>
                            </div>
                            <button
                              onClick={() => toggleBookmark(null, item.title)}
                              style={{
                                padding: '4px 8px',
                                borderRadius: '6px',
                                border: '1px solid #e0e0e0',
                                background: bookmarkedItems.has(titleKey) ? '#fef3c7' : '#fff',
                                fontSize: '12px',
                                cursor: 'pointer',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {bookmarkedItems.has(titleKey) ? '⭐ 已收藏' : '☆ 收藏'}
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
                {msg.role === 'assistant' && msg.sources.length > 0 && (
                  <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid #e0e0e0' }}>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '6px' }}>来源：</div>
                    {msg.sources.map((s, i) => (
                      <div key={i} style={{ fontSize: '12px' }}>
                        <a href={s.url} target="_blank" rel="noreferrer" style={{ color: '#4f46e5' }}>{s.name || s.url}</a>
                      </div>
                    ))}
                  </div>
                )}
                {msg.role === 'assistant' && ['intelligence_brief', 'analysis_brief', 'contact_full'].includes(msg.delivery_type || '') && (
                  <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #e0e0e0', display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => exportBrief(currentId)}
                      disabled={!lastQuery}
                      style={{
                        padding: '6px 14px',
                        borderRadius: '8px',
                        border: '1px solid #4f46e5',
                        background: '#4f46e5',
                        color: '#fff',
                        fontSize: '13px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        opacity: lastQuery ? 1 : 0.6,
                      }}
                    >
                      📄 导出PDF
                    </button>
                    <button
                      onClick={() => window.open(`http://localhost:8000/api/export/html?query=${encodeURIComponent(lastQuery)}&country=${encodeURIComponent(detectCountry(lastQuery))}`, '_blank')}
                      disabled={!lastQuery}
                      style={{
                        padding: '6px 14px',
                        borderRadius: '8px',
                        border: '1px solid #d0d0d0',
                        background: '#fff',
                        color: '#333',
                        fontSize: '13px',
                        cursor: 'pointer',
                        opacity: lastQuery ? 1 : 0.6,
                      }}
                    >
                      🔗 预览HTML
                    </button>
                  </div>
                )}
              </div>
            </div>
              )
            })()
            )}
            </div>
          ))}
          {isThinking && !streamingContent && (
            <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
              <div style={{ padding: '18px 22px', background: '#f9fafb', borderRadius: '16px', border: '1px solid #dbeafe', display: 'flex', alignItems: 'center', gap: '16px', boxShadow: '0 8px 24px rgba(59, 130, 246, 0.08)' }}>
                {renderAssistantAvatar(66, 60, '#dbeafe')}
                <div>
                  <div style={{ fontSize: '16px', fontWeight: 700, color: '#374151' }}>情报官思考中...</div>
                  <div style={{ fontSize: '13px', color: '#6b7280' }}>正在分析您的需求</div>
                </div>
              </div>
            </div>
          )}
          {currentTool && (
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '16px' }}>
              <div style={{ padding: '12px 16px', background: '#eff6ff', borderRadius: '14px', border: '1px solid #bfdbfe', color: '#1d4ed8', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{ width: '8px', height: '8px', borderRadius: '999px', background: '#3b82f6' }} />
                <span>正在分析：{humanizeToolName(currentTool)}</span>
              </div>
            </div>
          )}
          {streamingContent && (
            <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '20px' }}>
              <div style={{ maxWidth: '86%', padding: '16px 20px', borderRadius: '16px', background: '#fff', color: '#1a1a1a', border: '1px solid #e0e0e0', fontSize: '14px', lineHeight: '1.7', whiteSpace: 'pre-wrap' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                  {renderAssistantAvatar(60, 56, '#eef4ff')}
                  <div style={{ flex: 1 }}>
                    <div style={{ marginBottom: '8px', fontSize: '12px', fontWeight: 700, color: '#4f46e5' }}>实时生成中</div>
                    <div className="streaming-body">
                      {stripMarkdown(streamingContent)}
                      {isLoading && <span style={{ display: 'inline-block', width: '8px', height: '16px', background: '#6366f1', marginLeft: '6px', verticalAlign: 'middle' }} />}
                    </div>
                    <button
                      onClick={handleAbort}
                      style={{ marginTop: '10px', padding: '4px 10px', borderRadius: '8px', border: '1px solid #fecaca', background: '#fee2e2', color: '#dc2626', fontSize: '12px', cursor: 'pointer' }}
                    >
                      ⏹ 中断
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div style={{ flexShrink: 0, borderTop: '1px solid #e5e7eb', background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)' }}>
        <div style={{ ...contentShellStyle, padding: '14px 24px 18px', boxSizing: 'border-box' }}>
          <div
            style={{
              border: '1px solid #e5e7eb',
              borderRadius: '18px',
              background: '#fff',
              padding: '14px',
              boxShadow: '0 -6px 24px rgba(15, 23, 42, 0.05)',
            }}
          >
            <OntologyFilter onFilter={handleOntologyFilter} disabled={isLoading} />
            <div style={{ marginTop: '14px' }}>
              <div style={{ fontSize: '11px', fontWeight: 700, color: '#9ca3af', marginBottom: '8px' }}>对话输入</div>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-end',
                  gap: '10px',
                  border: '1px solid #dbe1ea',
                  borderRadius: '16px',
                  padding: '10px',
                  background: '#f9fafb',
                }}
              >
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入你的问题，支持机构查询、投资匹配、图谱关系、全球新闻..."
                  rows={1}
                  style={{
                    flex: 1,
                    resize: 'none',
                    minHeight: '48px',
                    maxHeight: '140px',
                    padding: '12px 14px',
                    borderRadius: '12px',
                    border: '1px solid #e5e7eb',
                    background: '#fff',
                    fontSize: '14px',
                    lineHeight: '1.6',
                    outline: 'none',
                  }}
                />
                <button
                  onClick={() => {
                    void handleSend()
                  }}
                  disabled={isLoading || !input.trim()}
                  style={{
                    padding: '12px 18px',
                    borderRadius: '12px',
                    border: 'none',
                    background: 'linear-gradient(135deg, #111827 0%, #1f2937 100%)',
                    color: '#fff',
                    fontSize: '14px',
                    fontWeight: 700,
                    cursor: isLoading || !input.trim() ? 'not-allowed' : 'pointer',
                    opacity: isLoading || !input.trim() ? 0.45 : 1,
                    flexShrink: 0,
                  }}
                >
                  发送
                </button>
                {isLoading && (
                  <button
                    onClick={handleAbort}
                    style={{
                      padding: '12px 14px',
                      borderRadius: '12px',
                      border: '1px solid #fecaca',
                      background: '#fff1f2',
                      color: '#dc2626',
                      fontSize: '14px',
                      fontWeight: 600,
                      cursor: 'pointer',
                      flexShrink: 0,
                    }}
                  >
                    中断
                  </button>
                )}
              </div>
              <div style={{ marginTop: '8px', fontSize: '11px', color: '#9ca3af' }}>
                `Enter` 发送，`Shift + Enter` 换行。也可以先点上方快速筛选，自动发起常见查询。
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ChatArea
