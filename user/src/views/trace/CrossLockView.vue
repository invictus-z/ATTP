<script setup lang="ts">
/**
 * 十字锁定综合视图 — 纵向逐跳评分 × 横向 F 累加，一次聚出全景。
 *
 * GET /api/analysis/cross-lock/{session_id}?protocol_node_address=
 *   → vertical { hop_scores, overall_verdict, total_hops, alerts }
 *     horizontal { tracked_dids: [{did, f_value, volume, batch_index, last_horizontal_analysis}] }
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loader2, Search, Crosshair, BarChart3, AlertTriangle } from 'lucide-vue-next'
import { apiFetch } from '../../transport'
import { useProtocolNodes } from '../../composables/useProtocolNodes'
import { useToast } from '../../composables/useToast'
import { verdictBadge, formatTime, formatDid } from '../../composables/useTraceFormat'
import type { HopScore, MaliciousReport, OverallVerdict } from './types'
import NodeSelector from './components/NodeSelector.vue'
import HopScoreCard from './components/HopScoreCard.vue'
import FProgress from './components/FProgress.vue'
import DimRadar from './components/DimRadar.vue'

interface LastHorizontalAnalysis {
  batch_index: number
  confirmed: boolean
  overall_verdict: OverallVerdict | null
  timestamp: number | null
}
interface TrackedDid {
  did: string
  f_value: number
  volume: number
  batch_index: number
  last_horizontal_analysis: LastHorizontalAnalysis | null
}
interface CrossLockData {
  session_id: string
  vertical: {
    traces: number
    hop_scores: HopScore[]
    overall_verdict: OverallVerdict
    total_hops: number
    alerts: MaliciousReport[]
  }
  horizontal: { tracked_dids: TrackedDid[] }
}

const route = useRoute()
const router = useRouter()
const { selectedNode, selectedNodeId, loadNodes, ensureSelection, buildUrl } = useProtocolNodes()
const { showToast } = useToast()

const sessionIdInput = ref('')
const loading = ref(false)
const data = ref<CrossLockData | null>(null)

/** 聚合四维（各跳取最大）供雷达图 */
const maxDims = computed<number[]>(() => {
  const scores = data.value?.vertical?.hop_scores || []
  const acc = [0, 0, 0, 0]
  for (const h of scores) {
    const d = h.dimensions || [0, 0, 0, 0]
    for (let i = 0; i < 4; i++) acc[i] = Math.max(acc[i], Number(d[i]) || 0)
  }
  return acc
})

const maxScore = computed(() =>
  (data.value?.vertical?.hop_scores || []).reduce((m, h) => Math.max(m, h.score), 0),
)

async function fetchCrossLock(sid: string) {
  if (!selectedNode.value || !sid) return
  const pna = encodeURIComponent(selectedNode.value.url)
  const url = buildUrl(`/api/analysis/cross-lock/${encodeURIComponent(sid)}?protocol_node_address=${pna}`)
  const res = await apiFetch(url)
  data.value = res.ok ? res.data : null
}

async function doQuery() {
  if (!selectedNode.value) { showToast('请先选择协议节点', 'error'); return }
  const sid = sessionIdInput.value.trim()
  if (!sid) return
  loading.value = true
  try {
    await fetchCrossLock(sid)
  } finally {
    loading.value = false
  }
}

function onViewDossier(did: string) {
  router.push({ path: '/trace/malicious', query: { did } })
}

