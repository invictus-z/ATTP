<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { apiFetch } from '../transport'
import { useAttpProtocol } from '../composables/useAttpProtocol'
import {
  Shield, Plus, X, Pencil, Trash2, Loader2, Activity, ExternalLink,
  Search, GitMerge, AlertTriangle, FileText, RefreshCw,
  ChevronDown, ChevronRight, CheckCircle2, XCircle, Clock, Zap,
  Info, Layers, AlertOctagon, Eye, UserX, BarChart3, Target,
  Crosshair
} from 'lucide-vue-next'

  // ─── Types ───────────────────────────────────────────────────────────

  interface TraceNode {
    id: string
    name: string
    url: string
    status: 'online' | 'offline' | 'checking'
  }

  interface BehaviorChainEntry {
    id?: number
    hop_count: number[]
    field_type: string
    sender_type: string
    sender_did: string
    target_did: string
    content: string
    timestamp: string | null
  }

  interface BehaviorEntry {
    id?: number
    content: string
    target: string
    timestamp: string | null
    verification_status?: string
    node_type?: string
  }

  interface HopNode {
    hop_count: number[]
    node_did: string
    A2T: BehaviorEntry[]
    A2U: BehaviorEntry[]
    U2A: BehaviorEntry[]
    A2A: BehaviorEntry[]
    T2A: BehaviorEntry[]
  }

  interface AnalysisReport {
    id: number
    batch_index: number
    from_trace_id: number
    to_trace_id: number
    timestamp: string | null
    report: Record<string, any>
  }

  interface Alert {
    report_id: number
    batch_index: number
    verdict: string
    summary: string
    from_trace_id: number
    to_trace_id: number
    timestamp: string | null
    suspicious_nodes: SuspiciousNode[]
  }

  interface SuspiciousNode {
    node_did: string | null
    severity: string | null
    taint_score: number | null
    evidence: string | null
  }

  interface AggregateData {
    session_id: string
    intent: any
    traces: {
      chain: BehaviorChainEntry[]
      total_entries: number
      nodes?: HopNode[]
    }
    reports: AnalysisReport[]
    alerts: Alert[]
    total_batches: number
    total_alerts: number
  }

  interface AnalysisStatus {
    status: string
    session_id?: string
    phase?: string
    progress?: number
  }

  // 恶意节点相关类型
  interface MaliciousReport {
    id: number
    source: string
    target_did: string
    node_type: string
    session_id: string
    evidence_type: string
    severity: string
    taint_score: number
    evidence_description: string
    nonce: string
    report_id: number | null
    timestamp: number
    raw_evidence: Record<string, any>
  }

  interface MaliciousDossier {
    found: boolean
    did: string
    total_violations: number
    severity_level: string  // clean / warning / dangerous / banned
    first_seen_at: number
    last_seen_at: number
    evidence_breakdown: Record<string, number>
    last_evidence_type: string
    last_session_id: string
    last_evidence_desc: string
    incidents: MaliciousReport[]
  }

  // 横向分析相关类型
  interface HorizontalReport {
    id: number
    batch_index: number
    from_trace_id: number
    to_trace_id: number
    sessions_scanned: number
    timestamp: string | null
    report: Record<string, any>
  }

  interface HorizontalState {
    did: string
    accumulated_count: number
    last_trace_id: number
    batch_index: number
    node_type?: string
    has_context: boolean
  }

  interface IntentDescriptor {
    original_task: string
    core_objective: string
    constraints: string[]
    involved_capabilities: string[]
    risk_level: string  // low / medium / high
  }

// ─── Node Management State ───────────────────────────────────────────

const { userConfig, addProtocolNode: configAddProtocolNode, updateProtocolNode: configUpdateProtocolNode, removeProtocolNode: configRemoveProtocolNode, saveProtocolNodes: configSaveProtocolNodes } = useAttpProtocol()

const traceNodes = ref<TraceNode[]>([])
const nodePanelOpen = ref(false)
const showAddModal = ref(false)
const showEditModal = ref(false)
const newNodeName = ref('')
const newNodeUrl = ref('http://localhost:9000')
const editNodeName = ref('')
const editNodeUrl = ref('')
const editingNodeId = ref<string | null>(null)

// ─── Query State ─────────────────────────────────────────────────────

const selectedNodeId = ref<string | null>(null)
const sessionIdInput = ref('')
const loading = ref(false)
const activeTab = ref<'aggregate' | 'behavior' | 'reports' | 'alerts' | 'malicious' | 'horizontal'>('aggregate')
const queryMode = ref<'vertical' | 'horizontal'>('vertical')

// ─── Data State ──────────────────────────────────────────────────────

const aggregateData = ref<AggregateData | null>(null)
const behaviorData = ref<{ session_id: string; nodes: HopNode[] } | null>(null)
const reportsData = ref<{ session_id: string; reports: AnalysisReport[]; total_batches: number } | null>(null)
const analysisStatus = ref<AnalysisStatus | null>(null)
const triggerLoading = ref(false)

// 恶意节点
const maliciousData = ref<{ session_id: string; reports: MaliciousReport[]; total: number } | null>(null)
const dossiersData = ref<{ total: number; dossiers: MaliciousDossier[] } | null>(null)
const maliciousSourceFilter = ref<string>('')

// 横向分析
const horizontalDidInput = ref('')
const horizontalReports = ref<HorizontalReport[]>([])
const horizontalState = ref<HorizontalState | null>(null)
const horizontalLoading = ref(false)
const horizontalTriggerLoading = ref(false)
const horizontalStatus = ref<{ status: string; did: string } | null>(null)

// ─── Toast ───────────────────────────────────────────────────────────

const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error'>('success')

const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
  toastMessage.value = msg
  toastType.value = type
  toastVisible.value = true
  setTimeout(() => { toastVisible.value = false }, 2500)
}

// ─── Node CRUD ───────────────────────────────────────────────────────

const loadNodes = () => {
  const stored = userConfig.protocolNodes || []
  traceNodes.value = stored.map((n, i) => ({
    id: 'trace_' + i + '_' + n.url.replace(/[^a-zA-Z0-9]/g, '_'),
    name: n.name,
    url: n.url,
    status: 'checking' as const,
  }))
}

const saveNodes = async () => {
  await configSaveProtocolNodes(traceNodes.value.map(({ name, url }) => ({ name, url })))
}

const checkNodeStatus = async (node: TraceNode) => {
  node.status = 'checking'
  try {
    const result = await apiFetch(`${node.url}/api/status`)
    node.status = result.ok ? 'online' : 'offline'
  } catch {
    node.status = 'offline'
  }
}

const checkAllNodes = () => {
  traceNodes.value.forEach(node => checkNodeStatus(node))
}

const addNode = async () => {
  const name = newNodeName.value.trim()
  const url = newNodeUrl.value.trim().replace(/\/$/, '')
  if (!name || !url) return
  const id = 'trace_' + Date.now().toString()
  const node: TraceNode = { id, name, url, status: 'checking' }
  traceNodes.value.push(node)
  await saveNodes()
  checkNodeStatus(node)
  newNodeName.value = ''
  newNodeUrl.value = 'http://localhost:9000'
  showAddModal.value = false
  showToast(`溯源节点「${name}」已添加`)
}

const openEditModal = (node: TraceNode) => {
  editingNodeId.value = node.id
  editNodeName.value = node.name
  editNodeUrl.value = node.url
  showEditModal.value = true
}

const saveEditNode = async () => {
  const name = editNodeName.value.trim()
  const url = editNodeUrl.value.trim().replace(/\/$/, '')
  if (!name || !url || !editingNodeId.value) return
  const idx = traceNodes.value.findIndex(n => n.id === editingNodeId.value)
  if (idx >= 0) {
    traceNodes.value[idx].name = name
    traceNodes.value[idx].url = url
    traceNodes.value[idx].status = 'checking'
    await saveNodes()
    checkNodeStatus(traceNodes.value[idx])
    showToast(`溯源节点「${name}」已更新`)
  }
  showEditModal.value = false
  editingNodeId.value = null
}

