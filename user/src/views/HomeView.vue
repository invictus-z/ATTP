<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useChat } from '../composables/useChat'
import { useAttpProtocol, getSessionProtocolUrl, bindSessionProtocolUrl } from '../composables/useAttpProtocol'
import { getActiveAgent } from '../agent_manager'
import { Bot, Activity, Loader2, Plus, MessageSquare, Paperclip, ArrowUp, Shield, Lock, X, AlertCircle } from 'lucide-vue-next'

const {
  currentSession, chatInput, sendMessage, renderMessageHtml,
  formatTime, getDateKey, formatDateLabel, agentStatus,
  createSession, initAgentContext, needsProtocolBinding,
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

const protocolNodes = computed(() => attpUserConfig.protocolNodes || [])

/** 响应式触发器：每次绑定后递增，让 boundProtocolUrl computed 重新计算 */
const protocolBindTrigger = ref(0)

/** 当前 session 绑定的溯源节点 URL（只读） */
const boundProtocolUrl = computed(() => {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const _trigger = protocolBindTrigger.value // 依赖触发器以实现响应式
  if (!currentSession.value) return null
  return getSessionProtocolUrl(currentSession.value.id)
})

/** 当前 session 绑定的溯源节点名称 */
const boundProtocolName = computed(() => {
  if (!boundProtocolUrl.value) return null
  const node = protocolNodes.value.find(n => n.url === boundProtocolUrl.value)
  return node?.name || boundProtocolUrl.value.replace(/^https?:\/\//, '')
})

// ---- 溯源节点选择弹窗 ----

const showNodeSelectModal = ref(false)
const selectedNodeUrl = ref<string | null>(null)
/** 标记是否为"新建会话"模式（选择后创建新 session），还是"补选"模式（绑定到当前 session） */
const isCreateMode = ref(false)

/** 打开新会话的溯源节点选择弹窗 */
const handleNewChat = () => {
  if (protocolNodes.value.length === 0) return
  if (protocolNodes.value.length === 1) {
    // 只有一个节点，直接使用
    createSession('New Chat', protocolNodes.value[0].url)
    scrollToBottom()
    return
  }
  isCreateMode.value = true
  selectedNodeUrl.value = null
  showNodeSelectModal.value = true
}

/** 确认选择溯源节点 */
const confirmNodeSelection = () => {
  if (!selectedNodeUrl.value) return

  if (isCreateMode.value || !currentSession.value) {
    // 新建会话模式 或 无当前 session：创建新 session 并绑定
    createSession('New Chat', selectedNodeUrl.value)
  } else {
    // 补选模式：绑定到当前已有 session
    bindSessionProtocolUrl(currentSession.value.id, selectedNodeUrl.value)
    needsProtocolBinding.value = false
  }

  // 触发响应式更新
  protocolBindTrigger.value++
  showNodeSelectModal.value = false
  selectedNodeUrl.value = null
  scrollToBottom()
}

// Watch needsProtocolBinding: 当需要绑定时自动弹出选择弹窗
watch(needsProtocolBinding, (val) => {
  if (val && protocolNodes.value.length > 0) {
    isCreateMode.value = false
    selectedNodeUrl.value = null
    nextTick(() => {
      showNodeSelectModal.value = true
    })
  }
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
          <button @click="handleNewChat" :disabled="protocolNodes.length === 0" class="p-2 bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors border border-gray-200 shadow-sm flex items-center gap-2 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed" :title="protocolNodes.length === 0 ? '请先在 User Config 中添加溯源节点' : 'New Chat'">
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
              <p class="text-xs text-gray-300 mt-1">点击 New Chat 选择溯源节点后开始</p>
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
          <!-- Trace Node Binding Display -->
          <div class="max-w-4xl mx-auto mb-2.5">
            <!-- 已绑定：只读显示 -->
            <div v-if="boundProtocolUrl" class="flex items-center gap-2">
              <div class="flex items-center gap-1.5 text-gray-400">
                <Shield class="w-3.5 h-3.5" />
                <span class="text-[11px] font-medium">溯源节点</span>
              </div>
              <div class="flex items-center gap-1.5 text-[12px] text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-lg px-2.5 py-1.5 max-w-[320px] truncate">
                <Lock class="w-3 h-3 shrink-0" />
                <span class="truncate">{{ boundProtocolName }}</span>
              </div>
              <span class="text-[10px] text-gray-300">会话期间锁定</span>
            </div>
            <!-- 未绑定：提示选择 -->
            <div v-else-if="protocolNodes.length > 0" class="flex items-center gap-2">
              <div class="flex items-center gap-1.5 text-amber-500">
                <AlertCircle class="w-3.5 h-3.5" />
                <span class="text-[11px] font-medium">请先选择溯源节点</span>
              </div>
              <button @click="showNodeSelectModal = true; isCreateMode = false; selectedNodeUrl = null" class="text-[11px] font-medium text-indigo-600 hover:text-indigo-700 underline underline-offset-2">选择节点</button>
            </div>
            <!-- 无可用节点 -->
            <div v-else class="flex items-center gap-1.5 text-gray-300">
              <Shield class="w-3.5 h-3.5" />
              <span class="text-[11px]">未配置溯源节点 — 请在 User Config 中添加 Protocol Node</span>
            </div>
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
              :placeholder="boundProtocolUrl ? 'Command Local Agent...' : '请先选择溯源节点...'"
              :disabled="!boundProtocolUrl"
            ></textarea>
            <button @click="handleSend" :disabled="!boundProtocolUrl" class="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-colors shadow-sm shrink-0 disabled:opacity-40 disabled:cursor-not-allowed">
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

    <!-- ── Protocol Node Selection Modal ── -->
    <div v-if="showNodeSelectModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showNodeSelectModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[460px] p-6">
        <div class="flex items-center justify-between mb-5">
          <div>
            <h3 class="text-sm font-semibold text-gray-800">
              {{ isCreateMode ? '选择溯源节点以开始新会话' : '为当前会话绑定溯源节点' }}
            </h3>
            <p class="text-[11px] text-gray-400 mt-1">选择后不可更改，该节点将全程记录此会话的行为溯源</p>
          </div>
          <button @click="showNodeSelectModal = false" class="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="space-y-2 max-h-[300px] overflow-y-auto">
          <button
            v-for="node in protocolNodes"
            :key="node.url"
            @click="selectedNodeUrl = node.url"
            :class="[
              'w-full flex items-center gap-3 p-3.5 rounded-xl border transition-all text-left',
              selectedNodeUrl === node.url
                ? 'border-indigo-300 bg-indigo-50 ring-1 ring-indigo-200'
                : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
            ]"
          >
            <div class="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
              :class="selectedNodeUrl === node.url ? 'bg-indigo-100 border border-indigo-200' : 'bg-gray-100 border border-gray-200'">
              <Shield class="w-4 h-4" :class="selectedNodeUrl === node.url ? 'text-indigo-600' : 'text-gray-500'" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-[13px] font-medium truncate" :class="selectedNodeUrl === node.url ? 'text-indigo-800' : 'text-gray-800'">
                {{ node.name }}
              </div>
              <div class="text-[11px] font-mono truncate" :class="selectedNodeUrl === node.url ? 'text-indigo-500' : 'text-gray-400'">
                {{ node.url }}
              </div>
            </div>
            <div v-if="selectedNodeUrl === node.url" class="w-5 h-5 rounded-full bg-indigo-500 flex items-center justify-center shrink-0">
              <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
          </button>
        </div>

        <div v-if="protocolNodes.length === 0" class="text-center py-8 text-gray-400 text-sm">
          暂无溯源节点，请先在 User Config 中添加
        </div>

        <div class="flex justify-end gap-2 mt-5 pt-4 border-t border-gray-100">
          <button @click="showNodeSelectModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button
            @click="confirmNodeSelection"
            :disabled="!selectedNodeUrl"
            class="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {{ isCreateMode ? '创建会话' : '确认绑定' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>