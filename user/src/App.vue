<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChat } from './composables/useChat'
import { useNodes } from './composables/useNodes'
import { useAttpProtocol } from './composables/useAttpProtocol'
import { getActiveAgent, getAgents, getActiveAgentId, setActiveAgent, onAgentSwitch, removeAgent, addAgent, loadAgents, renameAgent } from './agent_manager'
import { Bot, Server, X, MessageSquare, ChevronDown, History, Settings, Pencil, Shield, Wrench, User, Users, Search, AlertTriangle } from 'lucide-vue-next'

const route = useRoute()
const router = useRouter()
const {
  sessions, currentSessionId, agentStatus, totalUnread,
  initAgentContext, loadSession, createSession, connectAllAgents, connectWebSocket,
} = useChat()

const showAddAgentModal = ref(false)
const newAgentName = ref('')
const newAgentDid = ref('')
const newAgentUrl = ref('http://localhost:8001')
const nodesCollapsed = ref(false)
const traceCollapsed = ref(false)
const agentsCollapsed = ref(false)

// Agent context menu state
const contextMenu = ref({ visible: false, x: 0, y: 0, agentId: '', agentName: '', agentUrl: '' })
const showEditAgentModal = ref(false)
const editAgentName = ref('')
const editAgentUrl = ref('')

const onAgentContextMenu = (event: MouseEvent, agent: any) => {
  event.preventDefault()
  event.stopPropagation()
  contextMenu.value = {
    visible: true,
    x: event.clientX,
    y: event.clientY,
    agentId: agent.id,
    agentName: agent.name,
    agentUrl: agent.baseUrl,
  }
}

const closeContextMenu = () => { contextMenu.value.visible = false }

const openEditAgent = () => {
  editAgentName.value = contextMenu.value.agentName
  editAgentUrl.value = contextMenu.value.agentUrl
  showEditAgentModal.value = true
  closeContextMenu()
}

const saveEditAgent = () => {
  if (editAgentName.value.trim() && editAgentUrl.value.trim()) {
    renameAgent(contextMenu.value.agentId, editAgentName.value.trim())
    // Note: baseUrl change would require reconnecting, just save name for now
    showEditAgentModal.value = false
  }
}

const removeAgentFromMenu = () => {
  removeAgent(contextMenu.value.agentId)
  closeContextMenu()
}

// Close context menu on click elsewhere
if (typeof window !== 'undefined') {
  window.addEventListener('click', closeContextMenu)
  window.addEventListener('contextmenu', (e) => {
    // Only close if not right-clicking on an agent item
    const target = e.target as HTMLElement
    if (!target.closest('[data-agent-item]')) closeContextMenu()
  })
}

const { agentNodes, fetchNodes, getNodeIcon } = useNodes()
const { loadUserConfig } = useAttpProtocol()

const activeAgent = computed(() => getActiveAgent())
const agentList = computed(() => getAgents())
const hasActiveAgent = computed(() => !!getActiveAgent())

const activeNav = computed(() => {
  if (route.path.startsWith('/node')) return 'node'
  if (route.path.startsWith('/sessions')) return 'sessions'
  if (route.path.startsWith('/settings')) return 'settings'
  if (route.path.startsWith('/trace/nodes')) return 'trace-nodes'
  if (route.path.startsWith('/trace/query')) return 'trace-query'
  if (route.path.startsWith('/trace/malicious')) return 'trace-malicious'
  if (route.path.startsWith('/trace')) return 'trace-query'
  if (route.path.startsWith('/tools')) return 'tools'
  if (route.path.startsWith('/user-config')) return 'user-config'
  return 'home'
})

const switchToAgent = (agentId: string) => {
  setActiveAgent(agentId)
  router.push('/home')
}

const removeAgentAction = (event: Event, agentId: string) => {
  event.stopPropagation()
  removeAgent(agentId)
}