const removeNode = async (id: string) => {
  const node = traceNodes.value.find(n => n.id === id)
  traceNodes.value = traceNodes.value.filter(n => n.id !== id)
  await saveNodes()
  if (node) showToast(`溯源节点「${node.name}」已移除`)
}

const testConnection = async (node: TraceNode) => {
  await checkNodeStatus(node)
  showToast(
    node.status === 'online' ? `「${node.name}」连接成功` : `「${node.name}」连接失败`,
    node.status === 'online' ? 'success' : 'error'
  )
}

// ─── Selected Node Helper ────────────────────────────────────────────

const selectedNode = computed(() => traceNodes.value.find(n => n.id === selectedNodeId.value) || null)

const buildUrl = (path: string) => {
  if (!selectedNode.value) return ''
  return `${selectedNode.value.url.replace(/\/+$/, '')}${path}`
}

// ─── Data Transformation ──────────────────────────────────────────────

const transformChainToNodes = (chain: BehaviorChainEntry[]): HopNode[] => {
  const nodeMap = new Map<string, HopNode>()
  
  chain.forEach(entry => {
    const key = `${entry.hop_count.join('.')}_${entry.sender_did}`
    
    if (!nodeMap.has(key)) {
      nodeMap.set(key, {
        hop_count: entry.hop_count,
        node_did: entry.sender_did,
        A2T: [],
        A2U: [],
        U2A: [],
        A2A: [],
        T2A: [],
      })
    }
    
    const node = nodeMap.get(key)!
    const behaviorEntry: BehaviorEntry = {
      id: entry.id,
      content: entry.content,
      target: entry.target_did,
      timestamp: entry.timestamp,
    }
    
    if (entry.field_type === 'A2T') node.A2T.push(behaviorEntry)
    else if (entry.field_type === 'A2U') node.A2U.push(behaviorEntry)
    else if (entry.field_type === 'U2A') node.U2A.push(behaviorEntry)
    else if (entry.field_type === 'A2A') node.A2A.push(behaviorEntry)
    else if (entry.field_type === 'T2A') node.T2A.push(behaviorEntry)
  })
  
  return Array.from(nodeMap.values()).sort((a, b) => {
    const [a0, a1] = a.hop_count
    const [b0, b1] = b.hop_count
    if (a0 !== b0) return a0 - b0
    return a1 - b1
  })
}

// ─── Data Fetching ───────────────────────────────────────────────────

const fetchAggregate = async () => {
  if (!selectedNode.value || !sessionIdInput.value.trim()) return
  loading.value = true
  try {
    const url = buildUrl(`/api/analysis/aggregate/${sessionIdInput.value.trim()}?protocol_node_address=${encodeURIComponent(selectedNode.value.url)}`)
    const result = await apiFetch(url)
    if (result.ok) {
      const rawData = result.data as AggregateData
      const nodes = transformChainToNodes(rawData.traces.chain)
      aggregateData.value = {
        ...rawData,
        traces: { ...rawData.traces, nodes },
      }
    } else {
      showToast('获取综合数据失败', 'error')
    }
  } catch (e) {
    console.error('Aggregate fetch error:', e)
    showToast('请求失败', 'error')
  } finally {
    loading.value = false
  }
}

const fetchBehavior = async () => {
  if (!selectedNode.value || !sessionIdInput.value.trim()) return
  loading.value = true
  try {
    const url = buildUrl(`/api/behavior/${sessionIdInput.value.trim()}?protocol_node_address=${encodeURIComponent(selectedNode.value.url)}`)
    const result = await apiFetch(url)
    if (result.ok) {
      const rawData = result.data as { session_id: string; chain: BehaviorChainEntry[]; protocol_node_address?: string }
      const nodes = transformChainToNodes(rawData.chain)
      behaviorData.value = { session_id: rawData.session_id, nodes }
    } else {
      showToast('获取行为溯源数据失败', 'error')
    }
  } catch (e) {
    console.error('Behavior fetch error:', e)
    showToast('请求失败', 'error')
  } finally {
    loading.value = false
  }
}

const fetchReports = async () => {
  if (!selectedNode.value || !sessionIdInput.value.trim()) return
  loading.value = true
  try {
    const url = buildUrl(`/api/analysis/${sessionIdInput.value.trim()}`)
    const result = await apiFetch(url)
    if (result.ok) {
      reportsData.value = result.data
    } else {
      showToast('获取分析报告失败', 'error')
    }
  } catch (e) {
    console.error('Reports fetch error:', e)
    showToast('请求失败', 'error')
  } finally {
    loading.value = false
  }
}

// 恶意节点
const fetchMalicious = async () => {
  if (!selectedNode.value || !sessionIdInput.value.trim()) return
  loading.value = true
  try {
    let path = `/api/malicious/session/${sessionIdInput.value.trim()}`
    if (maliciousSourceFilter.value) path += `?source=${maliciousSourceFilter.value}`
    const url = buildUrl(path)
    const result = await apiFetch(url)
    if (result.ok) {
      maliciousData.value = result.data
    } else {
      showToast('获取恶意节点数据失败', 'error')
    }
  } catch (e) {
    console.error('Malicious fetch error:', e)
    showToast('请求失败', 'error')
  } finally {
    loading.value = false
  }
}

const fetchDossiers = async () => {
  if (!selectedNode.value) return
  try {
    const url = buildUrl('/api/malicious/dossiers')
    const result = await apiFetch(url)
    if (result.ok) {
      dossiersData.value = result.data
    }
  } catch (e) {
    console.error('Dossiers fetch error:', e)
  }
}

// 横向分析
const fetchHorizontalReport = async () => {
  if (!selectedNode.value || !horizontalDidInput.value.trim()) return
  horizontalLoading.value = true
  try {
    const url = buildUrl(`/api/analysis/horizontal/report/${encodeURIComponent(horizontalDidInput.value.trim())}`)
    const result = await apiFetch(url)
    if (result.ok) {
      horizontalReports.value = result.data.reports || []
    } else {
      showToast('获取横向分析报告失败', 'error')
    }
  } catch (e) {
    console.error('Horizontal report fetch error:', e)
    showToast('请求失败', 'error')
  } finally {
    horizontalLoading.value = false
  }
}

const fetchHorizontalState = async () => {
  if (!selectedNode.value || !horizontalDidInput.value.trim()) return
  try {
    const url = buildUrl(`/api/analysis/horizontal/state/${encodeURIComponent(horizontalDidInput.value.trim())}`)
    const result = await apiFetch(url)
    if (result.ok) {
      horizontalState.value = result.data
    }
  } catch {
    horizontalState.value = null
  }
}

const triggerHorizontalAnalysis = async () => {
  if (!selectedNode.value || !horizontalDidInput.value.trim()) return
  horizontalTriggerLoading.value = true
  try {
    const url = buildUrl(`/api/analysis/horizontal/trigger/${encodeURIComponent(horizontalDidInput.value.trim())}`)
    const result = await apiFetch(url, { method: 'POST' })
    if (result.ok && result.data?.triggered) {
      showToast('横向分析已触发', 'success')
      fetchHorizontalState()
    } else {
      showToast(result.data?.reason === 'analysis_disabled' ? '分析功能未启用' : '触发失败', 'error')
    }
  } catch {
    showToast('触发横向分析请求失败', 'error')
  } finally {
    horizontalTriggerLoading.value = false
  }
}

const queryHorizontal = () => {
  fetchHorizontalReport()
  fetchHorizontalState()
}

const fetchAnalysisStatus = async () => {
  if (!selectedNode.value || !sessionIdInput.value.trim()) return
  try {
    const url = buildUrl(`/api/analysis/status/${sessionIdInput.value.trim()}`)
    const result = await apiFetch(url)
    if (result.ok) {
      analysisStatus.value = result.data
    }
  } catch {
    analysisStatus.value = null
  }
}

