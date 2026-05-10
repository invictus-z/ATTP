import { ref, reactive, computed } from 'vue'
import { renderMarkdown } from '../markdown'
import { getActiveAgent, getActiveAgentId, getAgentById, getAgents, wsUrl, wsUrlForAgent, apiUrl, onAgentSwitch, updateAgentStatus } from '../agent_manager'
import { createWs, onWsMessage, onWsOpen, onWsClose, onWsError, apiFetch, type WsConnection } from '../transport'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
  senderOverride?: string
  timestamp?: string
}

export interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  rtLogs?: { senderName: string; text: string }[]
  nodeHistories?: { [targetNode: string]: { role: 'user' | 'agent'; text: string; timeStr: string }[] }
  updatedAt: number
  isPinned?: boolean
  isUnread?: boolean
  unreadCount?: number
  senderName?: string
}

// ---- Per-Agent State Maps ----

/** Sessions storage keyed by agentId */
const agentSessionsMap = new Map<string, ChatSession[]>()
/** Current session ID keyed by agentId */
const agentCurrentSessionMap = new Map<string, string | null>()
/** WebSocket connections keyed by agentId */
const agentWsMap = new Map<string, WsConnection>()
/** WS connected status keyed by agentId */
const agentWsConnectedMap = new Map<string, boolean>()

// ---- Shared Reactive State (for active agent) ----

const sessions = ref<ChatSession[]>([])
const currentSessionId = ref<string | null>(null)
const agentStatus = ref<'active' | 'offline' | 'connecting'>('offline')
let agentSwitchRegistered = false

// ---- Per-Agent Session Helpers ----

const getSessionKey = (agentId: string) => `nanobot_sessions_${agentId}`

/** Save current active agent's sessions to its map slot + localStorage */
const saveSessions = () => {
  const agentId = getActiveAgentId()
  if (!agentId) return
  agentSessionsMap.set(agentId, [...sessions.value])
  localStorage.setItem(getSessionKey(agentId), JSON.stringify(sessions.value))
}

/** Save sessions for a specific agent (used by background WS handlers) */
const saveSessionsForAgent = (agentId: string, sess: ChatSession[]) => {
  agentSessionsMap.set(agentId, sess)
  localStorage.setItem(getSessionKey(agentId), JSON.stringify(sess))
}

/** Load sessions for a specific agent from localStorage */
const loadSessionsForAgent = (agentId: string): ChatSession[] => {
  try { return JSON.parse(localStorage.getItem(getSessionKey(agentId)) || '[]') } catch { return [] }
}

/** Get sessions for a specific agent (from map or localStorage) */
const getSessionsForAgent = (agentId: string): ChatSession[] => {
  if (agentSessionsMap.has(agentId)) return agentSessionsMap.get(agentId)!
  const loaded = loadSessionsForAgent(agentId)
  agentSessionsMap.set(agentId, loaded)
  return loaded
}

/** Flush active agent sessions to map before switching */
const flushActiveSessions = () => {
  const agentId = getActiveAgentId()
  if (agentId) {
    agentSessionsMap.set(agentId, [...sessions.value])
    agentCurrentSessionMap.set(agentId, currentSessionId.value)
  }
}

/** Load sessions for the new active agent */
const loadActiveSessions = () => {
  const agentId = getActiveAgentId()
  if (!agentId) { sessions.value = []; currentSessionId.value = null; return }
  const sess = getSessionsForAgent(agentId)
  sessions.value = sess
  currentSessionId.value = agentCurrentSessionMap.get(agentId) || (sess.length > 0 ? sess[0].id : null)
}

