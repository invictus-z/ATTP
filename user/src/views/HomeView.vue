<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useChat } from '../composables/useChat'
import { useAttpProtocol, getSessionProtocolUrl, bindSessionProtocolUrl } from '../composables/useAttpProtocol'
import { getActiveAgent } from '../agent_manager'
import { Bot, Activity, Loader2, Plus, MessageSquare, Paperclip, ArrowUp, Shield } from 'lucide-vue-next'

const {
  currentSession, chatInput, sendMessage, renderMessageHtml,
  formatTime, getDateKey, formatDateLabel, agentStatus,
  createSession, initAgentContext,
} = useChat()

const { userConfig: attpUserConfig } = useAttpProtocol()

const chatContainer = ref<HTMLElement>()
const inputRef = ref<HTMLTextAreaElement>()

const activeAgent = computed(() => getActiveAgent())

const agentStatusClass = computed(() => {
  switch (agentStatus.value) {
    case 'active': return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 flex items-center gap-1.5'
    case 'offline': return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100 flex items-center gap-1.5'
    default: return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-1.5'
  }
})

const groupedMessages = computed(() => {
  if (!currentSession.value) return []
  const groups: { dateKey: string; dateLabel: string; messages: any[] }[] = []
  let currentGroup: any = null
  for (const msg of currentSession.value.messages) {
    const ts = msg.timestamp || new Date().toISOString()
    const dateKey = getDateKey(ts)
    if (!currentGroup || currentGroup.dateKey !== dateKey) {
      currentGroup = { dateKey, dateLabel: formatDateLabel(ts), messages: [] }
      groups.push(currentGroup)
    }
    currentGroup.messages.push({ ...msg, timestamp: ts })
  }
  return groups
})

const rtLogs = computed(() => currentSession.value?.rtLogs || [])

const scrollToBottom = () => {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

const handleSend = () => {
  sendMessage()
  scrollToBottom()
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

const handleNewChat = () => {
  createSession('New Chat')
  scrollToBottom()
}

const protocolNodes = computed(() => attpUserConfig.protocolNodes || [])

const selectedProtocolUrl = computed({
  get: () => {
    if (!currentSession.value) return null
    return getSessionProtocolUrl(currentSession.value.id)
  },
  set: (url: string | null) => {
    if (!currentSession.value || !url) return
    bindSessionProtocolUrl(currentSession.value.id, url)
  },
})

const autoResize = (e: Event) => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 128) + 'px'
}

