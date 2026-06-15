<script setup lang="ts">
/**
 * 视图2 — 溯源查询。
 *
 * 纵向（session 级）：行为溯源 + 纵向分析报告 + 告警
 * 横向（did 级）：累积状态 + 横向分析报告
 *
 * 引导式分析流程：查状态 → 未完成才显示触发 → 触发后轮询 → 完成后取报告。
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Loader2, Search, Crosshair, Zap, RefreshCw, GitMerge, FileText,
  AlertTriangle, CheckCircle2, XCircle, Clock, AlertOctagon, BarChart3,
} from 'lucide-vue-next'
import { apiFetch } from '../../transport'
import { useProtocolNodes } from '../../composables/useProtocolNodes'
import { useAnalysisFlow } from '../../composables/useAnalysisFlow'
import { useToast } from '../../composables/useToast'
import {
  transformChainToNodes, verdictBadge, severityBadgeCls, formatTime, formatDid,
} from '../../composables/useTraceFormat'
import type {
  HopNode, AnalysisReport, Alert, AnalysisStatus, HorizontalState, SuspiciousNode,
} from './types'
import NodeSelector from './components/NodeSelector.vue'
import BehaviorChain from './components/BehaviorChain.vue'
import AnalysisReportCard from './components/AnalysisReportCard.vue'

const route = useRoute()
const router = useRouter()
const { selectedNode, selectedNodeId, loadNodes, ensureSelection, buildUrl } = useProtocolNodes()
const { showToast } = useToast()

const queryMode = ref<'vertical' | 'horizontal'>('vertical')
const sessionIdInput = ref('')
const didInput = ref('')
const loading = ref(false)
const activeTab = ref<'behavior' | 'reports' | 'alerts'>('behavior')
const hasQueried = ref(false)

// ─── 数据 ───
const behaviorNodes = ref<HopNode[]>([])
const vReports = ref<AnalysisReport[]>([])
const hReports = ref<AnalysisReport[]>([])
const hState = ref<HorizontalState | null>(null)

// 从纵向报告派生告警（与后端 aggregate 提取逻辑一致）
const vAlerts = computed<Alert[]>(() =>
  vReports.value
    .filter(r => {
      const v = r.report?.overall_verdict
      return v === 'suspicious' || v === 'malicious'
    })
    .map(r => ({
      report_id: r.id,
      batch_index: r.batch_index,
      verdict: r.report?.overall_verdict ?? '',
      summary: r.report?.summary ?? '',
      from_trace_id: r.from_trace_id,
      to_trace_id: r.to_trace_id,
      timestamp: r.timestamp,
      suspicious_nodes: (r.report?.node_verdicts ?? [])
        .filter((nv: any) => nv.severity === 'medium' || nv.severity === 'high')
        .map((nv: any): SuspiciousNode => ({
          node_did: nv.node_did ?? null,
          severity: nv.severity ?? null,
          taint_score: nv.taint_score ?? null,
          evidence: nv.evidence ?? null,
        })),
    })),
)

// ─── 引导式分析流程（纵/横各一） ───
const vFlow = useAnalysisFlow('v', (sid) => { void fetchVerticalReport(sid) })
const hFlow = useAnalysisFlow('h', (did) => { void fetchHorizontalReport(did) })

const currentStatus = computed<AnalysisStatus | null>(() =>
  queryMode.value === 'vertical' ? vFlow.status.value : hFlow.status.value,
)
const currentPolling = computed(() =>
  queryMode.value === 'vertical' ? vFlow.polling.value : hFlow.polling.value,
)
const currentTriggerLoading = computed(() =>
  queryMode.value === 'vertical' ? vFlow.triggerLoading.value : hFlow.triggerLoading.value,
)

/** 状态展示：running | completed | failed | not_found | uptodate | idle */
const statusKind = computed<'idle' | 'running' | 'completed' | 'failed' | 'not_found' | 'uptodate'>(() => {
  const s = currentStatus.value
  if (!s) return 'idle'
  if (s.status === 'running' || s.status === 'already_running') return 'running'
  if (s.status === 'completed') {
    if (s.triggered === false) {
      // 已分析过、无新增 trace（旧报告仍有效）——不是失败
      const r = s.reason || ''
      if (r === 'no_unanalyzed_traces' || r === 'no_new_traces') return 'uptodate'
      return 'failed'
    }
    return 'completed'
  }
  if (s.status === 'not_found') return 'not_found'
  return 'idle'
})