const addNewAgent = () => {
  if (newAgentName.value.trim() && newAgentUrl.value.trim()) {
    addAgent(newAgentName.value.trim(), newAgentUrl.value.trim(), newAgentDid.value.trim() || undefined)
    newAgentName.value = ''
    newAgentDid.value = ''
    newAgentUrl.value = 'http://localhost:18080'
    showAddAgentModal.value = false
    // Connect WS for the new agent
    connectWebSocket()
  }
}

const navigate = (path: string) => { router.push(path) }

const navigateToNode = (index: number) => {
  router.push(`/node/${index}`)
}

const toggleNodesCollapsed = () => {
  nodesCollapsed.value = !nodesCollapsed.value
}

onMounted(async () => {
  // 1. Load user config first (agents + trace nodes live there now)
  await loadUserConfig()
  // 2. Load agents from config
  await loadAgents()
  // 3. Init chat context and connect
  initAgentContext()
  connectAllAgents()
  fetchNodes()
})

onAgentSwitch(() => {
  fetchNodes()
})

</script>

<template>
  <div class="flex h-screen w-full overflow-hidden bg-white">
    <!-- Left Sidebar - 260px -->
    <aside class="w-[260px] bg-white border-r border-gray-100 flex flex-col shrink-0">
      <!-- Header -->
      <div class="h-16 flex items-center px-5 mb-2">
        <div class="w-7 h-7 rounded-lg bg-gray-100 border border-gray-200 flex items-center justify-center mr-3">
          <Bot class="w-4 h-4 text-gray-600" />
        </div>
        <div class="flex flex-col">
          <span class="text-sm font-semibold text-gray-800">ATTP</span>
          <span class="text-[11px] text-gray-400">Multi-Agent Workspace</span>
        </div>
      </div>

      <!-- Unified Nav -->
      <nav class="flex-1 overflow-y-auto px-3 pt-3 pb-2">
        <!-- 溯源 & 工具 -->
        <div class="space-y-0.5 mb-3">
          <!-- 溯源模块 可折叠组头 -->
          <button
            @click="traceCollapsed = !traceCollapsed"
            class="w-full px-2.5 py-1.5 flex items-center gap-2 hover:bg-gray-50 rounded-lg transition-colors"
          >
            <ChevronDown :class="['w-3.5 h-3.5 text-gray-500 transition-transform duration-200', traceCollapsed ? '-rotate-90' : '']" />
            <Shield class="w-4 h-4 text-gray-500" />
            <span class="text-[13px] font-semibold text-gray-700">溯源模块</span>
          </button>
          <div v-show="!traceCollapsed" class="ml-4 mr-1 border-l border-gray-100 pl-2 space-y-0.5 mt-1">
            <button
              @click="navigate('/trace/nodes')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'trace-nodes' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
              title="溯源节点管理（协议节点）"
            >
              <Server class="w-4 h-4 mr-2.5 opacity-70" />
              <span>节点管理</span>
            </button>
            <button
              @click="navigate('/trace/query')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'trace-query' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
              title="溯源查询（行为溯源 + 纵/横向分析）"
            >
              <Search class="w-4 h-4 mr-2.5 opacity-70" />
              <span>溯源查询</span>
            </button>
            <button
              @click="navigate('/trace/malicious')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'trace-malicious' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
              title="恶意报告（节点档案 + 违规明细）"
            >
              <AlertTriangle class="w-4 h-4 mr-2.5 opacity-70" />
              <span>恶意报告</span>
            </button>
          </div>
          <div class="h-px bg-gray-100 my-2"></div>
          <button
            @click="navigate('/tools')"
            :class="[
              'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
              activeNav === 'tools' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
            ]"
            title="工具管理（工具节点）"
          >
            <Wrench class="w-4 h-4 mr-2.5 opacity-70" />
            <span>工具管理</span>
          </button>
        </div>

        <div class="h-px bg-gray-100 mx-2 mb-4"></div>

        <!-- 智能体 -->
        <div class="mb-4">
          <div
            class="px-2.5 py-1.5 flex items-center gap-2 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer select-none"
            @click="agentsCollapsed = !agentsCollapsed"
          >
            <ChevronDown :class="['w-3.5 h-3.5 text-gray-500 transition-transform duration-200', agentsCollapsed ? '-rotate-90' : '']" />
            <Users class="w-4 h-4 text-gray-500" />
            <span class="text-[13px] font-semibold text-gray-700 flex-1">智能体</span>
            <button @click.stop="showAddAgentModal = true" class="p-0.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors cursor-pointer" title="添加智能体">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="pointer-events:none;display:block"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            </button>
          </div>
          <div v-show="!agentsCollapsed" class="ml-4 mr-1 border-l border-gray-100 pl-2 space-y-0.5 mt-1">
            <div v-for="agent in agentList" :key="agent.id" class="group relative flex items-center" :data-agent-item="agent.id">
              <button
                @click="switchToAgent(agent.id)"
                @contextmenu="onAgentContextMenu($event, agent)"
                :class="[
                  'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors pr-8',
                  agent.id === getActiveAgentId() ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
                ]"
                :title="agent.baseUrl"
              >
                <Server class="w-4 h-4 mr-2 shrink-0" :class="agent.id === getActiveAgentId() ? 'opacity-90' : 'opacity-70'" />
                <span class="w-2 h-2 rounded-full shrink-0 mr-2" :class="agent.status === 'active' ? 'bg-emerald-400' : (agent.status === 'connecting' ? 'bg-blue-400' : 'bg-gray-300')"></span>
                <span class="flex-1 text-left truncate">{{ agent.name }}</span>
              </button>
              <button
                @click="removeAgentAction($event, agent.id)"
                class="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition-all"
                title="移除智能体"
              >
                <X class="w-3 h-3" />
              </button>
            </div>
            <div v-if="agentList.length === 0" class="px-2 py-4 text-center">
              <p class="text-[11px] text-gray-400 mb-2">暂无智能体</p>
              <button @click="showAddAgentModal = true" class="text-[11px] text-indigo-500 hover:text-indigo-700 flex items-center gap-1 mx-auto transition-colors cursor-pointer">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="pointer-events:none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg> 添加第一个智能体
              </button>
            </div>
          </div>
        </div>

        <!-- 当前智能体工作区：对话/配置/会话历史/节点 均从属于当前智能体 -->
        <div v-if="hasActiveAgent" class="mt-3">
          <!-- 当前智能体 醒目头部 -->
          <div class="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-gray-50 border border-gray-100 mb-1">
            <span class="w-2 h-2 rounded-full shrink-0" :class="activeAgent?.status === 'active' ? 'bg-emerald-400' : (activeAgent?.status === 'connecting' ? 'bg-blue-400' : 'bg-gray-300')"></span>
            <span class="text-[13px] font-semibold text-gray-800 truncate flex-1">{{ activeAgent?.name || '智能体' }}</span>
            <span class="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-brand-50 text-brand-600 border border-brand-100">当前</span>
          </div>
          <!-- 从属于当前智能体的视图（左边框缩进体现从属） -->
          <div class="ml-4 mr-1 border-l border-gray-100 pl-2 space-y-0.5">
            <button
              @click="navigate('/home')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'home' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
            >
              <MessageSquare class="w-4 h-4 mr-2.5 opacity-70" />
              <span>对话</span>
            </button>
            <button
              @click="navigate('/settings')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'settings' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
            >
              <Settings class="w-4 h-4 mr-2.5 opacity-70" />
              <span>配置</span>
            </button>
            <button
              @click="navigate('/sessions')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'sessions' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
            >
              <History class="w-4 h-4 mr-2.5 opacity-70" />
              <span>会话历史</span>
            </button>

            <!-- 节点 子组（从属于当前智能体） -->
            <div>
              <div class="px-2 py-1.5 flex items-center justify-between cursor-pointer select-none rounded-lg hover:bg-gray-50 transition-colors" @click="toggleNodesCollapsed()">
                <span class="flex items-center gap-1.5 text-[12px] font-medium text-gray-500">
                  <ChevronDown :class="['w-3 h-3 transition-transform duration-200', nodesCollapsed ? '-rotate-90' : '']" />
                  节点
                </span>
                <span class="text-[10px] text-gray-300">{{ agentNodes.length }}</span>
              </div>
              <div v-show="!nodesCollapsed" class="ml-3 border-l border-gray-100 pl-2 space-y-0.5 mt-0.5">
                <button
                  v-for="(node, index) in agentNodes"
                  :key="node.did"
                  @click="navigateToNode(index)"
                  :class="[
                    'nav-btn w-full flex items-center px-2.5 py-1.5 text-[12px] rounded-lg transition-colors',
                    activeNav === 'node' && route.params.index === String(index) ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
                  ]"
                  :title="node.did"
                >
                  <component :is="getNodeIcon(node.capabilities)" class="w-3.5 h-3.5 mr-2 opacity-70" />
                  <span class="flex-1 text-left truncate">{{ node.name }}</span>
                  <span class="w-1.5 h-1.5 rounded-full shrink-0" :class="node.online ? 'bg-emerald-400' : 'bg-gray-300'"></span>
                </button>
                <div v-if="agentNodes.length === 0" class="px-2 py-2 text-[11px] text-gray-300 text-center">未发现节点</div>
              </div>
            </div>
          </div>
        </div>
      </nav>

      <!-- Bottom: User Config -->
      <div class="px-3 py-3 border-t border-gray-100 space-y-0.5">
        <button
          @click="navigate('/user-config')"
          :class="[
            'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
            activeNav === 'user-config' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
          ]"
          title="用户配置"
        >
          <User class="w-4 h-4 mr-2.5 opacity-70" />
          <span>用户配置</span>
        </button>
      </div>

      <!-- Bottom spacer -->
      <div class="p-3">
        <div class="text-[10px] text-gray-300 text-center">v0.2.0-alpha</div>
      </div>
    </aside>

    <!-- Main Content Area -->
    <div class="flex-1 flex flex-col min-w-0 h-full">
      <router-view />
    </div>

    <!-- Agent Context Menu -->
    <div
      v-if="contextMenu.visible"
      class="fixed bg-white rounded-lg shadow-xl border border-gray-100 py-1 w-44 z-[100]"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
    >
      <button @click="openEditAgent" class="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 transition-colors">
        <Pencil class="w-3.5 h-3.5 opacity-60" />
        <span>编辑智能体</span>
      </button>
      <div class="h-px bg-gray-100 my-1"></div>
      <button @click="removeAgentFromMenu" class="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-red-500 hover:bg-red-50 transition-colors">
        <X class="w-3.5 h-3.5 opacity-70" />
        <span>移除</span>
      </button>
    </div>

    <!-- Edit Agent Modal -->
    <div v-if="showEditAgentModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showEditAgentModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[400px] p-6">
        <h3 class="text-sm font-semibold text-gray-800 mb-4">编辑智能体</h3>
        <div class="space-y-3">
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">智能体名称</label>
            <input v-model="editAgentName" placeholder="我的智能体" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-200" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">服务地址</label>
            <input v-model="editAgentUrl" placeholder="http://localhost:18080" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-200 font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showEditAgentModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button @click="saveEditAgent" class="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors">保存</button>
        </div>
      </div>
    </div>

    <!-- Add Agent Modal -->
    <div v-if="showAddAgentModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showAddAgentModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[400px] p-6">
        <h3 class="text-sm font-semibold text-gray-800 mb-4">添加智能体</h3>
        <div class="space-y-3">
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">智能体名称</label>
            <input v-model="newAgentName" placeholder="我的智能体" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-200" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">服务地址</label>
            <input v-model="newAgentUrl" placeholder="http://localhost:18080" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-200 font-mono" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">智能体 DID <span class="text-gray-300 font-normal">（必须）</span></label>
            <input v-model="newAgentDid" placeholder="did:wba:host:agent-name" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-200 font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showAddAgentModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button @click="addNewAgent" class="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 transition-colors">添加</button>
        </div>
      </div>
    </div>

  </div>
</template>
