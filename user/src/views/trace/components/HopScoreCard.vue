<script setup lang="ts">
/**
 * HopScoreCard — 单跳评分卡片（纵轴 V-Reasoner 输出）。
 *
 * 展示 score / severity 徽章 / 4 维横条（d1意图对齐 / d2能力 / d3注入 / d4外泄）
 * / breadth / deviation_type / 证据引用。
 */
import { fieldTypeConfig, severityBadgeCls, formatTime, formatDid } from '../../../composables/useTraceFormat'
import { DIMENSION_LABELS, type HopScore } from '../types'

defineProps<{ hop: HopScore }>()
</script>

<template>
  <div class="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
    <!-- 头部：hop 标识 + field_type + sender + score + severity -->
    <div class="flex items-center justify-between mb-3 gap-2">
      <div class="flex items-center gap-2 min-w-0">
        <span class="text-[12px] font-semibold text-gray-800 shrink-0">
          Hop {{ hop.hop_count?.[0] }}.{{ hop.hop_count?.[1] }}
        </span>
        <span v-if="hop.field_type"
          :class="['px-1.5 py-0.5 rounded-md text-[9px] font-semibold border shrink-0',
            fieldTypeConfig[hop.field_type]?.bg, fieldTypeConfig[hop.field_type]?.color, fieldTypeConfig[hop.field_type]?.border]"
        >
          {{ fieldTypeConfig[hop.field_type]?.label || hop.field_type }}
        </span>
        <span class="text-[11px] font-mono text-gray-400 truncate" :title="hop.sender_did">{{ formatDid(hop.sender_did) }}</span>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <span :class="['px-1.5 py-0.5 rounded border text-[9px] font-medium', severityBadgeCls(hop.severity)]">{{ hop.severity }}</span>
        <span class="text-[10px] text-gray-400">score</span>
        <span class="text-lg font-bold tabular-nums"
          :class="hop.score >= 7.5 ? 'text-red-600' : hop.score >= 5.5 ? 'text-amber-600' : 'text-gray-700'"
        >{{ Number(hop.score).toFixed(1) }}</span>
      </div>
    </div>

    <!-- 4 维横条 -->
    <div class="space-y-1.5 mb-3">
      <div v-for="(d, i) in (hop.dimensions || [0, 0, 0, 0])" :key="i" class="flex items-center gap-2">
        <span class="text-[10px] text-gray-400 w-16 shrink-0">{{ DIMENSION_LABELS[i] || `d${i + 1}` }}</span>
        <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
          <div class="h-full rounded-full transition-all"
            :class="d >= 7.5 ? 'bg-red-500' : d >= 5.5 ? 'bg-amber-500' : d >= 3.5 ? 'bg-blue-400' : 'bg-emerald-400'"
            :style="{ width: `${Math.min(100, (Number(d) / 10) * 100)}%` }"
          ></div>
        </div>
        <span class="text-[10px] font-mono text-gray-500 w-7 text-right shrink-0 tabular-nums">{{ Number(d).toFixed(1) }}</span>
      </div>
    </div>

    <!-- 元信息 -->
    <div class="flex items-center gap-3 flex-wrap text-[10px] text-gray-400">
      <span v-if="hop.deviation_type && hop.deviation_type !== 'none'"
        class="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 border border-gray-200"
      >{{ hop.deviation_type }}</span>
      <span>breadth: <span class="font-mono text-gray-500">{{ hop.breadth }}</span></span>
      <span>trace: <span class="font-mono text-gray-500">{{ hop.trace_id }}</span></span>
      <span class="ml-auto">{{ formatTime(hop.timestamp) }}</span>
    </div>

    <!-- 证据引用 -->
    <div v-if="hop.evidence_refs?.length" class="mt-2 pt-2 border-t border-gray-100 space-y-1">
      <div v-for="(e, i) in hop.evidence_refs" :key="i" class="text-[11px] text-gray-500 flex items-start gap-1.5">
        <span class="text-gray-400 shrink-0">·</span>
        <span>{{ e.description }}</span>
        <span v-if="e.trace_ids?.length" class="text-[10px] text-gray-400 font-mono shrink-0 ml-auto">trace {{ e.trace_ids.join(',') }}</span>
      </div>
    </div>
  </div>
</template>