const triggerAnalysis = async () => {
  if (!selectedNode.value || !sessionIdInput.value.trim()) return
  triggerLoading.value = true
  try {
    const url = buildUrl(`/api/analysis/trigger/${sessionIdInput.value.trim()}`)
    const result = await apiFetch(url, { method: 'POST' })
    if (result.ok && result.data?.triggered) {
      showToast('污点分析已触发', 'success')
      fetchAnalysisStatus()
    } else {
      showToast(result.data?.reason === 'analysis_disabled' ? '分析功能未启用' : '触发失败', 'error')
    }
  } catch {
    showToast('触发分析请求失败', 'error')
  } finally {
    triggerLoading.value = false
  }
}

const doQuery = () => {
  aggregateData.value = null
  behaviorData.value = null
  reportsData.value = null
  analysisStatus.value = null
  maliciousData.value = null

  if (activeTab.value === 'aggregate') fetchAggregate()
  else if (activeTab.value === 'behavior') fetchBehavior()
  else if (activeTab.value === 'reports') fetchReports()
  else if (activeTab.value === 'alerts') fetchAggregate()
  else if (activeTab.value === 'malicious') { fetchMalicious(); fetchDossiers() }
  else if (activeTab.value === 'horizontal') { /* 横向需要手动输入 DID */ }
}

const switchTab = (tab: typeof activeTab.value) => {
  activeTab.value = tab
  // 仅对需要 session_id 的 tab 自动查询（如果已有 session_id）
  // 横向分析和恶意节点档案不需要 session_id
  if (tab === 'malicious') {
    if (sessionIdInput.value.trim()) fetchMalicious()
    fetchDossiers()
  } else if (tab === 'horizontal') {
    // 横向分析有独立查询按钮，不自动查询
  } else if (sessionIdInput.value.trim()) {
    doQuery()
  }
}

// ─── Computed helpers ────────────────────────────────────────────────

const alerts = computed(() => aggregateData.value?.alerts || [])

const fieldTypes = ['A2T', 'A2U', 'U2A', 'A2A', 'T2A'] as const

