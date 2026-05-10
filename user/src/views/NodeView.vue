<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNodes } from '../composables/useNodes'
import { useChat } from '../composables/useChat'
import { Network, Link2, GitMerge, Paperclip, ArrowUp } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const { agentNodes, fetchNodes, getNodeIcon } = useNodes()
const { currentSession, renderNodeMessageHtml } = useChat()

const nodeInput = ref('')
const nodeMessagesContainer = ref<HTMLElement>()

const nodeIndex = computed(() => {
  const idx = route.params.index
  return idx ? parseInt(idx as string) : 0
})

const currentNode = computed(() => agentNodes.value[nodeIndex.value] || null)

const nodeMessages = computed(() => {
  if (!currentNode.value || !currentSession.value) return []
  const histories = currentSession.value.nodeHistories
  if (!histories || !histories[currentNode.value.did]) return []
  return histories[currentNode.value.did]
})

const scrollToBottom = () => {
  nextTick(() => {
    if (nodeMessagesContainer.value) {
      nodeMessagesContainer.value.scrollTop = nodeMessagesContainer.value.scrollHeight
    }
  })
}

const handleNodeSend = () => {
  const text = nodeInput.value.trim()
  if (!text || !currentNode.value) return
  // Dispatch to useChat's node messaging via WebSocket
  window.dispatchEvent(new CustomEvent('send-node-message', {
    detail: { text, targetDid: currentNode.value.did }
  }))
  nodeInput.value = ''
  scrollToBottom()
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleNodeSend()
  }
}

const handleViewTrace = () => {
  if (currentNode.value) {
    window.dispatchEvent(new CustomEvent('show-flow-diagram'))
  }
}

const autoResize = (e: Event) => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 128) + 'px'
}

watch(() => route.params.index, () => { scrollToBottom() })
watch(() => nodeMessages.value.length, () => { scrollToBottom() })

onMounted(() => {
  fetchNodes()
  scrollToBottom()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Node Header -->
    <header v-if="currentNode" class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-center gap-5 mb-4">
          <!-- Avatar -->
          <div class="w-14 h-14 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center shadow-sm">
            <component :is="getNodeIcon(currentNode.capabilities)" class="w-7 h-7 text-emerald-600" />
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2.5 mb-1">
              <h2 class="text-xl font-semibold text-gray-900 tracking-tight">{{ currentNode.name }}</h2>
              <!-- Status Badge -->
              <span v-if="currentNode.online" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 flex items-center gap-1.5">
                <span class="w-1 h-1 rounded-full bg-emerald-500"></span> Online
              </span>
              <span v-else class="px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100 flex items-center gap-1.5">
                <span class="w-1 h-1 rounded-full bg-amber-500"></span> Offline
              </span>
            </div>
            <p class="text-sm text-gray-500">{{ currentNode.description || 'ATTP Network Node' }}</p>
          </div>
        </div>

        <!-- Params -->
        <div class="flex flex-wrap items-center gap-4 text-sm">
          <div class="flex items-center gap-1.5 text-[12px] text-gray-500 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100">
            <span class="text-gray-400 font-medium">DID:</span>
            <span class="font-mono text-gray-600 truncate max-w-[200px]" :title="currentNode.did">{{ currentNode.did }}</span>
          </div>
          <div class="flex items-center gap-1.5 text-[12px] text-gray-500 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100">
            <Link2 class="w-3 h-3 text-gray-400" />
            <span class="font-mono text-gray-600 truncate max-w-[200px]" :title="currentNode.ad_url">{{ currentNode.ad_url }}</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span v-for="cap in currentNode.capabilities" :key="cap" class="text-[11px] px-2 py-0.5 rounded-md bg-gray-50 text-gray-500 border border-gray-100 font-mono">
              {{ cap }}
            </span>
          </div>
        </div>
      </div>
    </header>

    <!-- No Node Selected -->
    <div v-if="!currentNode" class="flex-1 flex flex-col items-center justify-center text-gray-400">
      <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
        <Network class="w-8 h-8 text-gray-300" />
      </div>
      <p class="text-sm">请从侧边栏选择一个节点</p>
      <p class="text-xs text-gray-300 mt-1">点击侧边栏 Nodes 下的节点查看详情</p>
    </div>

    <!-- Node Chat Area -->
    <template v-if="currentNode">
      <!-- Messages -->
      <div ref="nodeMessagesContainer" class="flex-1 overflow-y-auto p-8 relative">
        <div class="max-w-4xl mx-auto space-y-6 pb-4">
          <!-- Empty State -->
          <div v-if="nodeMessages.length === 0" class="flex flex-col items-center justify-center h-full text-gray-400 py-20">
            <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
              <Network class="w-8 h-8 text-gray-300" />
            </div>
            <p class="text-sm">发送消息与 {{ currentNode.name }} 交互</p>
            <p class="text-xs text-gray-300 mt-1">消息将通过 ATTP 协议路由</p>
          </div>
          <!-- Node Messages -->
          <div v-for="(msg, idx) in nodeMessages" :key="idx" v-html="renderNodeMessageHtml(msg.role, msg.text, msg.timeStr)"></div>
        </div>
      </div>

      <!-- View Trace Logs Button + Input -->
      <div class="shrink-0 border-t border-gray-100 bg-white">
        <!-- Trace Button -->
        <div class="max-w-4xl mx-auto px-8 pt-3">
          <button @click="handleViewTrace" class="text-[12px] text-gray-400 hover:text-gray-600 flex items-center gap-1.5 transition-colors">
            <GitMerge class="w-3.5 h-3.5" />
            View Trace Logs
          </button>
        </div>
        <!-- Input -->
        <div class="p-5">
          <div class="max-w-4xl mx-auto relative flex items-end bg-white border border-gray-200 focus-within:border-gray-300 focus-within:shadow-[0_0_0_4px_rgba(0,0,0,0.02)] rounded-2xl p-2 transition-all duration-200">
            <button class="p-2.5 text-gray-400 hover:text-gray-600 rounded-xl hover:bg-gray-50 transition-colors shrink-0">
              <Paperclip class="w-5 h-5" />
            </button>
            <textarea
              v-model="nodeInput"
              @keydown="handleKeydown"
              @input="autoResize"
              rows="1"
              class="w-full bg-transparent border-none focus:ring-0 text-[14px] text-gray-800 placeholder-gray-400 resize-none py-3 px-2 mx-1 max-h-32"
              style="outline: none;"
              :placeholder="`Message ${currentNode.name}...`"
            ></textarea>
            <button @click="handleNodeSend" class="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-colors shadow-sm shrink-0">
              <ArrowUp class="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>