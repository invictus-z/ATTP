<script setup lang="ts">
/**
 * 视图2 — 溯源查询。
 *
 * 纵向（session 级）：行为溯源 + 逐跳评分（hop_scores）+ 意图流（intent_revisions）+ R_T 告警
 * 横向（did 级）：F/volume 累积状态 + 横轴确认报告
 *
 * 引导式分析流程：查状态 → 触发后 SSE 订阅 → 完成后取报告。
 */
import { ref, computed, onMounted, onScopeDispose } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Loader2, Search, Crosshair, GitMerge, FileText,
  AlertTriangle, CheckCircle2, AlertOctagon, BarChart3, Layers,
} from 'lucide-vue-next'
import { apiFetch, createSse, onSseEvent, type SseConnection } from '../../transport'
import { useProtocolNodes } from '../../composables/useProtocolNodes'
import { useAnalysisFlow } from '../../composables/useAnalysisFlow'
import { useToast } from '../../composables/useToast'
import {
  transformChainToNodes, verdictBadge, severityBadgeCls, severityRowCls, formatTime,
} from '../../composables/useTraceFormat'
import type {
  HopNode, AnalysisReport, AnalysisStatus, HorizontalState, VerticalState,
  VerticalReport, MaliciousReport,
} from './types'
import NodeSelector from './components/NodeSelector.vue'
import BehaviorChain from './components/BehaviorChain.vue'
import AnalysisReportCard from './components/AnalysisReportCard.vue'
import AnalysisStatusBar from './components/AnalysisStatusBar.vue'
import HopScoreCard from './components/HopScoreCard.vue'
import FProgress from './components/FProgress.vue'

const route = useRoute()
const router = useRouter()
const { selectedNode, selectedNodeId, loadNodes, ensureSelection, buildUrl } = useProtocolNodes()
const { showToast } = useToast()

const queryMode = ref<'vertical' | 'horizontal'>('vertical')
const sessionIdInput = ref('')
const didInput = ref('')
const loading = ref(false)
const activeTab = ref<'behavior' | 'hops' | 'alerts'>('behavior')
const hasQueried = ref(false)

// ─── 数据 ───
const behaviorNodes = ref<HopNode[]>([])
const vReport = ref<VerticalReport | null>(null)
const vAlerts = ref<MaliciousReport[]>([])
const hReports = ref<AnalysisReport[]>([])
const hState = ref<HorizontalState | null>(null)
const vState = ref<VerticalState | null>(null)

// ─── 引导式分析流程（纵/横各一） ───
// LLM「工作中 → 完成」转换时，后端状态与报告均已更新，重拉刷新页面
const vFlow = useAnalysisFlow('v', (sid) => {
  void fetchVerticalState(sid); void fetchVerticalReport(sid); void fetchVerticalAlerts(sid)
})
const hFlow = useAnalysisFlow('h', (did) => { void fetchHorizontalState(did); void fetchHorizontalReport(did) })
// hop.scored（纵）→ 刷新逐跳评分 + 告警；horizontal.triggered/accumulated（横）→ 刷新横向累计状态
vFlow.onStateChange((sid) => { void fetchVerticalReport(sid); void fetchVerticalAlerts(sid) })
hFlow.onStateChange((did) => { void fetchHorizontalState(did) })

const currentStatus = computed<AnalysisStatus | null>(() =>
  queryMode.value === 'vertical' ? vFlow.status.value : hFlow.status.value,
)

/** 状态展示：running | completed | failed | uptodate
 *  - 触发分析按钮始终显示（见 AnalysisStatusBar），本字段仅驱动状态指示文案。
 *  - 逐跳改版后无 pending_count；后端 triggered:false + reason:no_unanalyzed_traces 兜底「无待分析」。 */
const statusKind = computed<'idle' | 'running' | 'completed' | 'failed' | 'uptodate'>(() => {
  const s = currentStatus.value
  if (s?.status === 'running' || s?.status === 'already_running') return 'running'
  if (s?.status === 'completed') {
    if (s.triggered === false) {
      const r = s.reason || ''
      if (r === 'no_unanalyzed_traces' || r === 'no_new_traces') return 'uptodate'
      return 'failed'
    }
    return 'completed'
  }
  return 'uptodate'
})

// 触发分析按钮：输入非空且未 running 即可（新模型无 pending_count；后端 no_unanalyzed 兜底）
const vTriggerDisabled = computed(() =>
  vFlow.triggerLoading.value || vFlow.running.value || !sessionIdInput.value.trim(),
)
const hTriggerDisabled = computed(() =>
  hFlow.triggerLoading.value || hFlow.running.value || !didInput.value.trim(),
)

// 意图流（report 优先，回退 state）
const intentRevisions = computed(() => vReport.value?.intent_revisions || vState.value?.intent_revisions || [])

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
  if (res.ok) vReport.value = res.data
}

