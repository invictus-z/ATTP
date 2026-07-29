<script setup lang="ts">
/**
 * 视图3 — 恶意报告。
 *
 * 全局恶意节点档案（dossiers）列表，支持来源 / severity 筛选；
 * 点击档案展开违规明细（incidents）。会话级恶意报告统一并入此视图。
 *
 *   GET /api/malicious/dossiers?source=&severity=&limit=
 *   GET /api/malicious/dossier/{did}
 */
import { ref, computed, onMounted, onScopeDispose } from 'vue'
import { useRoute } from 'vue-router'
import {
  UserX, Eye, RefreshCw, CheckCircle2, Loader2, ChevronDown, ChevronRight,
  X, AlertTriangle,
} from 'lucide-vue-next'
import { apiFetch } from '../../transport'
import { useProtocolNodes } from '../../composables/useProtocolNodes'
import { useToast } from '../../composables/useToast'
import { onMaliciousDetected } from '../../composables/nodeEvents'
import {
  severityLevelBadge, sourceBadge, severityBadgeCls, severityRowCls, formatTime, formatDid,
} from '../../composables/useTraceFormat'
import type { MaliciousDossier, MaliciousReport } from './types'
import NodeSelector from './components/NodeSelector.vue'

const route = useRoute()
const { selectedNodeId, selectedNode, loadNodes, ensureSelection, buildUrl } = useProtocolNodes()
const { showToast } = useToast()

const sourceFilter = ref('')
const severityFilter = ref('')
const dossiersData = ref<{ total: number; dossiers: MaliciousDossier[] } | null>(null)
const loading = ref(false)

const lastUpdated = ref<number | null>(null) // ms 时间戳

const lastUpdatedLabel = computed(() =>
  lastUpdated.value ? new Date(lastUpdated.value).toLocaleTimeString('zh-CN', { hour12: false }) : '未更新',
)

const selectedDid = ref<string | null>(null)
const detailOpen = ref(false)
const dossierDetail = ref<MaliciousDossier | null>(null)
const detailLoading = ref(false)
const incidentSourceFilter = ref('')

const filteredIncidents = computed<MaliciousReport[]>(() => {
  const list = dossierDetail.value?.incidents || []
  if (!incidentSourceFilter.value) return list
  return list.filter(r => r.source === incidentSourceFilter.value)
})

async function fetchDossiers() {
  if (!selectedNode.value) return
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (sourceFilter.value) params.set('source', sourceFilter.value)
    if (severityFilter.value) params.set('severity', severityFilter.value)
    params.set('limit', '200')
    const qs = params.toString()
    const url = buildUrl(`/api/malicious/dossiers${qs ? '?' + qs : ''}`)
    const res = await apiFetch(url)
    if (res.ok) {
      dossiersData.value = res.data
      lastUpdated.value = Date.now()
    }
  } catch {
    showToast('获取恶意档案失败', 'error')
  } finally {
    loading.value = false
  }
}

// ── 恶意事件刷新：订阅全局常驻连接（App.vue 维护）的 malicious.detected ──
// 全局 toast 在 App.vue 已处理；本视图仅负责收到事件时刷新档案列表。
let offMalicious: (() => void) | null = null

function registerMaliciousHandler() {
  if (offMalicious) return
  offMalicious = onMaliciousDetected(() => { void fetchDossiers() })
}

onScopeDispose(() => {
  if (offMalicious) { offMalicious(); offMalicious = null }
})

async function fetchDossierDetail(did: string) {
  if (!selectedNode.value) return
  detailLoading.value = true
  try {
    const url = buildUrl(`/api/malicious/dossier/${encodeURIComponent(did)}`)
    const res = await apiFetch(url)
    if (res.ok && res.data.found) {
      dossierDetail.value = res.data
      detailOpen.value = true
    } else {
      dossierDetail.value = null
      showToast('未找到该 DID 的档案', 'error')
    }
  } catch {
    showToast('获取档案详情失败', 'error')
  } finally {
    detailLoading.value = false
  }
}

function openDossier(did: string) {
  selectedDid.value = did
  incidentSourceFilter.value = ''
  void fetchDossierDetail(did)
}

function closeDetail() {
  detailOpen.value = false
  selectedDid.value = null
  dossierDetail.value = null
}