// ─── 数据拉取 ───
async function fetchBehavior(sid: string) {
  if (!selectedNode.value || !sid) return
  const pna = encodeURIComponent(selectedNode.value.url)
  const url = buildUrl(`/api/behavior/${encodeURIComponent(sid)}?protocol_node_address=${pna}`)
  const res = await apiFetch(url)
  if (res.ok) {
    behaviorNodes.value = transformChainToNodes(res.data.chain || [])
  }
}

async function fetchVerticalReport(sid: string) {
  if (!selectedNode.value || !sid) return
  const url = buildUrl(`/api/analysis/v/report/${encodeURIComponent(sid)}`)
  const res = await apiFetch(url)
  if (res.ok) vReports.value = res.data.reports || []
}

async function fetchHorizontalReport(did: string) {
  if (!selectedNode.value || !did) return
  const url = buildUrl(`/api/analysis/h/report/${encodeURIComponent(did)}`)
  const res = await apiFetch(url)
  if (res.ok) hReports.value = res.data.reports || []
}

async function fetchHorizontalState(did: string) {
  if (!selectedNode.value || !did) return
  const url = buildUrl(`/api/analysis/h/state/${encodeURIComponent(did)}`)
  const res = await apiFetch(url)
  hState.value = res.ok ? res.data : null
}

function resetData() {
  behaviorNodes.value = []
  vReports.value = []
  hReports.value = []
  hState.value = null
}

async function doQuery() {
  if (!selectedNode.value) { showToast('请先选择溯源节点', 'error'); return }
  resetData()
  loading.value = true
  try {
    if (queryMode.value === 'vertical') {
      const sid = sessionIdInput.value.trim()
      if (!sid) return
      hasQueried.value = true
      await Promise.all([
        fetchBehavior(sid),
        vFlow.refreshStatus(sid),
      ])
      // 已完成则直接取报告（含「已是最新」态——旧报告仍应展示；仅真正失败时不取）
      if (vFlow.status.value?.status === 'completed' && statusKind.value !== 'failed') {
        await fetchVerticalReport(sid)
      }
    } else {
      const did = didInput.value.trim()
      if (!did) return
      hasQueried.value = true
      await Promise.all([
        fetchHorizontalState(did),
        hFlow.refreshStatus(did),
      ])
      if (hFlow.status.value?.status === 'completed' && statusKind.value !== 'failed') {
        await fetchHorizontalReport(did)
      }
    }
  } finally {
    loading.value = false
  }
}

async function doTrigger() {
  if (queryMode.value === 'vertical') {
    const sid = sessionIdInput.value.trim()
    if (!sid) return
    const ok = await vFlow.trigger(sid)
    if (!ok) showToast('触发分析失败（分析功能未启用？）', 'error')
    else showToast('纵向污点分析已触发')
  } else {
    const did = didInput.value.trim()
    if (!did) return
    const ok = await hFlow.trigger(did)
    if (!ok) showToast('触发分析失败（分析功能未启用？）', 'error')
    else showToast('横向分析已触发')
  }
}

function refreshStatusOnly() {
  if (queryMode.value === 'vertical') {
    const sid = sessionIdInput.value.trim()
    if (sid) void vFlow.refreshStatus(sid)
  } else {
    const did = didInput.value.trim()
    if (did) void hFlow.refreshStatus(did)
  }
}

function onViewDossier(did: string) {
  router.push({ path: '/trace/malicious', query: { did } })
}