async function fetchVerticalAlerts(sid: string) {
  if (!selectedNode.value || !sid) return
  const url = buildUrl(`/api/malicious/reports?session_id=${encodeURIComponent(sid)}&source=vertical_analysis&limit=100`)
  const res = await apiFetch(url)
  if (res.ok) vAlerts.value = res.data.reports || []
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

async function fetchVerticalState(sid: string) {
  if (!selectedNode.value || !sid) return
  const url = buildUrl(`/api/analysis/v/state/${encodeURIComponent(sid)}`)
  const res = await apiFetch(url)
  vState.value = res.ok ? res.data : null
}

function resetData() {
  behaviorNodes.value = []
  vReport.value = null
  vAlerts.value = []
  hReports.value = []
  hState.value = null
  vState.value = null
}

async function doQuery() {
  if (!selectedNode.value) { showToast('请先选择协议节点', 'error'); return }
  resetData()
  loading.value = true
  try {
    if (queryMode.value === 'vertical') {
      const sid = sessionIdInput.value.trim()
      if (!sid) return
      hasQueried.value = true
      await Promise.all([
        fetchBehavior(sid),
        fetchVerticalState(sid),
        fetchVerticalReport(sid),
        fetchVerticalAlerts(sid),
      ])
      void vFlow.subscribe(sid)
      void subscribeTrace(sid)
    } else {
      const did = didInput.value.trim()
      if (!did) return
      hasQueried.value = true
      await Promise.all([fetchHorizontalState(did)])
      void hFlow.subscribe(did)
      // 有确认批次则拉取展示；触发后新完成的报告由 SSE onCompleted 回调拉取
      if (hState.value && hState.value.batch_index > 0) {
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
    else showToast('纵向意图追踪已触发')
  } else {
    const did = didInput.value.trim()
    if (!did) return
    const ok = await hFlow.trigger(did)
    if (!ok) showToast('触发分析失败（分析功能未启用？）', 'error')
    else showToast('横向分析已触发')
  }
}

function onViewDossier(did: string) {
  router.push({ path: '/trace/malicious', query: { did } })
}

function openCrossLock() {
  const sid = sessionIdInput.value.trim()
  if (!sid) { showToast('请先输入 Session ID', 'error'); return }
  router.push({
    path: '/trace/cross-lock',
    query: { sessionId: sid, protocolNodeUrl: selectedNode.value?.url },
  })
}

function switchMode(mode: 'vertical' | 'horizontal') {
  if (mode === queryMode.value) return
  // 离开当前轴：关闭其 SSE 订阅（长连接，需显式断开避免残留）
  if (queryMode.value === 'vertical') void vFlow.unsubscribe()
  else void hFlow.unsubscribe()
  void unsubscribeTrace()
  queryMode.value = mode
  hasQueried.value = false
}

// ── trace.recorded SSE 订阅：行为链 + 纵向状态/报告实时更新 ──
let traceSseConn: SseConnection | null = null

async function subscribeTrace(sid: string) {
  await unsubscribeTrace()
  if (!sid) return
  const url = buildUrl(`/api/events?topics=trace&session_id=${encodeURIComponent(sid)}`)
  if (!url) return
  try {
    traceSseConn = await createSse(url)
  } catch {
    return
  }
  onSseEvent(traceSseConn, (event) => {
    if (event === 'trace.recorded') {
      void fetchBehavior(sid)
      void fetchVerticalState(sid)
      void fetchVerticalReport(sid)
    }
  })
}

/** 手动刷新当前轴的全部展示数据（状态 + 报告 + 行为链）。 */
function refreshCurrent() {
  if (queryMode.value === 'vertical') {
    const sid = sessionIdInput.value.trim()
    if (!sid) return
    void fetchBehavior(sid)
    void fetchVerticalState(sid)
    void fetchVerticalReport(sid)
    void fetchVerticalAlerts(sid)
  } else {
    const did = didInput.value.trim()
    if (!did) return
    void fetchHorizontalState(did)
    void fetchHorizontalReport(did)
  }
}

async function unsubscribeTrace() {
  if (traceSseConn) {
    const conn = traceSseConn
    traceSseConn = null
    await conn.close()
  }
}

onScopeDispose(() => { void unsubscribeTrace() })

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
        <p class="text-sm text-gray-500">消息固化 · 纵向意图追踪 · 横向意图追踪</p>
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
          <p class="text-sm">请先选择一个协议节点</p>
        </div>

        <template v-else>
          <!-- ── 加载中 ── -->
          <div v-if="loading" class="flex items-center justify-center py-16 text-gray-400">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span class="text-sm">正在查询溯源数据...</span>
          </div>

          <template v-else>
            <!-- ============ 纵向 ============ -->
            <template v-if="queryMode === 'vertical'">
              <div v-if="hasQueried" class="space-y-6">
              <!-- 累计状态 + 意图流 -->
              <div v-if="vState" class="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-2">
                    <BarChart3 class="w-4 h-4 text-indigo-500" />
                    <span class="text-[13px] font-semibold text-gray-800">累计状态</span>
                  </div>
                  <!-- 总体裁决 banner -->
                  <div v-if="vReport?.overall_verdict" class="flex items-center gap-2 text-[11px]">
                    <span class="text-gray-400">总体裁决</span>
                    <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(vReport.overall_verdict).cls]">
                      {{ verdictBadge(vReport.overall_verdict).text }}
                    </span>
                    <span v-if="vReport?.max_score != null" class="text-gray-400">max <span class="font-mono text-gray-600">{{ Number(vReport.max_score).toFixed(1) }}</span></span>
                    <span v-if="vReport?.total_hops != null" class="text-gray-400">hops <span class="font-mono text-gray-600">{{ vReport.total_hops }}</span></span>
                  </div>
                </div>
                <div class="grid grid-cols-3 gap-4">
                  <div class="bg-gray-50 rounded-lg p-3 text-center">
                    <div class="text-[11px] text-gray-400 mb-1">意图增量数</div>
                    <div class="text-xl font-semibold text-gray-800">{{ vState.intent_revision_count }}</div>
                  </div>
                  <div class="bg-gray-50 rounded-lg p-3 text-center">
                    <div class="text-[11px] text-gray-400 mb-1">打分游标</div>
                    <div class="text-xl font-semibold text-gray-800">{{ vState.last_scored_trace_id }}</div>
                  </div>
                  <div class="bg-gray-50 rounded-lg p-3 text-center">
                    <div class="text-[11px] text-gray-400 mb-1">隐状态</div>
                    <div class="text-xl font-semibold" :class="vState.has_hidden_state ? 'text-indigo-600' : 'text-gray-300'">{{ vState.has_hidden_state ? '有' : '无' }}</div>
                  </div>
                </div>
                <!-- ── 分析状态条 ── -->
                <AnalysisStatusBar
                  :status="currentStatus" :status-kind="statusKind"
                  :polling="vFlow.running.value" :trigger-loading="vFlow.triggerLoading.value"
                  :refresh-disabled="!sessionIdInput.trim()" :trigger-disabled="vTriggerDisabled"
                  @refresh="refreshCurrent"
                  @trigger="doTrigger"
                />
                <!-- 意图流 (intent_revisions) -->
                <div v-if="intentRevisions.length" class="border-t border-gray-100 pt-4">
                  <div class="flex items-center gap-2 mb-2">
                    <Crosshair class="w-4 h-4 text-indigo-500" />
                    <span class="text-[13px] font-semibold text-gray-800">意图流 (Intent Stream)</span>
                  </div>
                  <div class="space-y-2">
                    <div v-for="(rev, i) in intentRevisions" :key="i"
                      class="p-2.5 bg-gray-50 rounded-lg border border-gray-100 text-[12px]"
                    >
                      <div class="flex items-center gap-2 mb-1">
                        <span class="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 text-[10px] font-semibold border border-indigo-100">Δ{{ i }}</span>
                        <span class="text-gray-700 font-medium truncate">{{ rev.goal || '--' }}</span>
                        <span v-if="rev.source" class="text-[10px] text-gray-400 font-mono ml-auto shrink-0" :title="rev.source.did">trace {{ rev.source.trace_id }}</span>
                      </div>
                      <div v-if="rev.constraints?.length" class="flex items-center gap-1 flex-wrap mt-1">
                        <span class="text-gray-400 text-[11px]">约束：</span>
                        <span v-for="(c, j) in rev.constraints" :key="j" class="inline-block bg-gray-100 rounded px-1.5 py-0.5 text-[11px] text-gray-600">{{ c }}</span>
                      </div>
                      <div v-if="rev.prohibitions?.length" class="flex items-center gap-1 flex-wrap mt-1">
                        <span class="text-gray-400 text-[11px]">禁止：</span>
                        <span v-for="(p, j) in rev.prohibitions" :key="j" class="inline-block bg-red-50 text-red-600 rounded px-1.5 py-0.5 text-[11px]">{{ p }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 十字锁定入口 -->
              <div class="flex justify-end -mt-2">
                <button @click="openCrossLock"
                  class="px-3 py-1.5 text-[12px] font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 rounded-lg hover:bg-indigo-100 transition-colors flex items-center gap-1.5"
                ><Layers class="w-3.5 h-3.5" /> 十字锁定综合视图</button>
              </div>

              <!-- Tabs -->
              <div class="flex items-center gap-1 bg-gray-100/60 rounded-xl p-1 flex-wrap">
                <button v-for="tab in ([
                    { key: 'behavior', label: '行为溯源', icon: GitMerge, count: behaviorNodes.length || null },
                    { key: 'hops', label: '逐跳评分', icon: FileText, count: vReport?.hop_scores?.length || null },
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

              <!-- 逐跳评分 -->
              <div v-if="activeTab === 'hops'" class="space-y-4">
                <div v-if="!vReport?.hop_scores?.length" class="text-center py-12 text-gray-400 text-sm">
                  <div v-if="statusKind !== 'completed' && statusKind !== 'uptodate'">触发纵向分析后将生成逐跳评分</div>
                  <div v-else>该会话暂无逐跳评分</div>
                </div>
                <HopScoreCard v-for="h in (vReport?.hop_scores || [])" :key="h.trace_id" :hop="h" />
              </div>

              <!-- 告警（R_T 单点，source=vertical_analysis） -->
              <div v-if="activeTab === 'alerts'" class="space-y-4">
                <div v-if="!vAlerts.length" class="text-center py-16 text-gray-400">
                  <div class="w-14 h-14 rounded-2xl bg-emerald-50 border border-emerald-100 flex items-center justify-center mx-auto mb-3">
                    <CheckCircle2 class="w-7 h-7 text-emerald-400" />
                  </div>
                  <p class="text-sm font-medium text-gray-500">未发现 R_T 告警</p>
                  <p class="text-xs text-gray-300 mt-1">无单点 high/critical 偏离</p>
                </div>
                <div v-for="report in vAlerts" :key="report.id"
                  class="bg-white rounded-xl border-2 overflow-hidden"
                  :class="severityRowCls(report.severity)"
                >
                  <div class="p-4">
                    <div class="flex items-center justify-between mb-2">
                      <div class="flex items-center gap-2">
                        <AlertOctagon :class="['w-4 h-4 shrink-0', (report.severity === 'critical' || report.severity === 'high') ? 'text-red-500' : 'text-amber-500']" />
                        <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-semibold', severityBadgeCls(report.severity)]">{{ report.severity }}</span>
                        <span v-if="report.evidence_type" class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-gray-100 text-gray-500 border border-gray-200">{{ report.evidence_type }}</span>
                      </div>
                      <span class="text-[10px] text-gray-400 shrink-0">{{ formatTime(report.timestamp) }}</span>
                    </div>
                    <p class="text-[13px] text-gray-700 leading-relaxed">{{ report.evidence_description || 'No description available' }}</p>
                    <div class="text-[11px] text-gray-400 font-mono mt-1 flex items-center gap-3 flex-wrap">
                      <span>taint: <span class="text-gray-600">{{ report.taint_score }}</span></span>
                      <span>trace: <span class="text-gray-600">{{ report.raw_evidence?.trace_id ?? '--' }}</span></span>
                    </div>
                    <button v-if="report.target_did" @click="onViewDossier(report.target_did)"
                      class="mt-2 text-[11px] font-mono text-gray-500 hover:text-indigo-600 hover:underline truncate block text-left"
                      :title="report.target_did"
                    >{{ report.target_did }}</button>
                  </div>
                </div>
              </div>
              </div>
              <div v-else class="text-center py-12 text-gray-400 text-sm">输入 Session ID 进行溯源查询</div>
            </template>

            <!-- ============ 横向 ============ -->
            <template v-else>
              <div class="space-y-5">
                <!-- 累计状态 -->
                <div v-if="hState" class="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
                  <div class="flex items-center gap-2">
                    <BarChart3 class="w-4 h-4 text-purple-500" />
                    <span class="text-[13px] font-semibold text-gray-800">累计状态</span>
                  </div>
                  <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">节点类型</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.node_type || '--' }}</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">确认批次</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.batch_index }}</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">累计跳数</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.volume }}</div>
                    </div>
                    <div class="bg-gray-50 rounded-lg p-3 text-center">
                      <div class="text-[11px] text-gray-400 mb-1">确认游标</div>
                      <div class="text-xl font-semibold text-gray-800">{{ hState.last_trace_id }}</div>
                    </div>
                  </div>
                  <!-- F 累积进度（Σ s² vs R_S） -->
                  <FProgress :f-value="hState.f_value" />
                  <!-- ── 分析状态条 ── -->
                  <AnalysisStatusBar
                    :status="currentStatus" :status-kind="statusKind"
                    :polling="hFlow.running.value" :trigger-loading="hFlow.triggerLoading.value"
                    :refresh-disabled="!didInput.trim()" :trigger-disabled="hTriggerDisabled"
                    @refresh="refreshCurrent"
                    @trigger="doTrigger"
                  />
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