watch(() => currentSession.value?.messages?.length, () => { scrollToBottom() })
watch(() => currentSession.value?.rtLogs?.length, () => {
  nextTick(() => {
    const rtContainer = document.getElementById('rt-log-container')
    if (rtContainer) rtContainer.scrollTop = rtContainer.scrollHeight
  })
})
onMounted(() => { scrollToBottom() })
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Header Profile -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-start justify-between">
          <div class="flex items-center gap-4">
            <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-gray-50 to-gray-100 border border-gray-200 flex items-center justify-center shadow-sm">
              <Bot class="w-6 h-6 text-gray-600" />
            </div>
            <div>
              <div class="flex items-center gap-2.5 mb-1">
                <h2 class="text-xl font-semibold text-gray-900 tracking-tight">{{ activeAgent?.name || 'Local Manager Agent' }}</h2>
                <span :class="agentStatusClass">
                  <template v-if="agentStatus === 'active'">
                    <Activity class="w-3 h-3" /> Active
                  </template>
                  <template v-else-if="agentStatus === 'offline'">
                    <Activity class="w-3 h-3" /> Offline
                  </template>
                  <template v-else>
                    <Loader2 class="w-3 h-3 animate-spin" /> Connecting...
                  </template>
                </span>
              </div>
              <p class="text-sm text-gray-500">{{ activeAgent?.baseUrl ? `Agent backend at ${activeAgent.baseUrl}` : '你本机的主控 Agent，负责调度全网节点、分配任务及执行本地脚本。' }}</p>
            </div>
          </div>

          <!-- New Chat Button -->
          <button @click="handleNewChat" class="p-2 bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors border border-gray-200 shadow-sm flex items-center gap-2 text-sm font-medium">
            <Plus class="w-4 h-4" />
            New Chat
          </button>
        </div>
      </div>
    </header>

    <!-- Main Content: Chat + Right Panel -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Chat Area -->
      <div class="flex-1 flex flex-col relative">
        <!-- Chat Messages -->
        <div ref="chatContainer" class="flex-1 overflow-y-auto p-8 relative">
          <div class="max-w-4xl mx-auto space-y-8 pb-4">
            <!-- Empty State -->
            <div v-if="!currentSession || currentSession.messages.length === 0" class="flex flex-col items-center justify-center h-full text-gray-400 py-20">
              <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
              <MessageSquare class="w-8 h-8 text-gray-300" />
              </div>
              <p class="text-sm">开始新的对话</p>
              <p class="text-xs text-gray-300 mt-1">输入消息并发送</p>
            </div>

            <!-- Message Groups -->
            <template v-for="group in groupedMessages" :key="group.dateKey">
              <!-- Date Separator -->
              <div class="flex items-center justify-center my-4">
                <span class="px-3 py-1 bg-white border border-gray-100 rounded-full text-[11px] font-medium text-gray-400 shadow-sm">{{ group.dateLabel }}</span>
              </div>
              <!-- Messages -->
              <div v-for="(msg, idx) in group.messages" :key="idx" v-html="renderMessageHtml(msg)"></div>
            </template>
          </div>
        </div>

        <!-- Input Area -->
        <div class="p-5 bg-surface border-t border-gray-100 shrink-0">
          <!-- Trace Node Selector -->
          <div v-if="protocolNodes.length > 0" class="max-w-4xl mx-auto mb-2.5 flex items-center gap-2">
            <div class="flex items-center gap-1.5 text-gray-400">
              <Shield class="w-3.5 h-3.5" />
              <span class="text-[11px] font-medium">溯源节点</span>
            </div>
            <select
              v-model="selectedProtocolUrl"
              class="flex-1 text-[12px] text-gray-600 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors appearance-none cursor-pointer max-w-[320px]"
            >
              <option v-for="node in protocolNodes" :key="node.url" :value="node.url">
                {{ node.name }} ({{ node.url.replace(/^https?:\/\//, '') }})
              </option>
            </select>
            <div v-if="selectedProtocolUrl" class="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" title="已绑定溯源节点"></div>
          </div>
          <div v-else class="max-w-4xl mx-auto mb-2.5">
            <span class="text-[11px] text-gray-300 flex items-center gap-1.5">
              <Shield class="w-3.5 h-3.5" />
              未配置溯源节点 — 请在 Settings 中添加 Protocol Node
            </span>
          </div>

          <div class="max-w-4xl mx-auto relative flex items-end bg-white border border-gray-200 focus-within:border-gray-300 focus-within:shadow-[0_0_0_4px_rgba(0,0,0,0.02)] rounded-2xl p-2 transition-all duration-200">
            <button class="p-2.5 text-gray-400 hover:text-gray-600 rounded-xl hover:bg-gray-50 transition-colors shrink-0">
              <Paperclip class="w-5 h-5" />
            </button>
            <textarea
              ref="inputRef"
              v-model="chatInput"
              @keydown="handleKeydown"
              @input="autoResize"
              rows="1"
              class="w-full bg-transparent border-none focus:ring-0 text-[14px] text-gray-800 placeholder-gray-400 resize-none py-3 px-2 mx-1 max-h-32"
              style="outline: none;"
              placeholder="Command Local Agent..."
            ></textarea>
            <button @click="handleSend" class="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-colors shadow-sm shrink-0">
              <ArrowUp class="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      <!-- Right Panel: Real-time Network -->
      <div class="w-80 border-l border-gray-100 bg-gray-50 flex-col h-full hidden lg:flex">
        <div class="p-6 border-b border-gray-100 bg-white">
          <h3 class="text-sm font-semibold text-gray-900">Real-time Network</h3>
        </div>
        <div class="flex-1 overflow-y-auto p-6 space-y-4">
          <div class="bg-white p-4 rounded-xl border border-gray-100">
            <div class="text-[11px] font-medium text-gray-400 uppercase mb-3">Logs</div>
            <div id="rt-log-container" class="space-y-3">
              <div v-if="rtLogs.length === 0" class="text-xs text-gray-300 text-center py-4">暂无日志</div>
              <div v-for="(log, idx) in rtLogs" :key="idx" class="text-xs text-gray-600 mb-1">
                <span class="font-semibold text-gray-700">[{{ log.senderName }}]</span> {{ log.text }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>