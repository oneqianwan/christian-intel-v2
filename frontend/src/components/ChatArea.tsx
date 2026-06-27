import { useState, useRef, useEffect } from 'react'
import { useConversationStore } from '../stores/conversationStore'
import { useMessageStore } from '../stores/messageStore'
import { sendChatStream, fetchMessages, createConversation } from '../services/api'
import { createMission, getMissionStatus } from '../services/missionApi'
import GlobalIntelCard from './GlobalIntelCard'
import AgentAlerts from './AgentAlerts'

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

const renderMarkdown = (content: string): string => {
  const lines = content.split('\n')
  const html: string[] = []
  let inList = false

  const closeList = () => {
    if (inList) {
      html.push('</ul>')
      inList = false
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()

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
        html.push('<ul>')
        inList = true
      }
      html.push(`<li>${renderInlineMarkdown(bulletMatch[1])}</li>`)
      continue
    }

    closeList()
    html.push(`<p>${renderInlineMarkdown(line)}</p>`)
  }

  closeList()
  return html.join('')
}

const extractSection = (content: string, section: string): string => {
  const lines = content.split('\n')
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
  value
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^#+\s+/gm, '')
    .replace(/\[CONFIDENCE:\s*[A-Z]+\]/g, '')
    .replace(/\[SOURCE:\s*[^\]]+\]/g, '')
    .trim()

const extractTags = (content: string, sourcesCount: number, deliveryType?: string): IntelTag[] => {
  const tags: IntelTag[] = []
  const sourceMatches = content.match(/\[SOURCE:\s*([^\]]+)\]/g)
  const sourceTotal = sourceMatches?.length || sourcesCount
  if (sourceTotal > 0) {
    tags.push({ type: 'source', text: `📎 ${sourceTotal}个来源` })
  }

  const confMatches = content.match(/\[CONFIDENCE:\s*([A-Z]+)\]/g)
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

  if (content.includes('建议行动')) {
    tags.push({ type: 'action', text: '⚡ 有建议行动' })
  }

  if (deliveryType === 'contact_partial') {
    tags.push({ type: 'completeness-partial', text: '⚠️ PARTIAL' })
  }

  return tags
}