onMounted(() => {
  loadNodes()
  setTimeout(() => {
    ensureSelection()
    const qSid = route.query.sessionId as string | undefined
    const pNodeUrl = route.query.protocolNodeUrl as string | undefined
    if (pNodeUrl) {
      const matched = useProtocolNodes().traceNodes.value.find(
        n => n.url.replace(/\/+$/, '') === pNodeUrl.replace(/\/+$/, ''),
      )
      if (matched) selectedNodeId.value = matched.id
    }
    if (qSid) { sessionIdInput.value = qSid; void doQuery() }
  }, 1500)
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-5xl mx-auto">
        <h2 class="text-xl font-semibold text-gray-900 tracking-tight mb-1.5">十字锁定综合视图</h2>
        <p class="text-sm text-gray-500">纵向逐跳评分 × 横向 F 累加，一次聚出全景</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto">
      <div class="max-w-5xl mx-auto p-8 space-y-6 pb-8">

        <!-- ── 查询栏 ── -->
        <div class="bg-white rounded-2xl border border-gray-200 p-5 space-y-3">
          <NodeSelector />
          <div class="flex items-end gap-3 pt-3 border-t border-gray-100">
            <div class="flex-1">
              <label class="block text-[11px] font-medium text-gray-400 mb-1.5">Session ID</label>
              <div class="relative">
                <Crosshair class="w-4 h-4 text-gray-400 absolute left-3 top-2.5 pointer-events-none" />
                <input v-model="sessionIdInput" placeholder="输入 Session ID"
                  class="w-full pl-9 pr-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors font-mono placeholder:text-gray-300"
                  @keydown.enter="doQuery()"
                />
              </div>
            </div>
            <button @click="doQuery()" :disabled="!selectedNodeId || !sessionIdInput.trim() || loading"
              class="px-5 py-2.5 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
              <Search v-else class="w-4 h-4" /> 查询
            </button>
          </div>
        </div>

        <!-- ── 加载中 ── -->
        <div v-if="loading" class="flex items-center justify-center py-16 text-gray-400">
          <Loader2 class="w-5 h-5 animate-spin mr-2" />
          <span class="text-sm">正在聚合十字锁定数据...</span>
        </div>

        <!-- ── 结果 ── -->
        <template v-else-if="data">
          <!-- 纵轴 -->
          <div class="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <BarChart3 class="w-4 h-4 text-indigo-500" />
                <span class="text-[13px] font-semibold text-gray-800">纵轴 · 逐跳评分</span>
              </div>
              <div class="flex items-center gap-2 text-[11px]">
                <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', verdictBadge(data.vertical.overall_verdict).cls]">
                  {{ verdictBadge(data.vertical.overall_verdict).text }}
                </span>
                <span class="text-gray-400">hops <span class="font-mono text-gray-600">{{ data.vertical.total_hops }}</span></span>
                <span class="text-gray-400">max <span class="font-mono text-gray-600">{{ Number(maxScore).toFixed(1) }}</span></span>
                <span v-if="data.vertical.alerts?.length" class="text-gray-400">alerts <span class="font-mono text-red-600">{{ data.vertical.alerts.length }}</span></span>
              </div>
            </div>

            <div class="flex gap-5 items-center">
              <DimRadar :dimensions="maxDims" :size="130" />
              <div class="text-[11px] text-gray-400 leading-relaxed">
                <p>雷达为各维度<strong class="text-gray-600">跨跳最大值</strong>（峰值暴露面）。</p>
                <p class="mt-1">逐跳明细见下，可定位峰值出现在哪一跳。</p>
              </div>
            </div>

            <div v-if="data.vertical.hop_scores?.length" class="space-y-3 pt-2 border-t border-gray-100">
              <HopScoreCard v-for="h in data.vertical.hop_scores" :key="h.trace_id" :hop="h" />
            </div>
            <div v-else class="text-center py-8 text-gray-400 text-sm">该会话暂无逐跳评分</div>
          </div>

          <!-- 横轴 -->
          <div class="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
            <div class="flex items-center gap-2">
              <AlertTriangle class="w-4 h-4 text-purple-500" />
              <span class="text-[13px] font-semibold text-gray-800">横轴 · 各 DID F 累积</span>
              <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-purple-100 text-purple-600 border border-purple-200">{{ data.horizontal.tracked_dids.length }}</span>
            </div>
            <div v-if="data.horizontal.tracked_dids.length" class="space-y-2">
              <div v-for="t in data.horizontal.tracked_dids" :key="t.did"
                class="p-3 rounded-lg border flex items-center gap-3 flex-wrap"
                :class="t.f_value > 25 ? 'bg-red-50/50 border-red-200' : 'bg-gray-50 border-gray-100'"
              >
                <button @click="onViewDossier(t.did)"
                  class="font-mono text-[12px] text-gray-600 hover:text-indigo-600 hover:underline truncate flex-1 min-w-[180px] text-left"
                  :title="t.did"
                >{{ formatDid(t.did) }}</button>
                <div class="w-44 shrink-0"><FProgress :f-value="t.f_value" /></div>
                <span class="text-[11px] text-gray-400 shrink-0">vol {{ t.volume }}</span>
                <span class="text-[11px] text-gray-400 shrink-0">batch {{ t.batch_index }}</span>
                <div v-if="t.last_horizontal_analysis" class="flex items-center gap-1 text-[10px] shrink-0">
                  <span :class="['px-1.5 py-0.5 rounded border font-medium', t.last_horizontal_analysis.confirmed ? 'bg-red-50 text-red-600 border-red-200' : 'bg-emerald-50 text-emerald-600 border-emerald-200']">
                    {{ t.last_horizontal_analysis.confirmed ? '确认恶意' : '判为良性' }}
                  </span>
                  <span v-if="t.last_horizontal_analysis.overall_verdict"
                    :class="['px-1.5 py-0.5 rounded border font-medium', verdictBadge(t.last_horizontal_analysis.overall_verdict).cls]"
                  >{{ verdictBadge(t.last_horizontal_analysis.overall_verdict).text }}</span>
                  <span class="text-gray-400">{{ formatTime(t.last_horizontal_analysis.timestamp) }}</span>
                </div>
                <span v-else class="text-[10px] text-gray-300 shrink-0">未确认</span>
              </div>
            </div>
            <div v-else class="text-center py-8 text-gray-400 text-sm">无涉及的 DID</div>
          </div>
        </template>

        <!-- ── 未查询 ── -->
        <div v-else class="text-center py-12 text-gray-400 text-sm">输入 Session ID 查询十字锁定视图</div>

      </div>
    </div>
  </div>
</template>