export function useChat() {
  const chatInput = ref('')
  const batchMode = ref(false)
  const selectedSessionIds = reactive(new Set<string>())
  const searchQuery = ref('')

  const totalUnread = computed(() =>
    sessions.value.filter(s => s.isUnread && s.unreadCount && s.unreadCount > 0)
      .reduce((sum, s) => sum + (s.unreadCount || 0), 0)
  )

  const currentSession = computed(() => sessions.value.find(s => s.id === currentSessionId.value))

  const createSession = (initialTitle: string) => {
    const newSession: ChatSession = {
      id: 'sess_' + Date.now().toString(),
      title: initialTitle,
      messages: [],
      rtLogs: [],
      nodeHistories: {},
      updatedAt: Date.now(),
    }
    sessions.value.unshift(newSession)
    currentSessionId.value = newSession.id
    saveSessions()
    return newSession
  }

  const updateAgentStatusBadge = (status: 'active' | 'offline' | 'connecting') => {
    agentStatus.value = status
  }

  const formatTime = (ts: string) => {
    try {
      const d = new Date(ts)
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    } catch { return '' }
  }

  const getDateKey = (ts: string) => {
    const d = new Date(ts)
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
  }

  const formatDateLabel = (ts: string) => {
    const d = new Date(ts)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate())
    const diffDays = Math.round((today.getTime() - msgDay.getTime()) / 86400000)
    const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    if (diffDays === 0) return 'Today'
    if (diffDays === 1) return 'Yesterday'
    return `${d.getMonth() + 1}月${d.getDate()}日 ${weekdays[d.getDay()]}`
  }

  const renderMessageHtml = (msg: ChatMessage) => {
    const timeStr = msg.timestamp ? formatTime(msg.timestamp) : ''
    if (msg.role === 'user') {
      return `
        <div class="flex justify-end group fade-in">
          <div class="max-w-[80%] flex flex-col items-end">
            <div class="flex items-center space-x-2 mb-1.5 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <span class="text-[11px] font-medium text-gray-500">You (Admin)</span>
              ${timeStr ? `<span class="text-[11px] text-gray-400">${timeStr}</span>` : ''}
            </div>
            <div class="bg-gray-800 text-white rounded-2xl rounded-tr-sm p-4 w-full shadow-md text-[14px]">${msg.content}</div>
          </div>
        </div>`
    } else {
      const agent = getActiveAgent()
      const displaySender = msg.senderOverride || (agent ? agent.name : 'Agent')
      return `
        <div class="flex justify-start group fade-in">
          <div class="max-w-[80%] flex flex-col items-start">
            <div class="flex items-center gap-2 mb-1.5 px-1">
              <div class="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center border border-gray-200">
                <i data-lucide="bot" class="w-3 h-3 text-gray-600"></i>
              </div>
              <span class="text-[11px] font-medium text-gray-600">${displaySender}</span>
              ${timeStr ? `<span class="text-[11px] text-gray-400">${timeStr}</span>` : ''}
            </div>
            <div class="bg-white border border-gray-100 rounded-2xl rounded-tl-sm p-4 w-full shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] text-gray-700 text-[14px] leading-relaxed markdown-body">
              ${renderMarkdown(msg.content)}
            </div>
          </div>
        </div>`
    }
  }

  const renderNodeMessageHtml = (role: 'user' | 'agent', text: string, timeStr: string) => {
    const contentClass = role === 'user'
      ? 'bg-gray-900 text-white rounded-2xl rounded-tr-sm px-5 py-3.5 shadow-sm ml-12'
      : 'bg-white border border-gray-100/80 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] text-gray-800 rounded-2xl rounded-tl-sm px-5 py-3.5 mr-12'
    return `
      <div class="${role === 'user' ? 'flex items-start justify-end gap-4' : 'flex items-start gap-4'}">
        ${role === 'agent' ? '<div class="w-8 h-8 rounded-full bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0 shadow-sm mt-1"><i data-lucide="shield-check" class="w-4 h-4 text-emerald-600"></i></div>' : ''}
        <div class="flex flex-col gap-1 ${role === 'user' ? 'items-end' : ''}">
          <div class="flex items-center gap-2 px-1">
            <span class="text-[11px] font-medium text-gray-500 uppercase tracking-wide">${role === 'user' ? 'Agent Request' : 'Node Trace'}</span>
            <span class="text-[10px] text-gray-400 font-mono">${timeStr}</span>
          </div>
          <div class="text-[14px] leading-relaxed relative group ${contentClass} markdown-body">
            ${role === 'agent' ? renderMarkdown(text) : text.replace(/\n/g, '<br>')}
          </div>
        </div>
        ${role === 'user' ? '<div class="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-100 flex items-center justify-center shrink-0 shadow-sm mt-1"><i data-lucide="blocks" class="w-4 h-4 text-indigo-600"></i></div>' : ''}
      </div>`
  }

  /** Add a message to a session for a SPECIFIC agent (used by background WS) */
  const addMessageToAgentSession = (
    agentId: string, sessionId: string, role: 'user' | 'agent',
    content: string, senderOverride?: string
  ) => {
    const activeAgentId = getActiveAgentId()
    const isActive = agentId === activeAgentId

    if (isActive) {
      // Operating on the reactive sessions array directly
      addMessageToSession(sessionId, role, content, senderOverride)
      return
    }

    // Background agent — operate on its own session array
    const agentSessions = getSessionsForAgent(agentId)
    const agent = getAgentById(agentId)
    let session = agentSessions.find(s => s.id === sessionId)

    if (!session) {
      if (role === 'agent') {
        const senderName = senderOverride || (agent ? agent.name : 'Remote Agent')
        session = {
          id: sessionId,
          title: `Message from ${senderName}`,
          messages: [], rtLogs: [], nodeHistories: {},
          updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName,
        }
        agentSessions.unshift(session)
      } else {
        // Create a new session for user message from background
        session = {
          id: 'sess_' + Date.now().toString(),
          title: content.length > 20 ? content.slice(0, 20) + '...' : content,
          messages: [], rtLogs: [], nodeHistories: {},
          updatedAt: Date.now(),
        }
        agentSessions.unshift(session)
      }
    }

    if (session) {
      // Mark unread for background agent
      const agentCurrentSessId = agentCurrentSessionMap.get(agentId)
      if (role === 'agent' && agentCurrentSessId !== sessionId) {
        if (!session.isUnread) session.isUnread = true
        session.unreadCount = (session.unreadCount || 0) + 1
      }
      session.messages.push({ role, content, senderOverride, timestamp: new Date().toISOString() })
      session.updatedAt = Date.now()
    }

    saveSessionsForAgent(agentId, agentSessions)
  }

  /** Add a node message for a SPECIFIC agent (background) */
  const addNodeMessageForAgent = (
    agentId: string, targetSessionId: string, targetNode: string,
    role: 'user' | 'agent', text: string
  ) => {
    const activeAgentId = getActiveAgentId()
    if (agentId === activeAgentId) {
      addNodeMessage(targetSessionId, targetNode, role, text)
      return
    }

    const agentSessions = getSessionsForAgent(agentId)
    const timeStr = new Date().toLocaleTimeString()
    let sess = agentSessions.find(s => s.id === targetSessionId)
    if (!sess) {
      sess = { id: targetSessionId, title: `Message from ${targetNode}`, messages: [], rtLogs: [], nodeHistories: {}, updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName: targetNode }
      agentSessions.unshift(sess)
    }
    if (!sess.senderName) sess.senderName = targetNode
    if (!sess.nodeHistories) sess.nodeHistories = {}
    if (!sess.nodeHistories[targetNode]) sess.nodeHistories[targetNode] = []
    sess.nodeHistories[targetNode].push({ role, text, timeStr })
    const agentCurrentSessId = agentCurrentSessionMap.get(agentId)
    if (agentCurrentSessId !== targetSessionId) { sess.isUnread = true; sess.unreadCount = (sess.unreadCount || 0) + 1 }
    saveSessionsForAgent(agentId, agentSessions)
  }

  const addMessageToSession = (sessionId: string, role: 'user' | 'agent', content: string, senderOverride?: string) => {
    let session = sessions.value.find(s => s.id === sessionId)
    if (!session) {
      if (role === 'agent') {
        const agent = getActiveAgent()
        const senderName = senderOverride || (agent ? agent.name : 'Remote Agent')
        const newSession: ChatSession = {
          id: sessionId,
          title: `Message from ${senderName}`,
          messages: [],
          rtLogs: [],
          nodeHistories: {},
          updatedAt: Date.now(),
          isUnread: false,
          unreadCount: 0,
          senderName: senderName,
        }
        sessions.value.unshift(newSession)
        session = newSession
      } else {
        session = createSession(content.slice(0, 20) + '...')
      }
    }
    if (session && !session.senderName && senderOverride) {
      const agent = getActiveAgent()
      if (senderOverride !== (agent ? agent.name : 'Agent')) session.senderName = senderOverride
    }
    if (session.messages.length === 0 && role === 'user') {
      session.title = content.length > 20 ? content.slice(0, 20) + '...' : content
    }
    if (role === 'agent' && currentSessionId.value !== sessionId) {
      if (!session.isUnread) session.isUnread = true
      session.unreadCount = (session.unreadCount || 0) + 1
    } else if (currentSessionId.value === sessionId && role === 'agent') {
      session.isUnread = false
      session.unreadCount = 0
    }
    const timestamp = new Date().toISOString()
    session.messages.push({ role, content, senderOverride, timestamp })
    session.updatedAt = Date.now()
    saveSessions()
  }

  const addNodeMessage = (targetSessionId: string, targetNode: string, role: 'user' | 'agent', text: string) => {
    const timeStr = new Date().toLocaleTimeString()
    if (targetSessionId && targetNode) {
      let sess = sessions.value.find(s => s.id === targetSessionId)
      if (!sess) {
        sess = { id: targetSessionId, title: `Message from ${targetNode}`, messages: [], rtLogs: [], nodeHistories: {}, updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName: targetNode }
        sessions.value.unshift(sess)
      }
      if (!sess.senderName) sess.senderName = targetNode
      if (!sess.nodeHistories) sess.nodeHistories = {}
      if (!sess.nodeHistories[targetNode]) sess.nodeHistories[targetNode] = []
      sess.nodeHistories[targetNode].push({ role, text, timeStr })
      if (currentSessionId.value !== targetSessionId) { sess.isUnread = true; sess.unreadCount = (sess.unreadCount || 0) + 1 }
      else { sess.isUnread = false; sess.unreadCount = 0 }
      saveSessions()
    }
  }

  // ---- Multi-Agent WebSocket Management ----

  /** Build the WS message handler for a specific agent */
  const createMessageHandler = (agentId: string) => {
    return (data: any) => {
      try {
        if (typeof data === 'string') {
          try { data = JSON.parse(data) } catch {}
        }
        const agent = getAgentById(agentId)
        if (!agent) return

        if (data && data.type === 'chat' && data.content) {
          const isNodeMsg = data.metadata && data.metadata.is_node_message
          let senderName = agent.name
          let rtLogSenderName = agent.name
          if (data.metadata && data.metadata.is_node_message) {
            let nodeName = data.metadata.other_did || 'Node'
            if (nodeName !== 'Node') { const parts = nodeName.split(':'); nodeName = parts[parts.length - 1] || nodeName }
            senderName = nodeName
            rtLogSenderName = data.metadata.direction === 'in'
              ? `${nodeName} -> ${agent.name}`
              : `${agent.name} -> ${nodeName}`
          }

          const activeAgentId = getActiveAgentId()
          let targetSessionId: string | null = null

          // Get the current session for this specific agent
          if (agentId === activeAgentId) {
            targetSessionId = currentSessionId.value
          } else {
            targetSessionId = agentCurrentSessionMap.get(agentId) || null
          }

          if (data.metadata && data.metadata.Session_ID) targetSessionId = data.metadata.Session_ID
          else if (data.Session_ID || data.session_id) targetSessionId = data.Session_ID || data.session_id

          if (targetSessionId) {
            // Handle rtLogs for the correct agent
            if (agentId === activeAgentId) {
              let sess = sessions.value.find(s => s.id === targetSessionId)
              if (!sess) {
                sess = { id: targetSessionId, title: `Message from ${senderName}`, messages: [], rtLogs: [], nodeHistories: {}, updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName }
                sessions.value.unshift(sess)
              }
              if (!sess.senderName && senderName) {
                if (senderName !== agent.name) sess.senderName = senderName
              }
              if (!sess.rtLogs) sess.rtLogs = []
              const safeText = data.content.slice(0, 50).replace(/\n/g, ' ')
              sess.rtLogs.push({ senderName: rtLogSenderName, text: safeText })
              saveSessions()
            } else {
              const agentSessions = getSessionsForAgent(agentId)
              let sess = agentSessions.find(s => s.id === targetSessionId)
              if (!sess) {
                sess = { id: targetSessionId, title: `Message from ${senderName}`, messages: [], rtLogs: [], nodeHistories: {}, updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName }
                agentSessions.unshift(sess)
              }
              if (!sess.rtLogs) sess.rtLogs = []
              const safeText = data.content.slice(0, 50).replace(/\n/g, ' ')
              sess.rtLogs.push({ senderName: rtLogSenderName, text: safeText })
              saveSessionsForAgent(agentId, agentSessions)
            }
          }

          if (isNodeMsg) {
            let targetNode = data.metadata.other_did || data.session_id
            if (targetNode && targetNode.startsWith('LocalBroker:')) targetNode = targetNode.substring(12)
            const direction = data.metadata ? data.metadata.direction : 'in'
            const nodeRole = direction === 'out' ? 'user' : 'agent'
            addNodeMessageForAgent(agentId, targetSessionId || '', targetNode, nodeRole, data.content)
          } else {
            if (targetSessionId) addMessageToAgentSession(agentId, targetSessionId, 'agent', data.content, senderName)
          }
        }
      } catch (e) { console.error(`[WS] Message error for agent ${agentId}:`, e) }
    }
  }

  /** Connect WebSocket for a specific agent */
  const connectAgentWs = async (agentId: string) => {
    // Skip if already connected
    if (agentWsMap.has(agentId) && agentWsConnectedMap.get(agentId)) return

    const agent = getAgentById(agentId)
    if (!agent) return

    // Close existing connection if any
    const existing = agentWsMap.get(agentId)
    if (existing) {
      try { await existing.close() } catch {}
      agentWsMap.delete(agentId)
    }
    agentWsConnectedMap.set(agentId, false)

    const targetUrl = wsUrlForAgent(agent, '/ws')
    updateAgentStatus(agent.id, 'connecting')

    // Update badge if this is the active agent
    if (agentId === getActiveAgentId()) updateAgentStatusBadge('connecting')

    try {
      const conn = await createWs(targetUrl)
      agentWsMap.set(agentId, conn)
      agentWsConnectedMap.set(agentId, true)
      updateAgentStatus(agent.id, 'active')
      if (agentId === getActiveAgentId()) updateAgentStatusBadge('active')
      console.log(`[WS] Connected to ${agent.name} (${agentId})`)

      onWsOpen(conn, () => {
        agentWsConnectedMap.set(agentId, true)
        updateAgentStatus(agent.id, 'active')
        if (agentId === getActiveAgentId()) updateAgentStatusBadge('active')
        console.log(`[WS] Re-connected to ${agent.name}`)
      })

      onWsClose(conn, () => {
        agentWsConnectedMap.set(agentId, false)
        updateAgentStatus(agent.id, 'offline')
        if (agentId === getActiveAgentId()) updateAgentStatusBadge('offline')
        agentWsMap.delete(agentId)
      })

      onWsError(conn, (error) => {
        agentWsConnectedMap.set(agentId, false)
        updateAgentStatus(agent.id, 'offline')
        if (agentId === getActiveAgentId()) updateAgentStatusBadge('offline')
        console.error(`[WS] Error for ${agent.name}:`, error)
        agentWsMap.delete(agentId)
      })

      onWsMessage(conn, createMessageHandler(agentId))
    } catch (e) {
      console.error(`[WS] Failed to connect to ${agent.name}:`, e)
      updateAgentStatus(agent.id, 'offline')
      if (agentId === getActiveAgentId()) updateAgentStatusBadge('offline')
    }
  }

  /** Connect all registered agents concurrently */
  const connectAllAgents = () => {
    const allAgents = getAgents()
    allAgents.forEach(agent => {
      connectAgentWs(agent.id)
    })
  }

  const connectWebSocket = async () => {
    const agent = getActiveAgent()
    if (!agent) { updateAgentStatusBadge('offline'); return }
    await connectAgentWs(agent.id)
  }

  const checkAgentStatus = () => {
    const statusUrl = apiUrl('/api/status')
    if (!statusUrl || !getActiveAgent()) { updateAgentStatusBadge('offline'); return }
    const activeId = getActiveAgentId()
    apiFetch(statusUrl).then(result => {
      if (activeId && agentWsConnectedMap.get(activeId)) return
      updateAgentStatusBadge(result.ok && result.data?.status === 'active' ? 'connecting' : 'offline')
    }).catch(() => {
      if (activeId && !agentWsConnectedMap.get(activeId)) updateAgentStatusBadge('offline')
    })
  }

  const initAgentContext = () => {
    // Flush previous agent's sessions
    flushActiveSessions()

    // Load new active agent's sessions
    loadActiveSessions()

    const agent = getActiveAgent()
    if (agent) {
      // Check if WS is already connected for this agent
      if (agentWsConnectedMap.get(agent.id)) {
        updateAgentStatusBadge('active')
      } else {
        checkAgentStatus()
        connectAgentWs(agent.id)
      }
    } else {
      updateAgentStatusBadge('offline')
    }

    if (sessions.value.length > 0) {
      if (!currentSessionId.value || !sessions.value.find(s => s.id === currentSessionId.value)) {
        currentSessionId.value = sessions.value[0].id
      }
    } else {
      createSession('New Chat')
    }
  }

  const sendMessage = () => {
    const text = chatInput.value.trim()
    if (!text || !currentSessionId.value) return
    const agentId = getActiveAgentId()
    addMessageToSession(currentSessionId.value, 'user', text)
    if (agentId) {
      const conn = agentWsMap.get(agentId)
      const connected = agentWsConnectedMap.get(agentId)
      if (conn && connected) {
        conn.send(JSON.stringify({ type: 'chat', content: text, session_id: currentSessionId.value }))
      } else {
        console.warn('WebSocket not open for active agent')
      }
    }
    chatInput.value = ''
  }

  const loadSession = (id: string) => {
    const session = sessions.value.find(s => s.id === id)
    if (session) { session.isUnread = false; session.unreadCount = 0; saveSessions() }
    currentSessionId.value = id
  }

  const deleteSessionRecord = (id: string) => {
    sessions.value = sessions.value.filter(s => s.id !== id)
    if (currentSessionId.value === id) {
      currentSessionId.value = sessions.value.length > 0 ? sessions.value[0].id : null
      if (!currentSessionId.value) createSession('New Chat')
    }
    saveSessions()
  }

  const pinSessionRecord = (id: string) => {
    const session = sessions.value.find(s => s.id === id)
    if (session) { session.isPinned = !session.isPinned; saveSessions() }
  }

  const toggleBatchMode = () => {
    batchMode.value = !batchMode.value
    if (!batchMode.value) selectedSessionIds.clear()
  }

  const toggleSessionSelect = (id: string) => {
    if (selectedSessionIds.has(id)) selectedSessionIds.delete(id); else selectedSessionIds.add(id)
  }

  const toggleSelectAll = (checked: boolean) => {
    if (checked) sessions.value.forEach(s => selectedSessionIds.add(s.id)); else selectedSessionIds.clear()
  }

  const batchDeleteSessions = () => {
    if (selectedSessionIds.size === 0) return
    sessions.value = sessions.value.filter(s => !selectedSessionIds.has(s.id))
    if (selectedSessionIds.has(currentSessionId.value || '')) {
      currentSessionId.value = sessions.value.length > 0 ? sessions.value[0].id : null
      if (!currentSessionId.value) createSession('New Chat')
    }
    selectedSessionIds.clear()
    batchMode.value = false
    saveSessions()
  }

  const batchPinSessions = () => {
    if (selectedSessionIds.size === 0) return
    sessions.value.forEach(s => { if (selectedSessionIds.has(s.id) && !s.isPinned) s.isPinned = true })
    selectedSessionIds.clear()
    batchMode.value = false
    saveSessions()
  }

  const batchUnpinSessions = () => {
    if (selectedSessionIds.size === 0) return
    sessions.value.forEach(s => { if (selectedSessionIds.has(s.id) && s.isPinned) s.isPinned = false })
    selectedSessionIds.clear()
    batchMode.value = false
    saveSessions()
  }

  const filteredSessions = computed(() => {
    if (!searchQuery.value) return sessions.value
    return sessions.value.filter(s => s.title.toLowerCase().includes(searchQuery.value.toLowerCase()))
  })

  // Register agent switch callback only ONCE (module-level singleton)
  if (!agentSwitchRegistered) {
    agentSwitchRegistered = true
    onAgentSwitch(() => { initAgentContext() })
  }

  return {
    sessions,
    currentSessionId,
    currentSession,
    agentStatus,
    chatInput,
    batchMode,
    selectedSessionIds,
    searchQuery,
    totalUnread,
    filteredSessions,
    initAgentContext,
    createSession,
    loadSession,
    deleteSessionRecord,
    pinSessionRecord,
    sendMessage,
    renderMessageHtml,
    renderNodeMessageHtml,
    addMessageToSession,
    addNodeMessage,
    formatTime,
    getDateKey,
    formatDateLabel,
    toggleBatchMode,
    toggleSessionSelect,
    toggleSelectAll,
    batchDeleteSessions,
    batchPinSessions,
    batchUnpinSessions,
    connectWebSocket,
    connectAllAgents,
  }
}