function ChatArea() {
  const { currentId, addConversation } = useConversationStore()
  const { addMessage, getMessages } = useMessageStore()
  const [input, setInput] = useState('')
  const [lastQuery, setLastQuery] = useState('')
  const [bookmarkedItems, setBookmarkedItems] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [searchCountry, setSearchCountry] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [activeMission, setActiveMission] = useState<string | null>(null)
  const [missionStatus, setMissionStatus] = useState<any>(null)
  const [userScrolled, setUserScrolled] = useState(false)
  const chatContainerRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const prevMessageCountRef = useRef(0)
  const forceScrollRef = useRef(false)
  const userScrolledRef = useRef(false)

  const messages = currentId ? getMessages(currentId) : []

  const scrollToBottom = (behavior: ScrollBehavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior })
  }

  const renderIntelContent = (content: string, sourcesCount: number, deliveryType?: string) => {
    const conclusion = extractSection(content, '核心结论')
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
          dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
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
    const conclusion = stripMarkdown(extractSection(msg.content, '核心结论'))
    const summary = conclusion || stripMarkdown(msg.content).slice(0, 220)
    const firstLine = stripMarkdown(msg.content).split('\n').find((line) => line.trim()) || '全球情报简报'
    const firstSource = msg.sources[0] || { name: '全球来源', url: '' }
    const confidence = msg.content.match(/\[CONFIDENCE:\s*([A-Z]+)\]/)?.[1]
    const publishedAt = msg.content.match(/(\d{4}-\d{2}-\d{2})/)?.[1]

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
          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
        />
      </div>
    )
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
    setActiveMission(null)
    setMissionStatus(null)
    setLastQuery('')
    setUserScrolled(false)
    userScrolledRef.current = false
    forceScrollRef.current = true
  }, [currentId])

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
      if (searchCountry) url.searchParams.append('country', searchCountry)

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

  const pollMissionStatus = async (missionId: string) => {
    const targetConversationId = currentId
    const check = async () => {
      const status = await getMissionStatus(missionId)
      setMissionStatus(status)
      if (status.mission?.status === 'done' || status.mission?.status === 'failed') {
        setActiveMission(null)
        const resultMsg = {
          id: Date.now().toString(),
          role: 'assistant' as const,
          content: `## 采集任务完成\n\n- 任务ID: ${missionId}\n- 状态: ${status.mission.status}\n- 发现情报条目: ${status.intelligence_count || 0}\n\n${status.intelligence_count > 0 ? '已入库的情报可在知识库中查询。' : '本次采集未命中菲律宾相关内容，建议后续补充更多本地来源。'}`,
          sources: [],
          delivery_type: 'intelligence_brief',
          status: 'completed',
        }
        if (targetConversationId) addMessage(targetConversationId, resultMsg)
      } else {
        setTimeout(check, 2000)
      }
    }
    check()
  }

  const handleSend = async () => {
    const trimmed = input.trim()
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

    let assistantContent = ''
    await sendChatStream(userMsg.content, convId, (type, data) => {
      if (type === 'mission_created') {
        const missionId = data.mission_id || 'N/A'
        setActiveMission(data.mission_id || null)
        setMissionStatus({
          mission: { id: missionId, status: 'queued' },
          intelligence_count: 0,
        })
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
      } else if (type === 'mission_progress') {
        setMissionStatus({
          mission: { id: activeMission || 'running', status: data.mission_status || 'running' },
          intelligence_count: 0,
        })
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
      } else if (type === 'delivery_emitted') {
        setActiveMission(null)
        setMissionStatus((prev: any) => prev ? { ...prev, mission: { ...prev.mission, status: 'done' } } : null)
        assistantContent = data.delivery?.content || ''
        if (!userScrolledRef.current) {
          forceScrollRef.current = true
        }
        const assistantMsg = {
          id: data.message_id || Date.now().toString(),
          role: 'assistant' as const,
          content: assistantContent,
          sources: data.delivery?.sources || [],
          delivery_type: data.delivery?.delivery_type || 'text',
          status: 'completed',
          scope: data.delivery?.scope || data.delivery?.execution_summary?.scope,
        }
        addMessage(convId!, assistantMsg)
      } else if (type === 'error') {
        setActiveMission(null)
        if (!userScrolledRef.current) {
          forceScrollRef.current = true
        }
        const errorMsg = {
          id: data.message_id || Date.now().toString(),
          role: 'assistant' as const,
          content: `⚠️ **服务响应异常**\n\n${data.message || '请求处理过程中发生错误，请稍后重试。'}`,
          sources: [],
          delivery_type: 'error_notification',
          status: 'completed',
        }
        addMessage(convId!, errorMsg)
      }
    })
    setIsLoading(false)
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
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 采集任务区域（仅在有当前会话时显示） */}
      {currentId && (
        <div style={{ borderBottom: '1px solid #e0e0e0', padding: '12px 20%', background: '#fafafa' }}>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button
              onClick={async () => {
                const result = await createMission('菲律宾基督教最新动态', '菲律宾')
                if (result.mission_id) {
                  setActiveMission(result.mission_id)
                  pollMissionStatus(result.mission_id)
                }
              }}
              disabled={!!activeMission}
              style={{
                padding: '8px 16px', borderRadius: '8px', border: '1px solid #4f46e5',
                background: '#4f46e5', color: '#fff', fontSize: '13px', cursor: 'pointer',
                opacity: activeMission ? 0.5 : 1,
              }}
            >
              {activeMission ? '采集中...' : '启动菲律宾情报采集'}
            </button>
            {missionStatus && (
              <span style={{ fontSize: '13px', color: '#666' }}>
                状态: {missionStatus.mission?.status || 'queued'} | 发现情报: {missionStatus.intelligence_count || 0}
              </span>
            )}
          </div>
        </div>
      )}

      <div style={{
        padding: '12px 20%',
        borderBottom: '1px solid #e0e0e0',
        background: '#fff',
        display: 'flex',
        gap: '10px',
      }}>
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && executeSearch()}
          placeholder="搜索情报..."
          style={{
            flex: 1,
            padding: '10px 16px',
            borderRadius: '10px',
            border: '1px solid #d0d0d0',
            fontSize: '14px',
            outline: 'none',
          }}
        />
        <select
          value={searchCountry}
          onChange={(e) => setSearchCountry(e.target.value)}
          style={{
            padding: '10px',
            borderRadius: '10px',
            border: '1px solid #d0d0d0',
          }}
        >
          <option value="">全部国家</option>
          <option value="菲律宾">菲律宾</option>
          <option value="美国">美国</option>
          <option value="韩国">韩国</option>
          <option value="尼日利亚">尼日利亚</option>
        </select>
        <button
          onClick={executeSearch}
          style={{
            padding: '10px 20px',
            borderRadius: '10px',
            border: 'none',
            background: '#4f46e5',
            color: '#fff',
            cursor: 'pointer',
          }}
        >
          搜索
        </button>
      </div>

      {/* 消息区域 */}
      <div
        ref={chatContainerRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflow: 'auto', padding: '20px 20%' }}
      >
        <AgentAlerts />
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
                <span>{msg.content}</span>
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
                  <span style={{ fontSize: '18px', lineHeight: 1 }}>🤖</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '12px', fontWeight: 700, color: '#4f46e5', marginBottom: '6px' }}>
                      Agent自动通知
                    </div>
                    <div
                      className="markdown-body"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                    />
                  </div>
                </div>
              </div>
            ) : (
            (() => {
              const isIntelBrief =
                msg.role === 'assistant' &&
                ['intelligence_brief', 'analysis_brief', 'contact_partial', 'contact_full', 'global_brief'].includes(msg.delivery_type || '')
              const isGlobalBrief =
                msg.role === 'assistant' &&
                ((msg as any).scope === 'global' || msg.delivery_type === 'global_brief')
              return (
            <div style={{
              maxWidth: '80%', padding: '14px 18px', borderRadius: '14px',
              background: msg.role === 'user' ? '#4f46e5' : '#fff',
              color: msg.role === 'user' ? '#fff' : '#1a1a1a',
              border: msg.role === 'user' ? 'none' : '1px solid #e0e0e0',
              fontSize: '14px', lineHeight: '1.6', whiteSpace: 'pre-wrap',
            }}>
              {msg.role === 'assistant'
                ? (isGlobalBrief
                    ? renderGlobalContent(msg)
                    : isIntelBrief
                    ? renderIntelContent(msg.content, msg.sources.length, msg.delivery_type)
                    : (
                        <div
                          className="markdown-body"
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                        />
                      ))
                : msg.content}
              {msg.role === 'assistant' && ['intelligence_brief', 'analysis_brief', 'contact_full'].includes(msg.delivery_type || '') && parseBriefItems(msg.content).length > 0 && (
                <div style={{ marginTop: '12px', display: 'grid', gap: '10px' }}>
                  {parseBriefItems(msg.content).map((item) => {
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
              )
            })()
            )}
          </div>
        ))}
        {isLoading && (
          <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
            <div style={{ padding: '14px 18px', background: '#fff', borderRadius: '14px', border: '1px solid #e0e0e0' }}>
              <span style={{ fontSize: '14px', color: '#666' }}>思考中...</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入框 */}
      <div style={{ borderTop: '1px solid #e0e0e0', padding: '12px 20%', background: '#fff' }}>
        <div style={{ display: 'flex', gap: '10px' }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题..."
            style={{ flex: 1, padding: '12px 16px', borderRadius: '10px', border: '1px solid #d0d0d0', fontSize: '14px', outline: 'none' }}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            style={{ padding: '12px 24px', borderRadius: '10px', border: 'none', background: '#4f46e5', color: '#fff', fontSize: '14px', cursor: 'pointer', opacity: isLoading ? 0.6 : 1 }}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  )
}

export default ChatArea