const fieldTypeConfig: Record<string, { label: string; color: string; bg: string; border: string }> = {
  A2T: { label: 'Agent→Tool', color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200' },
  A2U: { label: 'Agent→User', color: 'text-purple-600', bg: 'bg-purple-50', border: 'border-purple-200' },
  U2A: { label: 'User→Agent', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  A2A: { label: 'Agent→Agent', color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200' },
  T2A: { label: 'Tool→Agent', color: 'text-cyan-600', bg: 'bg-cyan-50', border: 'border-cyan-200' },
}

const verificationBadge = (status?: string) => {
  if (!status) return { text: '未知', cls: 'bg-gray-100 text-gray-500 border-gray-200' }
  if (status === 'verified') return { text: '已验证', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (status === 'unverified') return { text: '未验证', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (status === 'tampered') return { text: '已篡改', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: status, cls: 'bg-gray-100 text-gray-500 border-gray-200' }
}

const verdictBadge = (verdict: string) => {
  if (verdict === 'clean') return { text: 'Clean', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (verdict === 'suspicious') return { text: 'Suspicious', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (verdict === 'malicious') return { text: 'Malicious', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: verdict, cls: 'bg-gray-100 text-gray-500 border-gray-200' }
}

const severityBadge = (sev: string) => {
  if (sev === 'low') return { cls: 'bg-blue-50 text-blue-600 border-blue-200' }
  if (sev === 'medium') return { cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (sev === 'high') return { cls: 'bg-red-50 text-red-600 border-red-200' }
  return { cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

const severityLevelBadge = (level: string) => {
  if (level === 'clean') return { text: 'Clean', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (level === 'warning') return { text: 'Warning', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (level === 'dangerous') return { text: 'Dangerous', cls: 'bg-orange-50 text-orange-600 border-orange-200' }
  if (level === 'banned') return { text: 'Banned', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: level, cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

const riskLevelBadge = (level: string) => {
  if (level === 'low') return { text: 'Low', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (level === 'medium') return { text: 'Medium', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (level === 'high') return { text: 'High', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: level, cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

const sourceBadge = (source: string) => {
  if (source === 'protocol_review') return { text: '协议审查', cls: 'bg-blue-50 text-blue-600 border-blue-200' }
  if (source === 'vertical_analysis') return { text: '纵向分析', cls: 'bg-purple-50 text-purple-600 border-purple-200' }
  if (source === 'horizontal_analysis') return { text: '横向分析', cls: 'bg-orange-50 text-orange-600 border-orange-200' }
  return { text: source, cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

const formatTime = (ts: string | number | null) => {
  if (!ts) return '--'
  try {
    const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(ts)
  }
}

const formatDid = (did: string) => {
  if (!did) return '--'
  const parts = did.split(':')
  return parts.length > 1 ? parts[parts.length - 1] : did
}

// 解析 intent
const intentInfo = computed<IntentDescriptor | null>(() => {
  const intent = aggregateData.value?.intent
  if (!intent) return null
  // intent 可能直接是 IntentDescriptor 或包裹在 intent 字段中
  if (intent.original_task) return intent as IntentDescriptor
  if (intent.intent && intent.intent.original_task) return intent.intent as IntentDescriptor
  return null
})

// ─── Lifecycle ───────────────────────────────────────────────────────

const route = useRoute()

onMounted(() => {
  loadNodes()
  checkAllNodes()

  const querySessionId = route.query.sessionId as string | undefined
  const queryProtocolUrl = route.query.protocolNodeUrl as string | undefined

  if (querySessionId) {
    sessionIdInput.value = querySessionId
  }

  setTimeout(() => {
    if (queryProtocolUrl) {
      const normalizedUrl = queryProtocolUrl.replace(/\/+$/, '')
      const matchedNode = traceNodes.value.find(n => n.url.replace(/\/+$/, '') === normalizedUrl)
      if (matchedNode) {
        selectedNodeId.value = matchedNode.id
      }
    }

    if (!selectedNodeId.value) {
      const first = traceNodes.value.find(n => n.status === 'online')
      if (first) selectedNodeId.value = first.id
    }

    if (querySessionId && selectedNodeId.value) {
      doQuery()
    }
  }, 2000)
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-5xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">溯源模块</h2>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200">{{ traceNodes.length }} 节点</span>
        </div>
        <p class="text-sm text-gray-500">行为溯源 · 语义污点分析 · 恶意检测 · 审计追踪</p>
      </div>
    </header>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto relative">
      <div class="max-w-5xl mx-auto p-8 space-y-6 pb-8">

        <!-- ── Node Management Panel (collapsed) ── -->
        <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div
            @click="nodePanelOpen = !nodePanelOpen"
            class="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50/50 transition-colors cursor-pointer select-none"
          >
            <div class="flex items-center gap-3">
              <component :is="nodePanelOpen ? ChevronDown : ChevronRight" class="w-4 h-4 text-gray-400" />
              <span class="text-[13px] font-medium text-gray-700">溯源节点管理</span>
              <span class="text-[11px] text-gray-400">{{ traceNodes.filter(n => n.status === 'online').length }} / {{ traceNodes.length }} 在线</span>
            </div>
            <button
              @click.stop="showAddModal = true"
              class="px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 hover:border-gray-300 transition-colors flex items-center gap-1"
            >
              <Plus class="w-3.5 h-3.5" /> 添加
            </button>
          </div>

          <div v-if="nodePanelOpen" class="border-t border-gray-100 px-5 py-4 space-y-3">
            <div class="flex items-center justify-between mb-2">
              <button @click="checkAllNodes" class="px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
                <Activity class="w-3.5 h-3.5" /> 检测全部
              </button>
            </div>
            <div v-for="node in traceNodes" :key="node.id"
              class="group flex items-center justify-between p-3 bg-gray-50/50 rounded-xl border border-gray-100 hover:border-gray-200 transition-all"
            >
              <div class="flex items-center gap-3 flex-1 min-w-0">
                <div class="w-9 h-9 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0">
                  <Shield class="w-4 h-4 text-indigo-600" />
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-[13px] font-medium text-gray-800 truncate">{{ node.name }}</span>
                    <span v-if="node.status === 'online'" class="px-1.5 py-0.5 rounded text-[9px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100">Online</span>
                    <span v-else-if="node.status === 'offline'" class="px-1.5 py-0.5 rounded text-[9px] font-medium text-amber-600 bg-amber-50 border border-amber-100">Offline</span>
                    <span v-else class="px-1.5 py-0.5 rounded text-[9px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-0.5"><Loader2 class="w-2.5 h-2.5 animate-spin" />检测中</span>
                  </div>
                  <div class="text-[11px] text-gray-400 font-mono truncate">{{ node.url }}</div>
                </div>
              </div>
              <div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button @click="testConnection(node)" class="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors" title="测试"><ExternalLink class="w-3.5 h-3.5" /></button>
                <button @click="openEditModal(node)" class="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors" title="编辑"><Pencil class="w-3.5 h-3.5" /></button>
                <button @click="removeNode(node.id)" class="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors" title="删除"><Trash2 class="w-3.5 h-3.5" /></button>
              </div>
            </div>
            <div v-if="traceNodes.length === 0" class="text-center py-6 text-gray-400 text-[13px]">
              暂无溯源节点，请先添加
            </div>
          </div>
        </div>

        <!-- ── Query Bar ── -->
        <div class="bg-white rounded-2xl border border-gray-200 p-5">
          <!-- Row 1: Node select + Mode toggle -->
          <div class="flex items-center gap-3 flex-wrap">
            <div class="flex-1 min-w-[200px]">
              <label class="block text-[11px] font-medium text-gray-400 mb-1.5">溯源节点</label>
              <select v-model="selectedNodeId" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors appearance-none">
                <option :value="null" disabled>选择溯源节点...</option>
                <option v-for="node in traceNodes" :key="node.id" :value="node.id">
                  {{ node.name }} ({{ node.status === 'online' ? '●' : '○' }} {{ node.url }})
                </option>
              </select>
            </div>
            <div class="flex items-end">
              <div class="flex bg-gray-100 rounded-xl p-1">
                <button
                  @click="queryMode = 'vertical'"
                  :class="[
                    'px-3 py-2 text-[12px] rounded-lg transition-colors font-medium flex items-center gap-1',
                    queryMode === 'vertical' ? 'bg-white text-gray-900 shadow-sm border border-gray-200' : 'text-gray-500 hover:text-gray-700'
                  ]"
                ><Search class="w-3.5 h-3.5" /> 纵向分析</button>
                <button
                  @click="queryMode = 'horizontal'"
                  :class="[
                    'px-3 py-2 text-[12px] rounded-lg transition-colors font-medium flex items-center gap-1',
                    queryMode === 'horizontal' ? 'bg-white text-gray-900 shadow-sm border border-gray-200' : 'text-gray-500 hover:text-gray-700'
                  ]"
                ><Crosshair class="w-3.5 h-3.5" /> 横向分析</button>
              </div>
            </div>
          </div>

          <!-- Row 2: Input + Buttons -->
          <div class="flex items-center gap-3 flex-wrap mt-3 pt-3 border-t border-gray-100">
            <div class="flex-[2] min-w-[280px]">
              <label class="block text-[11px] font-medium text-gray-400 mb-1.5">
                {{ queryMode === 'vertical' ? '纵向分析 — Session ID' : '横向分析 — 节点 DID' }}
              </label>
              <div class="relative">
                <Search v-if="queryMode === 'vertical'" class="w-4 h-4 text-gray-400 absolute left-3 top-2.5 pointer-events-none" />
                <Crosshair v-else class="w-4 h-4 text-gray-400 absolute left-3 top-2.5 pointer-events-none" />
                <input
                  v-show="queryMode === 'vertical'"
                  v-model="sessionIdInput"
                  placeholder="输入 Session ID 进行溯源查询"
                  class="w-full pl-9 pr-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors font-mono placeholder:text-gray-300"
                  @keydown.enter="doQuery()"
                />
                <input
                  v-show="queryMode === 'horizontal'"
                  v-model="horizontalDidInput"
                  placeholder="输入节点 DID 进行横向分析"
                  class="w-full pl-9 pr-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors font-mono placeholder:text-gray-300"
                  @keydown.enter="queryHorizontal()"
                />
              </div>
            </div>
            <div class="flex items-end gap-2">
              <button
                @click="queryMode === 'vertical' ? doQuery() : queryHorizontal()"
                :disabled="!selectedNodeId || (queryMode === 'vertical' ? (!sessionIdInput.trim() || loading) : (!horizontalDidInput.trim() || horizontalLoading))"
                class="px-5 py-2.5 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Loader2 v-if="loading || horizontalLoading" class="w-4 h-4 animate-spin" />
                <Search v-else class="w-4 h-4" />
                查询
              </button>
              <button
                v-if="queryMode === 'horizontal'"
                @click="triggerHorizontalAnalysis"
                :disabled="!selectedNodeId || !horizontalDidInput.trim() || horizontalTriggerLoading"
                class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Loader2 v-if="horizontalTriggerLoading" class="w-4 h-4 animate-spin" />
                <Zap v-else class="w-4 h-4" />
                触发分析
              </button>
              <button
                v-if="queryMode === 'vertical'"
                @click="triggerAnalysis"
                :disabled="triggerLoading || !selectedNodeId || !sessionIdInput.trim()"
                class="px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-xl hover:bg-indigo-700 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Loader2 v-if="triggerLoading" class="w-4 h-4 animate-spin" />
                <Zap v-else class="w-4 h-4" />
                触发分析
              </button>
            </div>
          </div>
        </div>

        <!-- ── No Node Selected State ── -->
        <div v-if="!selectedNodeId" class="flex flex-col items-center justify-center py-20 text-gray-400">
          <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
            <Shield class="w-8 h-8 text-gray-300" />
          </div>
          <p class="text-sm">请先选择一个溯源节点</p>
        </div>

        <!-- ── Loading ── -->
        <div v-if="loading" class="flex items-center justify-center py-20 text-gray-400">
          <Loader2 class="w-5 h-5 animate-spin mr-2" />
          <span class="text-sm">正在查询溯源数据...</span>
        </div>

        <!-- ── Data Display (always visible when node selected) ── -->
        <template v-if="selectedNodeId && !loading">
          <!-- Tab Bar — Vertical mode tabs -->
          <template v-if="queryMode === 'vertical'">
            <div class="flex items-center gap-1 bg-gray-100/60 rounded-xl p-1 flex-wrap">
              <button
                v-for="tab in ([
                  { key: 'aggregate', label: '综合视图', icon: Layers, count: aggregateData ? (aggregateData.traces?.total_entries ?? 0) : null },
                  { key: 'behavior', label: '行为溯源', icon: GitMerge, count: behaviorData ? behaviorData.nodes?.length ?? 0 : null },
                  { key: 'reports', label: '分析报告', icon: FileText, count: reportsData ? reportsData.total_batches : null },
                  { key: 'alerts', label: '告警', icon: AlertTriangle, count: aggregateData ? aggregateData.total_alerts : null },
                  { key: 'malicious', label: '恶意节点', icon: UserX, count: maliciousData ? maliciousData.total : null },
                ] as const)"
                :key="tab.key"
                @click="switchTab(tab.key as any)"
                :class="[
                  'flex items-center gap-1.5 px-4 py-2 text-[13px] rounded-lg transition-colors font-medium',
                  activeTab === tab.key
                    ? 'bg-white text-gray-900 shadow-sm border border-gray-200'
                    : 'text-gray-500 hover:text-gray-700'
                ]"
              >
                <component :is="tab.icon" class="w-3.5 h-3.5" />
                <span>{{ tab.label }}</span>
                <span v-if="tab.count !== null && tab.count > 0" class="px-1.5 py-0.5 rounded-full text-[10px] font-medium"
                  :class="tab.key === 'alerts' && tab.count > 0 ? 'bg-red-100 text-red-600' : tab.key === 'malicious' && tab.count > 0 ? 'bg-red-100 text-red-600' : 'bg-gray-200 text-gray-600'"
                >{{ tab.count }}</span>
              </button>
            </div>
          </template>

          <!-- Tab Bar — Horizontal mode tabs -->
          <template v-else>
            <div class="flex items-center gap-1 bg-gray-100/60 rounded-xl p-1">
              <button
                class="flex items-center gap-1.5 px-4 py-2 text-[13px] rounded-lg bg-white text-gray-900 shadow-sm border border-gray-200 font-medium"
              >
                <BarChart3 class="w-3.5 h-3.5" />
                <span>横向分析</span>
                <span v-if="horizontalReports.length > 0" class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-purple-100 text-purple-600">{{ horizontalReports.length }}</span>
              </button>
            </div>
          </template>

          <!-- ── Vertical Analysis Content ── -->
          <template v-if="queryMode === 'vertical'">

          <!-- ── Aggregate Tab ── -->
          <div v-if="activeTab === 'aggregate' && aggregateData" class="space-y-5">
            <!-- Stats Cards -->
            <div class="grid grid-cols-4 gap-4">
              <div class="bg-white rounded-xl border border-gray-200 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <div class="w-8 h-8 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center">
                    <GitMerge class="w-4 h-4 text-blue-600" />
                  </div>
                  <span class="text-[11px] font-medium text-gray-400 uppercase">Trace Entries</span>
                </div>
                <div class="text-2xl font-semibold text-gray-900">{{ aggregateData.traces?.total_entries ?? 0 }}</div>
              </div>
              <div class="bg-white rounded-xl border border-gray-200 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <div class="w-8 h-8 rounded-lg bg-purple-50 border border-purple-100 flex items-center justify-center">
                    <Layers class="w-4 h-4 text-purple-600" />
                  </div>
                  <span class="text-[11px] font-medium text-gray-400 uppercase">Hop Nodes</span>
                </div>
                <div class="text-2xl font-semibold text-gray-900">{{ aggregateData.traces?.nodes?.length ?? 0 }}</div>
              </div>
              <div class="bg-white rounded-xl border border-gray-200 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <div class="w-8 h-8 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center">
                    <FileText class="w-4 h-4 text-emerald-600" />
                  </div>
                  <span class="text-[11px] font-medium text-gray-400 uppercase">Reports</span>
                </div>
                <div class="text-2xl font-semibold text-gray-900">{{ aggregateData.total_batches }}</div>
              </div>
              <div class="bg-white rounded-xl border border-gray-200 p-4">
                <div class="flex items-center gap-2 mb-2">
                  <div class="w-8 h-8 rounded-lg bg-red-50 border border-red-100 flex items-center justify-center">
                    <AlertTriangle class="w-4 h-4 text-red-600" />
                  </div>
                  <span class="text-[11px] font-medium text-gray-400 uppercase">Alerts</span>
                </div>
                <div class="text-2xl font-semibold" :class="aggregateData.total_alerts > 0 ? 'text-red-600' : 'text-gray-900'">
                  {{ aggregateData.total_alerts }}
                </div>
              </div>
            </div>

            <!-- Intent Info — 结构化渲染 -->
            <div v-if="intentInfo" class="bg-white rounded-xl border border-gray-200 p-5">
              <div class="flex items-center gap-2 mb-4">
                <Target class="w-4 h-4 text-indigo-500" />
                <span class="text-[13px] font-semibold text-gray-800">意图信息</span>
                <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', riskLevelBadge(intentInfo.risk_level).cls]">
                  {{ riskLevelBadge(intentInfo.risk_level).text }} Risk
                </span>
              </div>

              <div class="space-y-3">
                <!-- Original Task -->
                <div>
                  <div class="text-[11px] font-medium text-gray-400 mb-1">用户原始输入</div>
                  <div class="bg-gray-50 rounded-lg px-3 py-2 text-[13px] text-gray-800 leading-relaxed">{{ intentInfo.original_task }}</div>
                </div>

                <!-- Core Objective -->
                <div>
                  <div class="text-[11px] font-medium text-gray-400 mb-1">核心目标</div>
                  <div class="bg-indigo-50/50 rounded-lg px-3 py-2 text-[13px] text-indigo-700 leading-relaxed">{{ intentInfo.core_objective }}</div>
                </div>

                <!-- Constraints & Capabilities -->
                <div class="grid grid-cols-2 gap-4">
                  <div v-if="intentInfo.constraints?.length">
                    <div class="text-[11px] font-medium text-gray-400 mb-1.5">约束条件</div>
                    <div class="space-y-1">
                      <div v-for="(c, i) in intentInfo.constraints" :key="i"
                        class="flex items-start gap-1.5 text-[12px] text-gray-600"
                      >
                        <span class="w-1 h-1 rounded-full bg-gray-400 mt-1.5 shrink-0"></span>
                        {{ c }}
                      </div>
                    </div>
                  </div>
                  <div v-if="intentInfo.involved_capabilities?.length">
                    <div class="text-[11px] font-medium text-gray-400 mb-1.5">涉及能力域</div>
                    <div class="flex flex-wrap gap-1.5">
                      <span v-for="(cap, i) in intentInfo.involved_capabilities" :key="i"
                        class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-blue-50 text-blue-600 border border-blue-200"
                      >{{ cap }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Fallback: raw intent if not parseable -->
            <div v-else-if="aggregateData.intent" class="bg-white rounded-xl border border-gray-200 p-5">
              <div class="flex items-center gap-2 mb-3">
                <Info class="w-4 h-4 text-indigo-500" />
                <span class="text-[13px] font-semibold text-gray-800">意图信息（原始）</span>
              </div>
              <div class="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 font-mono whitespace-pre-wrap">{{ JSON.stringify(aggregateData.intent, null, 2) }}</div>
            </div>

            <!-- Behavior Chain Overview -->
            <div v-if="aggregateData.traces?.nodes?.length" class="bg-white rounded-xl border border-gray-200 p-5">
              <div class="flex items-center gap-2 mb-4">
                <GitMerge class="w-4 h-4 text-indigo-500" />
                <span class="text-[13px] font-semibold text-gray-800">行为链路概览</span>
                <span class="text-[11px] text-gray-400">{{ aggregateData.traces.nodes.length }} hops</span>
              </div>
              <div class="space-y-3">
                <div v-for="node in aggregateData.traces.nodes" :key="node.hop_count.join('.')"
                  class="flex items-start gap-3 p-3 bg-gray-50/50 rounded-xl border border-gray-100"
                >
                  <div class="w-8 h-8 rounded-full bg-white border border-gray-200 flex items-center justify-center shrink-0 text-[12px] font-semibold text-gray-600 shadow-sm">
                    {{ node.hop_count[0] }}.{{ node.hop_count[1] }}
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="text-[12px] font-mono text-gray-500 mb-2 truncate" :title="node.node_did">{{ formatDid(node.node_did) }}</div>
                    <div class="flex flex-wrap gap-1.5">
                      <template v-for="ft in fieldTypes" :key="ft">
                        <span v-if="node[ft] && node[ft].length > 0"
                          :class="['px-2 py-0.5 rounded-md text-[10px] font-medium border', fieldTypeConfig[ft].bg, fieldTypeConfig[ft].color, fieldTypeConfig[ft].border]"
                        >
                          {{ fieldTypeConfig[ft].label }} ×{{ node[ft].length }}
                        </span>
                      </template>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Alerts Summary in Aggregate -->
            <div v-if="aggregateData.alerts && aggregateData.alerts.length > 0" class="bg-white rounded-xl border border-red-200 p-5">
              <div class="flex items-center gap-2 mb-4">
                <AlertOctagon class="w-4 h-4 text-red-500" />
                <span class="text-[13px] font-semibold text-red-700">告警摘要</span>
                <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-red-100 text-red-600 border border-red-200">{{ aggregateData.alerts.length }}</span>
              </div>
              <div class="space-y-3">
                <div v-for="alert in aggregateData.alerts" :key="alert.report_id"
                  class="p-3 bg-red-50/50 rounded-lg border border-red-100"
                >
                  <div class="flex items-center justify-between mb-1">
                    <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(alert.verdict).cls]">
                      {{ verdictBadge(alert.verdict).text }}
                    </span>
                    <span class="text-[10px] text-gray-400">{{ formatTime(alert.timestamp) }}</span>
                  </div>
                  <p class="text-[12px] text-gray-700 mt-1">{{ alert.summary || 'No summary' }}</p>
                  <div v-if="alert.suspicious_nodes?.length" class="mt-2 space-y-1">
                    <div v-for="(sn, i) in alert.suspicious_nodes" :key="i" class="flex items-center gap-2 text-[11px]">
                      <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadge(sn.severity || '').cls]">{{ sn.severity }}</span>
                      <span class="font-mono text-gray-600 truncate">{{ formatDid(sn.node_did || '') }}</span>
                      <span v-if="sn.taint_score" class="text-gray-400">score: {{ sn.taint_score }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ── Behavior Trace Tab ── -->
          <div v-if="activeTab === 'behavior' && behaviorData" class="space-y-5">
            <div v-if="behaviorData.nodes.length === 0" class="text-center py-12 text-gray-400 text-sm">
              该会话暂无行为溯源数据
            </div>

            <div v-else class="relative">
              <div class="absolute left-[19px] top-3 bottom-3 w-px bg-gray-200 border-l border-dashed border-gray-300 z-0"></div>

              <div v-for="node in behaviorData.nodes" :key="node.hop_count.join('.')" class="relative flex gap-4 mb-8 z-10">
                <div class="w-10 h-10 rounded-full bg-white border-2 border-indigo-200 flex items-center justify-center shrink-0 shadow-sm z-10">
                  <span class="text-[12px] font-bold text-indigo-600">{{ node.hop_count[0] }}.{{ node.hop_count[1] }}</span>
                </div>

                <div class="flex-1 min-w-0 space-y-3">
                  <div class="flex items-center gap-2">
                    <span class="text-[13px] font-semibold text-gray-800">Hop {{ node.hop_count[0] }}.{{ node.hop_count[1] }}</span>
                    <span class="text-[11px] font-mono text-gray-400 truncate" :title="node.node_did">{{ node.node_did }}</span>
                  </div>

                  <template v-for="ft in fieldTypes" :key="ft">
                    <div v-if="node[ft] && node[ft].length > 0" class="space-y-2">
                      <div class="flex items-center gap-1.5">
                        <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', fieldTypeConfig[ft].bg, fieldTypeConfig[ft].color, fieldTypeConfig[ft].border]">
                          {{ fieldTypeConfig[ft].label }}
                        </span>
                      </div>
                      <div v-for="(entry, idx) in node[ft]" :key="idx"
                        class="ml-2 bg-white rounded-xl border border-gray-200 p-3 shadow-sm"
                      >
                        <div class="flex items-center justify-between mb-1.5">
                          <div class="flex items-center gap-1.5">
                            <span v-if="entry.verification_status" :class="['px-1.5 py-0.5 rounded text-[9px] font-medium border', verificationBadge(entry.verification_status).cls]">
                              {{ verificationBadge(entry.verification_status).text }}
                            </span>
                            <span v-if="entry.node_type" class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-gray-100 text-gray-500 border border-gray-200">
                              {{ entry.node_type }}
                            </span>
                          </div>
                          <span class="text-[10px] text-gray-400 shrink-0">{{ formatTime(entry.timestamp) }}</span>
                        </div>
                        <p class="text-[12px] text-gray-700 leading-relaxed">{{ entry.content || '--' }}</p>
                        <p v-if="entry.target" class="text-[11px] text-gray-400 font-mono mt-1 truncate">
                          <span class="text-gray-500">target:</span> {{ entry.target }}
                        </p>
                      </div>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>

          <!-- ── Reports Tab ── -->
          <div v-if="activeTab === 'reports' && reportsData" class="space-y-4">
            <div v-if="reportsData.reports.length === 0" class="text-center py-12 text-gray-400 text-sm">
              该会话暂无分析报告
            </div>

            <div v-for="report in reportsData.reports" :key="report.id"
              class="bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-gray-300 transition-colors"
            >
              <div class="p-4">
                <div class="flex items-center justify-between mb-3">
                  <div class="flex items-center gap-2">
                    <span class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-purple-50 text-purple-600 border border-purple-200">
                      Batch #{{ report.batch_index }}
                    </span>
                    <span class="text-[11px] text-gray-400 font-mono">
                      trace {{ report.from_trace_id }} → {{ report.to_trace_id }}
                    </span>
                  </div>
                  <span class="text-[10px] text-gray-400">{{ formatTime(report.timestamp) }}</span>
                </div>

                <div v-if="report.report?.overall_verdict" class="flex items-center gap-2 mb-3">
                  <span class="text-[11px] text-gray-500">Verdict:</span>
                  <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(report.report.overall_verdict).cls]">
                    {{ verdictBadge(report.report.overall_verdict).text }}
                  </span>
                </div>

                <p v-if="report.report?.summary" class="text-[12px] text-gray-600 leading-relaxed mb-3">
                  {{ report.report.summary }}
                </p>

                <div v-if="report.report?.node_verdicts?.length" class="space-y-2 mt-3">
                  <div class="text-[11px] font-medium text-gray-400">节点裁决 ({{ report.report.node_verdicts.length }})</div>
                  <div v-for="(nv, i) in report.report.node_verdicts" :key="i"
                    class="flex items-center gap-2 p-2 bg-gray-50 rounded-lg border border-gray-100 text-[11px]"
                  >
                    <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadge(nv.severity || '').cls]">
                      {{ nv.severity || '--' }}
                    </span>
                    <span class="font-mono text-gray-600 truncate flex-1">{{ formatDid(nv.node_did || '') }}</span>
                    <span v-if="nv.taint_score != null" class="text-gray-400">taint: {{ nv.taint_score }}</span>
                  </div>
                </div>

                <details class="mt-3">
                  <summary class="text-[11px] text-gray-400 cursor-pointer hover:text-gray-600 transition-colors">查看原始报告</summary>
                  <div class="mt-2 bg-gray-50 rounded-lg p-3 text-[11px] font-mono text-gray-600 whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto">
                    {{ JSON.stringify(report.report, null, 2) }}
                  </div>
                </details>
              </div>
            </div>
          </div>

          <!-- ── Alerts Tab ── -->
          <div v-if="activeTab === 'alerts' && aggregateData" class="space-y-4">
            <div v-if="aggregateData.alerts.length === 0" class="text-center py-16 text-gray-400">
              <div class="w-14 h-14 rounded-2xl bg-emerald-50 border border-emerald-100 flex items-center justify-center mx-auto mb-3">
                <CheckCircle2 class="w-7 h-7 text-emerald-400" />
              </div>
              <p class="text-sm font-medium text-gray-500">未发现告警</p>
              <p class="text-xs text-gray-300 mt-1">所有分析报告均为 clean 状态</p>
            </div>

            <div v-for="alert in aggregateData.alerts" :key="alert.report_id"
              class="bg-white rounded-xl border-2 overflow-hidden"
              :class="alert.verdict === 'malicious' ? 'border-red-300' : 'border-amber-200'"
            >
              <div class="p-4" :class="alert.verdict === 'malicious' ? 'bg-red-50/50' : 'bg-amber-50/50'">
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <AlertOctagon :class="['w-4 h-4', alert.verdict === 'malicious' ? 'text-red-500' : 'text-amber-500']" />
                    <span :class="['px-2 py-0.5 rounded-md text-[10px] font-bold border', verdictBadge(alert.verdict).cls]">
                      {{ verdictBadge(alert.verdict).text }}
                    </span>
                    <span class="text-[11px] text-gray-400">Batch #{{ alert.batch_index }}</span>
                  </div>
                  <span class="text-[10px] text-gray-400">{{ formatTime(alert.timestamp) }}</span>
                </div>
                <p class="text-[13px] text-gray-700 leading-relaxed">{{ alert.summary || 'No summary available' }}</p>
                <div class="text-[11px] text-gray-400 font-mono mt-1">
                  trace range: {{ alert.from_trace_id }} → {{ alert.to_trace_id }}
                </div>
              </div>

              <div v-if="alert.suspicious_nodes?.length" class="p-4 border-t border-gray-100">
                <div class="text-[11px] font-medium text-gray-400 mb-2">可疑节点 ({{ alert.suspicious_nodes.length }})</div>
                <div class="space-y-2">
                  <div v-for="(sn, i) in alert.suspicious_nodes" :key="i"
                    class="flex items-start gap-3 p-3 bg-gray-50 rounded-lg border border-gray-100"
                  >
                    <div class="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
                      :class="sn.severity === 'high' ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600'"
                    >
                      <AlertTriangle class="w-3.5 h-3.5" />
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2 mb-1">
                        <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-semibold', severityBadge(sn.severity || '').cls]">
                          {{ sn.severity || '--' }}
                        </span>
                        <span v-if="sn.taint_score != null" class="text-[10px] text-gray-400">
                          taint_score: <span class="font-mono font-medium text-gray-600">{{ sn.taint_score }}</span>
                        </span>
                      </div>
                      <div class="text-[11px] font-mono text-gray-500 truncate" :title="sn.node_did || ''">
                        {{ sn.node_did || '--' }}
                      </div>
                      <p v-if="sn.evidence" class="text-[11px] text-gray-500 mt-1">{{ sn.evidence }}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ── Malicious Nodes Tab ── -->
          <div v-if="activeTab === 'malicious'" class="space-y-5">
            <!-- Source Filter -->
            <div class="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 flex-wrap">
              <span class="text-[12px] text-gray-500">来源筛选：</span>
              <select v-model="maliciousSourceFilter" @change="fetchMalicious"
                class="px-3 py-1.5 text-[12px] border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
              >
                <option value="">全部来源</option>
                <option value="protocol_review">协议审查</option>
                <option value="vertical_analysis">纵向分析</option>
                <option value="horizontal_analysis">横向分析</option>
              </select>
            </div>

            <!-- Session Reports -->
            <div class="bg-white rounded-xl border border-gray-200 p-5">
              <div class="flex items-center gap-2 mb-4">
                <UserX class="w-4 h-4 text-red-500" />
                <span class="text-[13px] font-semibold text-gray-800">当前 Session 恶意报告</span>
                <span v-if="maliciousData" class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-500 border border-gray-200">{{ maliciousData.total }}</span>
              </div>

              <div v-if="!maliciousData" class="text-center py-8 text-gray-400 text-[12px]">输入 Session ID 并查询</div>
              <div v-else-if="maliciousData.reports.length === 0" class="text-center py-8 text-gray-400 text-[12px]">
                <CheckCircle2 class="w-6 h-6 text-emerald-400 mx-auto mb-2" />
                该 Session 未发现恶意行为
              </div>
              <div v-else class="space-y-3">
                <div v-for="report in maliciousData.reports" :key="report.id"
                  class="p-3 rounded-lg border"
                  :class="report.severity === 'high' ? 'bg-red-50/50 border-red-200' : report.severity === 'medium' ? 'bg-amber-50/50 border-amber-200' : 'bg-blue-50/50 border-blue-200'"
                >
                  <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                      <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', sourceBadge(report.source).cls]">
                        {{ sourceBadge(report.source).text }}
                      </span>
                      <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadge(report.severity).cls]">
                        {{ report.severity }}
                      </span>
                      <span class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-gray-100 text-gray-500 border border-gray-200">
                        {{ report.evidence_type }}
                      </span>
                    </div>
                    <span class="text-[10px] text-gray-400">{{ formatTime(report.timestamp) }}</span>
                  </div>

                  <p class="text-[12px] text-gray-700 leading-relaxed mb-2">{{ report.evidence_description }}</p>

                  <div class="flex items-center gap-4 text-[11px] text-gray-500">
                    <div class="flex items-center gap-1">
                      <span class="text-gray-400">Target:</span>
                      <span class="font-mono truncate" :title="report.target_did">{{ formatDid(report.target_did) }}</span>
                    </div>
                    <div v-if="report.taint_score" class="flex items-center gap-1">
                      <span class="text-gray-400">Taint:</span>
                      <span class="font-mono font-medium text-gray-600">{{ report.taint_score }}</span>
                    </div>
                    <div class="flex items-center gap-1">
                      <span class="text-gray-400">Type:</span>
                      <span>{{ report.node_type }}</span>
                    </div>
                  </div>

                  <details class="mt-2">
                    <summary class="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">原始证据</summary>
                    <div class="mt-1 bg-gray-50 rounded p-2 text-[10px] font-mono text-gray-500 whitespace-pre-wrap overflow-x-auto max-h-[200px] overflow-y-auto">
                      {{ JSON.stringify(report.raw_evidence, null, 2) }}
                    </div>
                  </details>
                </div>
              </div>
            </div>

            <!-- Dossiers Overview -->
            <div class="bg-white rounded-xl border border-gray-200 p-5">
              <div class="flex items-center gap-2 mb-4">
                <Eye class="w-4 h-4 text-indigo-500" />
                <span class="text-[13px] font-semibold text-gray-800">恶意节点档案总览</span>
                <button @click="fetchDossiers" class="ml-auto px-2 py-1 text-[10px] text-gray-400 hover:text-gray-600 transition-colors flex items-center gap-1">
                  <RefreshCw class="w-3 h-3" /> 刷新
                </button>
              </div>

              <div v-if="!dossiersData" class="text-center py-8 text-gray-400 text-[12px]">点击刷新加载档案数据</div>
              <div v-else-if="dossiersData.dossiers.length === 0" class="text-center py-8 text-gray-400 text-[12px]">
                <CheckCircle2 class="w-6 h-6 text-emerald-400 mx-auto mb-2" />
                暂无已知恶意节点
              </div>
              <div v-else class="space-y-3">
                <div v-for="dossier in dossiersData.dossiers" :key="dossier.did"
                  class="p-3 rounded-lg border border-gray-200 bg-gray-50/50"
                >
                  <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                      <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', severityLevelBadge(dossier.severity_level).cls]">
                        {{ severityLevelBadge(dossier.severity_level).text }}
                      </span>
                      <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-200 text-gray-600">
                        {{ dossier.total_violations }} violations
                      </span>
                    </div>
                  </div>

                  <div class="text-[12px] font-mono text-gray-600 truncate mb-1" :title="dossier.did">{{ dossier.did }}</div>

                  <div class="flex items-center gap-3 text-[11px] text-gray-500">
                    <span>首次: {{ formatTime(dossier.first_seen_at) }}</span>
                    <span>最近: {{ formatTime(dossier.last_seen_at) }}</span>
                  </div>

                  <div v-if="dossier.last_evidence_desc" class="mt-2 text-[11px] text-gray-500">
                    <span class="text-gray-400">最近事件：</span>{{ dossier.last_evidence_desc }}
                  </div>

                  <!-- Evidence Breakdown -->
                  <div v-if="dossier.evidence_breakdown && Object.keys(dossier.evidence_breakdown).length" class="mt-2 flex flex-wrap gap-1.5">
                    <span v-for="(count, etype) in dossier.evidence_breakdown" :key="String(etype)"
                      class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-white text-gray-500 border border-gray-200"
                    >{{ String(etype) }} ({{ count }})</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          </template><!-- end vertical content -->

          <!-- ── Horizontal Analysis Content ── -->
          <template v-else>
          <div class="space-y-5">
            <!-- Horizontal State -->
            <div v-if="horizontalState" class="bg-white rounded-xl border border-gray-200 p-5">
              <div class="flex items-center gap-2 mb-3">
                <BarChart3 class="w-4 h-4 text-purple-500" />
                <span class="text-[13px] font-semibold text-gray-800">累积状态</span>
              </div>
              <div class="grid grid-cols-4 gap-4">
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[11px] text-gray-400 mb-1">累积次数</div>
                  <div class="text-xl font-semibold text-gray-800">{{ horizontalState.accumulated_count }}</div>
                </div>
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[11px] text-gray-400 mb-1">最后 Trace ID</div>
                  <div class="text-xl font-semibold text-gray-800">{{ horizontalState.last_trace_id }}</div>
                </div>
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[11px] text-gray-400 mb-1">批次索引</div>
                  <div class="text-xl font-semibold text-gray-800">{{ horizontalState.batch_index }}</div>
                </div>
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[11px] text-gray-400 mb-1">节点类型</div>
                  <div class="text-xl font-semibold text-gray-800">{{ horizontalState.node_type || '--' }}</div>
                </div>
              </div>
            </div>

            <!-- Horizontal Reports -->
            <div v-if="horizontalReports.length > 0" class="space-y-4">
              <div class="flex items-center gap-2 mb-2">
                <FileText class="w-4 h-4 text-purple-500" />
                <span class="text-[13px] font-semibold text-gray-800">横向分析报告</span>
                <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-purple-100 text-purple-600 border border-purple-200">{{ horizontalReports.length }}</span>
              </div>

              <div v-for="report in horizontalReports" :key="report.id"
                class="bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-gray-300 transition-colors"
              >
                <div class="p-4">
                  <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                      <span class="px-2 py-0.5 rounded-md text-[10px] font-semibold bg-purple-50 text-purple-600 border border-purple-200">
                        Batch #{{ report.batch_index }}
                      </span>
                      <span class="text-[11px] text-gray-400 font-mono">
                        trace {{ report.from_trace_id }} → {{ report.to_trace_id }}
                      </span>
                      <span class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-blue-50 text-blue-600 border border-blue-200">
                        {{ report.sessions_scanned }} sessions
                      </span>
                    </div>
                    <span class="text-[10px] text-gray-400">{{ formatTime(report.timestamp) }}</span>
                  </div>

                  <div v-if="report.report?.overall_verdict" class="flex items-center gap-2 mb-3">
                    <span class="text-[11px] text-gray-500">Verdict:</span>
                    <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(report.report.overall_verdict).cls]">
                      {{ verdictBadge(report.report.overall_verdict).text }}
                    </span>
                  </div>

                  <p v-if="report.report?.summary" class="text-[12px] text-gray-600 leading-relaxed mb-3">
                    {{ report.report.summary }}
                  </p>

                  <div v-if="report.report?.node_verdicts?.length" class="space-y-2 mt-3">
                    <div class="text-[11px] font-medium text-gray-400">节点裁决 ({{ report.report.node_verdicts.length }})</div>
                    <div v-for="(nv, i) in report.report.node_verdicts" :key="i"
                      class="flex items-center gap-2 p-2 bg-gray-50 rounded-lg border border-gray-100 text-[11px]"
                    >
                      <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadge(nv.severity || '').cls]">
                        {{ nv.severity || '--' }}
                      </span>
                      <span class="font-mono text-gray-600 truncate flex-1">{{ formatDid(nv.node_did || '') }}</span>
                      <span v-if="nv.taint_score != null" class="text-gray-400">taint: {{ nv.taint_score }}</span>
                    </div>
                  </div>

                  <details class="mt-3">
                    <summary class="text-[11px] text-gray-400 cursor-pointer hover:text-gray-600 transition-colors">查看原始报告</summary>
                    <div class="mt-2 bg-gray-50 rounded-lg p-3 text-[11px] font-mono text-gray-600 whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto">
                      {{ JSON.stringify(report.report, null, 2) }}
                    </div>
                  </details>
                </div>
              </div>
            </div>

            <div v-if="horizontalReports.length === 0 && horizontalState && !horizontalLoading" class="text-center py-12 text-gray-400 text-sm">
              <BarChart3 class="w-6 h-6 text-gray-300 mx-auto mb-2" />
              该 DID 暂无横向分析报告
            </div>

            <div v-if="!horizontalState && horizontalReports.length === 0 && !horizontalLoading" class="text-center py-12 text-gray-400 text-sm">
              输入节点 DID 查询横向分析数据
            </div>
          </div>
          </template><!-- end horizontal content -->

          <!-- ── Analysis Status (vertical only) ── -->
          <div v-if="queryMode === 'vertical' && analysisStatus" class="bg-white rounded-2xl border border-gray-200 p-5">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <button
                  @click="fetchAnalysisStatus"
                  :disabled="!selectedNodeId || !sessionIdInput.trim()"
                  class="px-3 py-2 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 hover:border-gray-300 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <RefreshCw class="w-3.5 h-3.5" /> 刷新状态
                </button>
              </div>

              <!-- Analysis Status Badge -->
              <div v-if="analysisStatus" class="flex items-center gap-2">
                <template v-if="analysisStatus.status === 'running'">
                  <Loader2 class="w-4 h-4 text-blue-500 animate-spin" />
                  <span class="text-[12px] text-blue-600 font-medium">分析进行中</span>
                  <span v-if="analysisStatus.phase" class="text-[11px] text-gray-400">{{ analysisStatus.phase }}</span>
                </template>
                <template v-else-if="analysisStatus.status === 'completed'">
                  <CheckCircle2 class="w-4 h-4 text-emerald-500" />
                  <span class="text-[12px] text-emerald-600 font-medium">分析完成</span>
                </template>
                <template v-else-if="analysisStatus.status === 'failed'">
                  <XCircle class="w-4 h-4 text-red-500" />
                  <span class="text-[12px] text-red-600 font-medium">分析失败</span>
                </template>
                <template v-else-if="analysisStatus.status === 'not_found'">
                  <Clock class="w-4 h-4 text-gray-400" />
                  <span class="text-[12px] text-gray-400">未找到分析任务</span>
                </template>
                <template v-else>
                  <Clock class="w-4 h-4 text-gray-400" />
                  <span class="text-[12px] text-gray-400">{{ analysisStatus.status }}</span>
                </template>
              </div>
            </div>
          </div>
        </template>

      </div>
    </div>

    <!-- ── Add Node Modal ── -->
    <div v-if="showAddModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="showAddModal = false">
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-900">添加溯源节点</h3>
          <button @click="showAddModal = false" class="p-1 text-gray-400 hover:text-gray-600"><X class="w-4 h-4" /></button>
        </div>
        <div class="space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">名称</label>
            <input v-model="newNodeName" placeholder="例如：ATTP Node 1" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">URL</label>
            <input v-model="newNodeUrl" placeholder="http://localhost:9000" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showAddModal = false" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
          <button @click="addNode" class="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800">添加</button>
        </div>
      </div>
    </div>

    <!-- ── Edit Node Modal ── -->
    <div v-if="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="showEditModal = false">
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-900">编辑溯源节点</h3>
          <button @click="showEditModal = false" class="p-1 text-gray-400 hover:text-gray-600"><X class="w-4 h-4" /></button>
        </div>
        <div class="space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">名称</label>
            <input v-model="editNodeName" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">URL</label>
            <input v-model="editNodeUrl" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showEditModal = false" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
          <button @click="saveEditNode" class="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800">保存</button>
        </div>
      </div>
    </div>

    <!-- ── Toast ── -->
    <transition name="toast">
      <div v-if="toastVisible"
        class="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-4 py-2.5 rounded-xl shadow-lg text-[13px] font-medium flex items-center gap-2"
        :class="toastType === 'success' ? 'bg-gray-900 text-white' : 'bg-red-600 text-white'"
      >
        <CheckCircle2 v-if="toastType === 'success'" class="w-4 h-4" />
        <XCircle v-else class="w-4 h-4" />
        {{ toastMessage }}
      </div>
    </transition>
  </div>
</template>