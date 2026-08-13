<script setup lang="ts">
/**
 * BehaviorChain — 行为溯源时间线（按 hop 节点聚合）。
 * 纵向/横向视图共用。
 */
import {
  fieldTypes, fieldTypeConfig, verificationBadge, formatTime,
} from '../../../composables/useTraceFormat'
import type { HopNode } from '../types'

defineProps<{ nodes: HopNode[] }>()
</script>

<template>
  <div>
    <div v-if="nodes.length === 0" class="text-center py-12 text-gray-400 text-sm">
      该会话暂无行为溯源数据
    </div>

    <div v-else class="relative">
      <div class="absolute left-[19px] top-3 bottom-3 w-px bg-gray-200 border-l border-dashed border-gray-300 z-0"></div>

      <div v-for="node in nodes" :key="node.hop_count.join('.')" class="relative flex gap-4 mb-8 z-10">
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
</template>
