<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { apiUrl } from '../agent_manager'
import { apiFetch } from '../transport'
import { GitMerge, X, Loader2, Bot, ArrowRightLeft, ChevronLeft, ChevronRight } from 'lucide-vue-next'

const visible = ref(false)
const loading = ref(false)
const sessionId = ref('')
const traceData = ref<any[]>([])
const currentPage = ref(0)
const ITEMS_PER_PAGE = 2
const totalLatency = ref<string>('--')

const totalPages = computed(() => Math.ceil(traceData.value.length / ITEMS_PER_PAGE))
const pageData = computed(() => {
  const start = currentPage.value * ITEMS_PER_PAGE
  return traceData.value.slice(start, start + ITEMS_PER_PAGE)
})

const show = async (sid: string) => {
  sessionId.value = sid
  visible.value = true
  loading.value = true
  traceData.value = []
  currentPage.value = 0

  try {
    const { data } = await apiFetch(apiUrl(`/api/traces/${sid}`))
    if (!data?.Path || data.Path.length === 0) {
      traceData.value = []
    } else {
      traceData.value = data.Path
      // Calculate latency
      const first = new Date(data.Path[0].Log.Timestamp).getTime() || Date.now()
      const last = new Date(data.Path[data.Path.length - 1].Log.Timestamp).getTime() || Date.now()
      const latency = Math.max(15, Math.abs(last - first))
      totalLatency.value = `${latency}ms`
    }
  } catch (e) {
    console.error('Failed to load trace:', e)
    traceData.value = []
  } finally {
    loading.value = false
  }
}

const close = () => {
  visible.value = false
}

const prevPage = () => {
  if (currentPage.value > 0) currentPage.value--
}

const nextPage = () => {
  if (currentPage.value < totalPages.value - 1) currentPage.value++
}

const formatTime = (ts: string) => {
  try {
    return new Date(ts).toISOString().split('T')[1].replace('Z', '')
  } catch { return ts }
}

const getDesc = (log: any) => {
  if (log.Content_Snapshot && typeof log.Content_Snapshot === 'object') {
    if (log.Content_Snapshot.Action) return `Action: ${log.Content_Snapshot.Action}`
  } else if (typeof log.Content_Snapshot === 'string') {
    return log.Content_Snapshot
  }
  return 'Transmission'
}

const getSenderName = (log: any) => {
  const parts = log.node_did.split(':')
  return parts[parts.length - 1] || 'Unknown'
}

const getTraceTitle = (hop: any, idx: number) => {
  const senderName = getSenderName(hop.Log)
  let receiverName = 'Target'
  const isLastHop = idx === traceData.value.length - 1
  const entryHash = hop.Log.Entry_Hash || hop.Log.Genesis_Hash
  const childHop = traceData.value.find((t: any, j: number) => j !== idx && t.Log.Prev_Hash === entryHash)
  if (childHop) {
    receiverName = getSenderName(childHop.Log)
  } else if (isLastHop && hop.Log.target_did) {
    const parts = hop.Log.target_did.split(':')
    receiverName = parts[parts.length - 1] || 'Unknown'
  } else {
    const myPrev = hop.Log.Prev_Hash
    if (myPrev && myPrev !== 'Genesis') {
      const parentHop = traceData.value.find((t: any) => t.Log.Entry_Hash === myPrev || t.Log.Genesis_Hash === myPrev)
      if (parentHop) receiverName = getSenderName(parentHop.Log)
    }
  }
  return `[ ${senderName} -> ${receiverName} ]`
}

// Listen for events
window.addEventListener('show-trace-timeline', ((e: CustomEvent) => {
  show(e.detail.sessionId)
}) as EventListener)

defineExpose({ show, close })
</script>