function switchMode(mode: 'vertical' | 'horizontal') {
  queryMode.value = mode
  hasQueried.value = false
}

// ─── 生命周期 ───
onMounted(async () => {
  loadNodes()
  // 等节点状态检测完成
  setTimeout(() => {
    ensureSelection()
    const qSid = route.query.sessionId as string | undefined
    const qDid = route.query.did as string | undefined
    const pNodeUrl = route.query.protocolNodeUrl as string | undefined
    if (pNodeUrl) {
      const matched = useProtocolNodes().traceNodes.value.find(
        n => n.url.replace(/\/+$/, '') === pNodeUrl.replace(/\/+$/, ''),
      )
      if (matched) selectedNodeId.value = matched.id
    }
    if (qSid) { queryMode.value = 'vertical'; sessionIdInput.value = qSid; void doQuery() }
    else if (qDid) { queryMode.value = 'horizontal'; didInput.value = qDid; void doQuery() }
  }, 1500)
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-5xl mx-auto">
        <h2 class="text-xl font-semibold text-gray-900 tracking-tight mb-1.5">溯源查询</h2>
        <p class="text-sm text-gray-500">行为溯源链 · 纵向语义污点分析 · 横向跨会话分析</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto">
      <div class="max-w-5xl mx-auto p-8 space-y-6 pb-8">

        <!-- ── 查询栏 ── -->
        <div class="bg-white rounded-2xl border border-gray-200 p-5 space-y-3">
          <div class="flex items-center gap-3 flex-wrap">
            <NodeSelector />
            <div class="flex items-end">
              <div class="flex bg-gray-100 rounded-xl p-1">
                <button @click="switchMode('vertical')"
                  :class="['px-3 py-2 text-[12px] rounded-lg transition-colors font-medium flex items-center gap-1', queryMode === 'vertical' ? 'bg-white text-gray-900 shadow-sm border border-gray-200' : 'text-gray-500 hover:text-gray-700']"
                ><Search class="w-3.5 h-3.5" /> 纵向分析</button>
                <button @click="switchMode('horizontal')"
                  :class="['px-3 py-2 text-[12px] rounded-lg transition-colors font-medium flex items-center gap-1', queryMode === 'horizontal' ? 'bg-white text-gray-900 shadow-sm border border-gray-200' : 'text-gray-500 hover:text-gray-700']"
                ><Crosshair class="w-3.5 h-3.5" /> 横向分析</button>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-3 flex-wrap pt-3 border-t border-gray-100">
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
                  v-model="didInput"
                  placeholder="输入节点 DID 进行横向分析"
                  class="w-full pl-9 pr-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors font-mono placeholder:text-gray-300"
                  @keydown.enter="doQuery()"
                />
              </div>
            </div>
            <div class="flex items-end gap-2">
              <button @click="doQuery()"
                :disabled="!selectedNodeId || (queryMode === 'vertical' ? !sessionIdInput.trim() : !didInput.trim()) || loading"
                class="px-5 py-2.5 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
                <Search v-else class="w-4 h-4" /> 查询
              </button>
            </div>
          </div>
        </div>

        <!-- ── 未选节点 ── -->
        <div v-if="!selectedNodeId" class="flex flex-col items-center justify-center py-20 text-gray-400">
          <p class="text-sm">请先选择一个溯源节点</p>
        </div>

        <template v-else>
          <!-- ── 分析状态条 ── -->
          <div v-if="currentStatus" class="bg-white rounded-2xl border border-gray-200 p-4 flex items-center justify-between">
            <button @click="refreshStatusOnly" :disabled="queryMode === 'vertical' ? !sessionIdInput.trim() : !didInput.trim()"
              class="px-3 py-2 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 transition-colors flex items-center gap-1.5 disabled:opacity-40"
            >
              <RefreshCw class="w-3.5 h-3.5" /> 刷新状态
            </button>
            <div class="flex items-center gap-2">
              <template v-if="statusKind === 'running'">
                <Loader2 class="w-4 h-4 text-blue-500 animate-spin" />
                <span class="text-[12px] text-blue-600 font-medium">分析进行中</span>
                <span v-if="currentStatus.phase" class="text-[11px] text-gray-400">{{ currentStatus.phase }}</span>
              </template>
              <template v-else-if="statusKind === 'completed'">
                <CheckCircle2 class="w-4 h-4 text-emerald-500" />
                <span class="text-[12px] text-emerald-600 font-medium">分析完成</span>
              </template>
              <template v-else-if="statusKind === 'uptodate'">
                <CheckCircle2 class="w-4 h-4 text-gray-400" />
                <span class="text-[12px] text-gray-500 font-medium">已是最新 · 无新增待分析 trace</span>
              </template>
              <template v-else-if="statusKind === 'failed'">
                <XCircle class="w-4 h-4 text-red-500" />
                <span class="text-[12px] text-red-600 font-medium">分析失败</span>
                <span v-if="currentStatus.reason" class="text-[11px] text-gray-400 truncate max-w-[280px]">{{ currentStatus.reason }}</span>
              </template>
              <template v-else-if="statusKind === 'not_found'">
                <Clock class="w-4 h-4 text-gray-400" />
                <span class="text-[12px] text-gray-400">未找到分析任务</span>
                <button @click="doTrigger"
                  :disabled="currentTriggerLoading || currentPolling || !selectedNodeId || (queryMode === 'vertical' ? !sessionIdInput.trim() : !didInput.trim())"
                  class="px-3 py-1.5 text-[12px] font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Loader2 v-if="currentTriggerLoading || currentPolling" class="w-3.5 h-3.5 animate-spin" />
                  <Zap v-else class="w-3.5 h-3.5" /> 触发分析
                </button>
              </template>
              <template v-else>
                <Clock class="w-4 h-4 text-gray-400" />
                <span class="text-[12px] text-gray-400">{{ currentStatus.status }}</span>
              </template>
            </div>
          </div>

          <!-- ── 加载中 ── -->
          <div v-if="loading" class="flex items-center justify-center py-16 text-gray-400">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span class="text-sm">正在查询溯源数据...</span>
          </div>

          <template v-else>
            <!-- ============ 纵向 ============ -->
            <template v-if="queryMode === 'vertical'">
              <div v-if="hasQueried" class="space-y-6">
              <!-- Tabs -->
              <div class="flex items-center gap-1 bg-gray-100/60 rounded-xl p-1 flex-wrap">
                <button v-for="tab in ([
                    { key: 'behavior', label: '行为溯源', icon: GitMerge, count: behaviorNodes.length || null },
                    { key: 'reports', label: '分析报告', icon: FileText, count: vReports.length || null },
                    { key: 'alerts', label: '告警', icon: AlertTriangle, count: vAlerts.length || null },
                  ] as const)" :key="tab.key"
                  @click="activeTab = tab.key as any"
                  :class="['flex items-center gap-1.5 px-4 py-2 text-[13px] rounded-lg transition-colors font-medium', activeTab === tab.key ? 'bg-white text-gray-900 shadow-sm border border-gray-200' : 'text-gray-500 hover:text-gray-700']"
                >
                  <component :is="tab.icon" class="w-3.5 h-3.5" />
                  <span>{{ tab.label }}</span>
                  <span v-if="tab.count" :class="['px-1.5 py-0.5 rounded-full text-[10px] font-medium', tab.key === 'alerts' ? 'bg-red-100 text-red-600' : 'bg-gray-200 text-gray-600']">{{ tab.count }}</span>
                </button>
              </div>

              <!-- 行为溯源 -->
              <div v-if="activeTab === 'behavior'">
                <BehaviorChain :nodes="behaviorNodes" />
              </div>

              <!-- 分析报告 -->
              <div v-if="activeTab === 'reports'" class="space-y-4">
                <div v-if="vReports.length === 0" class="text-center py-12 text-gray-400 text-sm">
                  <div v-if="statusKind !== 'completed' && statusKind !== 'uptodate'">触发纵向分析后将生成报告</div>
                  <div v-else>该会话暂无分析报告</div>
                </div>
                <AnalysisReportCard v-for="r in vReports" :key="r.id" :report="r" axis="v" @view-dossier="onViewDossier" />
              </div>

              <!-- 告警 -->
              <div v-if="activeTab === 'alerts'" class="space-y-4">
                <div v-if="vAlerts.length === 0" class="text-center py-16 text-gray-400">
                  <div class="w-14 h-14 rounded-2xl bg-emerald-50 border border-emerald-100 flex items-center justify-center mx-auto mb-3">
                    <CheckCircle2 class="w-7 h-7 text-emerald-400" />
                  </div>
                  <p class="text-sm font-medium text-gray-500">未发现告警</p>
                  <p class="text-xs text-gray-300 mt-1">所有分析报告均为 clean 状态</p>
                </div>
                <div v-for="alert in vAlerts" :key="alert.report_id"
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
                    <div class="text-[11px] text-gray-400 font-mono mt-1">trace range: {{ alert.from_trace_id }} → {{ alert.to_trace_id }}</div>
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
                            <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-semibold', severityBadgeCls(sn.severity || '')]">
                              {{ sn.severity || '--' }}
                            </span>
                            <span v-if="sn.taint_score != null" class="text-[10px] text-gray-400">
                              taint_score: <span class="font-mono font-medium text-gray-600">{{ sn.taint_score }}</span>
                            </span>
                          </div>
                          <button v-if="sn.node_did" @click="onViewDossier(sn.node_did)"
                            class="text-[11px] font-mono text-gray-500 hover:text-indigo-600 hover:underline truncate block text-left"
                            :title="sn.node_did"
                          >{{ sn.node_did }}</button>
                          <p v-if="sn.evidence" class="text-[11px] text-gray-500 mt-1">{{ sn.evidence }}</p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              </div>
              <div v-else class="text-center py-12 text-gray-400 text-sm">输入 Session ID 进行溯源查询</div>
            </template>

            <!-- ============ 横向 ============ -->
            <template v-else>
              <div class="space-y-5">
                <!-- 累积状态 -->
                <div v-if="hState" class="bg-white rounded-xl border border-gray-200 p-5">
                  <div class="flex items-center gap-2 mb-3">
                    <BarChart3 class="w-4 h-4 text-purple-500" />
                    <span class="text-[13px] font-semibold text-gray-800">累积状态</span>
                  </div>
                  <div class="grid grid-cols-4 gap-4">
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">累积次数</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.accumulated_count }}</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">最后 Trace ID</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.last_trace_id }}</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">批次索引</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.batch_index }}</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">节点类型</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.node_type || '--' }}</div>
                    </div>
                  </div>
                </div>

                <!-- 横向报告 -->
                <div v-if="hReports.length > 0" class="space-y-4">
                  <div class="flex items-center gap-2 mb-2">
                    <FileText class="w-4 h-4 text-purple-500" />
                    <span class="text-[13px] font-semibold text-gray-800">横向分析报告</span>
                    <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-purple-100 text-purple-600 border border-purple-200">{{ hReports.length }}</span>
                  </div>
                  <AnalysisReportCard v-for="r in hReports" :key="r.id" :report="r" axis="h" @view-dossier="onViewDossier" />
                </div>

                <div v-if="hReports.length === 0 && !hState" class="text-center py-12 text-gray-400 text-sm">
                  输入节点 DID 查询横向分析数据
                </div>
                <div v-else-if="hReports.length === 0" class="text-center py-12 text-gray-400 text-sm">
                  <BarChart3 class="w-6 h-6 text-gray-300 mx-auto mb-2" />
                  该 DID 暂无横向分析报告
                </div>
              </div>
            </template>
          </template>
        </template>

      </div>
    </div>
  </div>
</template>
