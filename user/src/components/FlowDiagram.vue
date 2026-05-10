<script setup lang="ts">
import { ref, computed } from 'vue'
import { apiUrl } from '../agent_manager'
import { apiFetch } from '../transport'
import { Network, X, Loader2, ShieldCheck, ArrowRight } from 'lucide-vue-next'

const visible = ref(false)
const loading = ref(false)
const flowNodes = ref<any[]>([])
const flowEdges = ref<any[]>([])

const show = async () => {
  visible.value = true
  loading.value = true
  flowNodes.value = []
  flowEdges.value = []

  try {
    const { data } = await apiFetch(apiUrl('/api/trace/flow'))
    if (data?.nodes) {
      flowNodes.value = data.nodes
      flowEdges.value = data.edges || []
    }
  } catch (e) {
    console.error('Failed to load flow diagram:', e)
  } finally {
    loading.value = false
  }
}

const close = () => { visible.value = false }

window.addEventListener('show-flow-diagram', (() => { show() }) as EventListener)

defineExpose({ show, close })
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm transition-opacity duration-300" @click.self="close">
    <div class="bg-white w-full max-w-2xl rounded-2xl shadow-2xl overflow-hidden transform transition-all duration-300">
      <!-- Header -->
      <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 rounded-lg bg-violet-50 border border-violet-100 flex items-center justify-center">
            <Network class="w-4 h-4 text-violet-600" />
          </div>
          <h3 class="text-sm font-semibold text-gray-900">ATTP Flow Diagram</h3>
        </div>
        <button @click="close" class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
          <X class="w-4 h-4" />
        </button>
      </div>

      <!-- Content -->
      <div class="p-6 min-h-[400px] max-h-[500px] overflow-y-auto">
        <div v-if="loading" class="flex items-center justify-center py-16 text-gray-400">
          <Loader2 class="w-5 h-5 animate-spin mr-2" />
          <span class="text-sm">Loading flow diagram...</span>
        </div>

        <div v-else-if="flowNodes.length === 0" class="flex flex-col items-center justify-center py-16 text-gray-400">
          <div class="w-12 h-12 rounded-xl bg-gray-50 flex items-center justify-center mb-3">
            <Network class="w-6 h-6 text-gray-300" />
          </div>
          <p class="text-sm">No flow data available</p>
        </div>

        <div v-else class="space-y-4">
          <!-- Nodes -->
          <div class="space-y-3">
            <div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Nodes</div>
            <div class="grid grid-cols-2 gap-3">
              <div v-for="node in flowNodes" :key="node.id" class="bg-white border border-gray-100 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow">
                <div class="flex items-center gap-3 mb-2">
                  <div class="w-8 h-8 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center">
                    <ShieldCheck class="w-4 h-4 text-emerald-600" />
                  </div>
                  <div>
                    <div class="text-sm font-medium text-gray-900">{{ node.name || node.id }}</div>
                    <div class="text-[10px] text-gray-400 font-mono truncate max-w-[180px]" :title="node.did">{{ node.did || '' }}</div>
                  </div>
                </div>
                <div v-if="node.status" class="flex items-center gap-1.5">
                  <span :class="node.status === 'online' ? 'w-1.5 h-1.5 rounded-full bg-emerald-500' : 'w-1.5 h-1.5 rounded-full bg-gray-300'"></span>
                  <span class="text-[10px] text-gray-500">{{ node.status }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Edges -->
          <div v-if="flowEdges.length > 0" class="space-y-3">
            <div class="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Connections</div>
            <div class="space-y-2">
              <div v-for="(edge, idx) in flowEdges" :key="idx" class="flex items-center gap-3 bg-gray-50 rounded-lg px-4 py-2.5 border border-gray-100">
                <span class="text-xs font-medium text-gray-700">{{ edge.from }}</span>
                <ArrowRight class="w-3.5 h-3.5 text-gray-400" />
                <span class="text-xs font-medium text-gray-700">{{ edge.to }}</span>
                <span v-if="edge.label" class="text-[10px] text-gray-400 ml-auto font-mono">{{ edge.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="bg-gray-50 border-t border-gray-100 px-6 py-3 flex items-center justify-between">
        <span class="text-[11px] text-gray-500">{{ flowNodes.length }} nodes · {{ flowEdges.length }} connections</span>
        <button @click="close" class="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">Close</button>
      </div>
    </div>
  </div>
</template>