onMounted(() => {
  loadNodes()
  setTimeout(() => {
    ensureSelection()
    if (selectedNode.value) {
      void fetchDossiers()
      registerMaliciousHandler()
    }
    const qDid = route.query.did as string | undefined
    if (qDid) { selectedDid.value = qDid; void fetchDossierDetail(qDid) }
  }, 1500)
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-5xl mx-auto">
        <h2 class="text-xl font-semibold text-gray-900 tracking-tight mb-1.5">恶意报告</h2>
        <p class="text-sm text-gray-500">恶意节点档案 · 来源筛选 · 违规明细追踪</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto">
      <div class="max-w-5xl mx-auto p-8 space-y-6 pb-8">

        <!-- ── 筛选栏 ── -->
        <div class="bg-white rounded-2xl border border-gray-200 p-5">
          <div class="flex items-center gap-3 flex-wrap mb-4">
            <NodeSelector />
            <button @click="fetchDossiers" :disabled="!selectedNodeId || loading"
              class="px-4 py-2.5 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
              <Eye v-else class="w-4 h-4" /> 查询档案
            </button>
          </div>
          <div class="flex items-center gap-3 flex-wrap pt-3 border-t border-gray-100">
            <div class="flex items-center gap-2">
              <span class="text-[12px] text-gray-500">来源</span>
              <select v-model="sourceFilter" @change="fetchDossiers"
                class="px-3 py-1.5 text-[12px] border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
              >
                <option value="">全部来源</option>
                <option value="protocol_review">协议审查</option>
                <option value="vertical_analysis">纵向分析</option>
                <option value="horizontal_analysis">横向分析</option>
              </select>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[12px] text-gray-500">等级</span>
              <select v-model="severityFilter" @change="fetchDossiers"
                class="px-3 py-1.5 text-[12px] border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
              >
                <option value="">全部等级</option>
                <option value="warning">Warning</option>
                <option value="dangerous">Dangerous</option>
                <option value="banned">Banned</option>
              </select>
            </div>
            <div class="ml-auto flex items-center gap-3 text-[11px] text-gray-400">
              <span class="flex items-center gap-1">
                <RefreshCw class="w-3 h-3" :class="loading ? 'animate-spin' : ''" />
                最近更新 {{ lastUpdatedLabel }}
              </span>
              <span>共 {{ dossiersData?.total ?? 0 }} 个档案</span>
            </div>
          </div>
        </div>

        <!-- ── 未选节点 ── -->
        <div v-if="!selectedNodeId" class="flex flex-col items-center justify-center py-20 text-gray-400">
          <p class="text-sm">请先选择一个协议节点</p>
        </div>

        <template v-else>
          <!-- 加载 -->
          <div v-if="loading" class="flex items-center justify-center py-16 text-gray-400">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span class="text-sm">正在加载恶意档案...</span>
          </div>

          <template v-else>
            <!-- 空状态 -->
            <div v-if="!dossiersData || dossiersData.dossiers.length === 0" class="bg-white rounded-2xl border border-dashed border-gray-200 py-16 text-center">
              <CheckCircle2 class="w-10 h-10 text-emerald-300 mx-auto mb-3" />
              <p class="text-sm text-gray-400">暂无已知恶意节点档案</p>
            </div>

            <!-- 档案列表 -->
            <div v-else class="space-y-3">
              <button v-for="dossier in dossiersData.dossiers" :key="dossier.did"
                @click="openDossier(dossier.did)"
                :class="['w-full text-left p-4 rounded-xl border transition-all hover:border-gray-300 hover:shadow-sm',
                  selectedDid === dossier.did ? 'border-indigo-300 bg-indigo-50/30' : 'border-gray-200 bg-white']"
              >
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', severityLevelBadge(dossier.severity_level).cls]">
                      {{ severityLevelBadge(dossier.severity_level).text }}
                    </span>
                    <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600 border border-gray-200">
                      {{ dossier.total_violations }} violations
                    </span>
                  </div>
                  <ChevronRight class="w-4 h-4 text-gray-300" />
                </div>

                <div class="text-[12px] font-mono text-gray-600 truncate mb-1.5" :title="dossier.did">{{ dossier.did }}</div>

                <div class="flex items-center gap-3 text-[11px] text-gray-400 mb-2">
                  <span>首次: {{ formatTime(dossier.first_seen_at) }}</span>
                  <span>最近: {{ formatTime(dossier.last_seen_at) }}</span>
                </div>

                <!-- 来源分布徽章 -->
                <div v-if="dossier.source_breakdown && Object.keys(dossier.source_breakdown).length" class="flex flex-wrap gap-1.5 mb-2">
                  <span v-for="(count, src) in dossier.source_breakdown" :key="String(src)"
                    :class="['px-1.5 py-0.5 rounded text-[9px] font-medium border', sourceBadge(String(src)).cls]"
                  >{{ sourceBadge(String(src)).text }} ({{ count }})</span>
                </div>

                <div v-if="dossier.last_evidence_desc" class="text-[11px] text-gray-500">
                  <span class="text-gray-400">最近事件：</span>{{ dossier.last_evidence_desc }}
                </div>
              </button>
            </div>
          </template>
        </template>

      </div>
    </div>

    <!-- ── 档案详情抽屉 ── -->
    <transition name="toast">
      <div v-if="detailOpen" class="fixed inset-0 z-50 flex justify-end bg-black/30" @click.self="closeDetail">
        <div class="bg-white w-full max-w-2xl h-full overflow-y-auto shadow-2xl">
          <!-- 抽屉加载 -->
          <div v-if="detailLoading" class="flex items-center justify-center py-20 text-gray-400">
            <Loader2 class="w-5 h-5 animate-spin mr-2" />
            <span class="text-sm">加载档案详情...</span>
          </div>

          <template v-else-if="dossierDetail">
            <div class="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between z-10">
              <div class="flex items-center gap-2 min-w-0">
                <UserX class="w-4 h-4 text-red-500 shrink-0" />
                <span class="text-[13px] font-semibold text-gray-800 truncate">恶意节点档案</span>
                <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border shrink-0', severityLevelBadge(dossierDetail.severity_level).cls]">
                  {{ severityLevelBadge(dossierDetail.severity_level).text }}
                </span>
              </div>
              <button @click="closeDetail" class="p-1 text-gray-400 hover:text-gray-600"><X class="w-4 h-4" /></button>
            </div>

            <div class="p-6 space-y-5">
              <!-- 基本信息 -->
              <div>
                <div class="text-[11px] font-medium text-gray-400 mb-1">DID</div>
                <div class="bg-gray-50 rounded-lg px-3 py-2 text-[12px] font-mono text-gray-700 break-all">{{ dossierDetail.did }}</div>
              </div>

              <div class="grid grid-cols-3 gap-3">
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[10px] text-gray-400 mb-1">违规总数</div>
                  <div class="text-lg font-semibold text-gray-800">{{ dossierDetail.total_violations }}</div>
                </div>
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[10px] text-gray-400 mb-1">首次发现</div>
                  <div class="text-[11px] font-medium text-gray-700">{{ formatTime(dossierDetail.first_seen_at) }}</div>
                </div>
                <div class="bg-gray-50 rounded-lg p-3 text-center">
                  <div class="text-[10px] text-gray-400 mb-1">最近活动</div>
                  <div class="text-[11px] font-medium text-gray-700">{{ formatTime(dossierDetail.last_seen_at) }}</div>
                </div>
              </div>

              <!-- 来源 + 证据分布 -->
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <div class="text-[11px] font-medium text-gray-400 mb-1.5">来源分布</div>
                  <div v-if="dossierDetail.source_breakdown && Object.keys(dossierDetail.source_breakdown).length" class="flex flex-wrap gap-1.5">
                    <span v-for="(count, src) in dossierDetail.source_breakdown" :key="String(src)"
                      :class="['px-2 py-0.5 rounded-md text-[10px] font-medium border', sourceBadge(String(src)).cls]"
                    >{{ sourceBadge(String(src)).text }} ×{{ count }}</span>
                  </div>
                  <span v-else class="text-[11px] text-gray-300">无</span>
                </div>
                <div>
                  <div class="text-[11px] font-medium text-gray-400 mb-1.5">证据类型分布</div>
                  <div v-if="dossierDetail.evidence_breakdown && Object.keys(dossierDetail.evidence_breakdown).length" class="flex flex-wrap gap-1.5">
                    <span v-for="(count, etype) in dossierDetail.evidence_breakdown" :key="String(etype)"
                      class="px-1.5 py-0.5 rounded text-[9px] font-medium bg-gray-100 text-gray-500 border border-gray-200"
                    >{{ String(etype) }} ({{ count }})</span>
                  </div>
                  <span v-else class="text-[11px] text-gray-300">无</span>
                </div>
              </div>

              <!-- 违规明细 -->
              <div>
                <div class="flex items-center justify-between mb-3">
                  <div class="flex items-center gap-2">
                    <AlertTriangle class="w-4 h-4 text-amber-500" />
                    <span class="text-[13px] font-semibold text-gray-800">违规明细</span>
                    <span class="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-500 border border-gray-200">
                      {{ (dossierDetail.incidents || []).length }}
                    </span>
                  </div>
                  <select v-model="incidentSourceFilter"
                    class="px-2.5 py-1 text-[11px] border border-gray-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200"
                  >
                    <option value="">全部来源</option>
                    <option value="protocol_review">协议审查</option>
                    <option value="vertical_analysis">纵向分析</option>
                    <option value="horizontal_analysis">横向分析</option>
                  </select>
                </div>

                <div v-if="filteredIncidents.length === 0" class="text-center py-8 text-gray-400 text-[12px]">无符合条件的明细</div>

                <div v-else class="space-y-3">
                  <div v-for="report in filteredIncidents" :key="report.id"
                    class="p-3 rounded-lg border"
                    :class="severityRowCls(report.severity)"
                  >
                    <div class="flex items-center justify-between mb-2">
                      <div class="flex items-center gap-2">
                        <span :class="['px-2 py-0.5 rounded-md text-[10px] font-semibold border', sourceBadge(report.source).cls]">
                          {{ sourceBadge(report.source).text }}
                        </span>
                        <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadgeCls(report.severity)]">
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
                        <span>{{ report.node_type || '--' }}</span>
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
            </div>
          </template>
        </div>
      </div>
    </transition>
  </div>
</template>
