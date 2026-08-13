<script setup lang="ts">
/**
 * NodeSelector — 共享协议节点下拉选择器。
 * 绑定 useProtocolNodes 单例的 selectedNodeId。
 */
import { useProtocolNodes } from '../../../composables/useProtocolNodes'

const { traceNodes, selectedNodeId } = useProtocolNodes()
</script>

<template>
  <div class="flex-1 min-w-[220px]">
    <label class="block text-[11px] font-medium text-gray-400 mb-1.5">协议节点</label>
    <select
      v-model="selectedNodeId"
      class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors appearance-none"
    >
      <option :value="null" disabled>选择协议节点...</option>
      <option v-for="node in traceNodes" :key="node.id" :value="node.id">
        {{ node.name }} ({{ node.status === 'online' ? '●' : '○' }} {{ node.url }})
      </option>
    </select>
  </div>
</template>