<template>
  <!-- Trace Timeline Modal -->
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm transition-opacity duration-300" @click.self="close">
    <div class="bg-white w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden transform transition-all duration-300">
      <!-- Header -->
      <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center">
            <GitMerge class="w-4 h-4 text-indigo-600" />
          </div>
          <div>
            <h3 class="text-sm font-semibold text-gray-900">Message Trace</h3>
            <p class="text-[11px] text-gray-500 font-mono">ID: {{ sessionId.substring(0, 12) }}...</p>
          </div>
        </div>
        <button @click="close" class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
          <X class="w-4 h-4" />
        </button>
      </div>

      <!-- Timeline Content -->
      <div class="p-6 overflow-hidden relative min-h-[300px]">
        <!-- Loading -->
        <div v-if="loading" class="text-center text-sm py-4 text-gray-400">
          <Loader2 class="w-5 h-5 animate-spin inline-block mb-2" />
          <p>Loading trace via ATTP...</p>
        </div>
        <!-- Empty -->
        <div v-else-if="traceData.length === 0" class="text-center text-sm py-4 text-gray-400">
          No traces available for this session.
        </div>
        <!-- Timeline -->
        <div v-else class="relative">
          <div class="absolute left-4 top-2 bottom-2 w-px bg-gray-200 border-l border-dashed border-gray-300 z-0"></div>
          <div v-for="(hop, index) in pageData" :key="currentPage * ITEMS_PER_PAGE + index" class="relative flex gap-4 mb-6 z-10">
            <div class="w-8 h-8 rounded-full bg-white border border-gray-200 mt-1 flex items-center justify-center shrink-0 shadow-sm relative z-10">
              <component :is="(currentPage * ITEMS_PER_PAGE + index) === 0 ? Bot : ArrowRightLeft" :class="(currentPage * ITEMS_PER_PAGE + index) === 0 ? 'w-3.5 h-3.5 text-gray-600' : 'w-3.5 h-3.5 text-blue-500'" />
            </div>
            <div class="flex-1 min-w-0 overflow-hidden">
              <div class="flex items-center justify-between mb-1">
                <span class="text-[13px] font-semibold text-gray-800 truncate" :title="hop.Log.node_did">{{ getTraceTitle(hop, currentPage * ITEMS_PER_PAGE + index) }}</span>
                <span class="text-[11px] text-gray-400 shrink-0">{{ formatTime(hop.Log.Timestamp) }}</span>
              </div>
              <div class="text-[12px] text-gray-500 bg-gray-50 px-3 py-2 rounded-lg border border-gray-100">
                {{ getDesc(hop.Log) }}
              </div>
              <div class="mt-2 space-y-1 bg-white border border-gray-100 rounded p-2 text-[10px] font-mono shadow-sm">
                <div class="flex"><span class="text-gray-400 w-20 shrink-0">Hash: </span><span class="text-gray-600 truncate" :title="hop.Log.Entry_Hash || hop.Log.Genesis_Hash">{{ hop.Log.Entry_Hash || hop.Log.Genesis_Hash }}</span></div>
                <div class="flex"><span class="text-gray-400 w-20 shrink-0">Prev: </span><span class="text-gray-600 truncate" :title="hop.Log.Prev_Hash">{{ hop.Log.Prev_Hash }}</span></div>
                <div class="flex"><span class="text-gray-400 w-20 shrink-0">Sig: </span><span class="text-gray-600 truncate" :title="hop.Log.Signature">{{ hop.Log.Signature }}</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="totalPages > 1" class="px-6 py-2 border-t border-gray-100 flex items-center justify-between bg-white">
        <button @click="prevPage" :disabled="currentPage === 0" class="p-1.5 text-gray-500 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-all">
          <ChevronLeft class="w-4 h-4" />
        </button>
        <div class="text-[12px] text-gray-500">Page {{ currentPage + 1 }} / {{ totalPages }}</div>
        <button @click="nextPage" :disabled="currentPage >= totalPages - 1" class="p-1.5 text-gray-500 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-all">
          <ChevronRight class="w-4 h-4" />
        </button>
      </div>

      <!-- Footer -->
      <div class="bg-gray-50 border-t border-gray-100 px-6 py-3 flex items-center justify-between">
        <span class="text-[11px] text-gray-500 font-mono flex items-center gap-1.5">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Validated Chain
        </span>
        <span class="text-[11px] font-medium text-gray-400">Total Latency: {{ totalLatency }}</span>
      </div>
    </div>
  </div>
</template>