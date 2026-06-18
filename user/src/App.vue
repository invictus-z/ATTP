<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChat } from './composables/useChat'
import { useNodes } from './composables/useNodes'
import { useAttpProtocol } from './composables/useAttpProtocol'
import { getActiveAgent, getAgents, getActiveAgentId, setActiveAgent, onAgentSwitch, removeAgent, addAgent, loadAgents, renameAgent } from './agent_manager'
import { Bot, Server, X, MessageSquare, ChevronDown, History, Settings, Pencil, Shield, Wrench, User, Search, AlertTriangle, Plus, MoreVertical } from 'lucide-vue-next'

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
const switcherOpen = ref(false)

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
  // Close agent switcher when clicking outside it
  window.addEventListener('click', (e) => {
    const target = e.target as HTMLElement
    if (!target.closest('[data-agent-switcher]')) switcherOpen.value = false
  })
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

// Agent switcher
const toggleSwitcher = () => {
  switcherOpen.value = !switcherOpen.value
}

const switchAgentAndClose = (agentId: string) => {
  switchToAgent(agentId)
  switcherOpen.value = false
}

const openAddAndClose = () => {
  showAddAgentModal.value = true
  switcherOpen.value = false
}

// Edit/remove the *current* agent via the card ⋯ button (reuses context menu)
const openCurrentAgentMenu = (event: MouseEvent) => {
  const a = getActiveAgent()
  if (!a) return
  onAgentContextMenu(event, a)
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
          <span class="text-sm font-semibold text-gray-800">谛听</span>
          <span class="text-[11px] text-gray-400">基于 ATTP 的多智能体工作区</span>
        </div>
      </div>

      <!-- 智能体切换器（浮于下方面板之上、不挤占布局；置于 nav 之外，避免 overflow-y-auto 裁剪浮层） -->
      <div class="px-3 pt-2" data-agent-switcher>
        <!-- 卡片：点开切换/新增；用 div 而非 button（内含 ⋯ 子按钮，HTML 禁止 button 嵌套） -->
        <div
          @click="toggleSwitcher()"
          class="relative w-full rounded-lg border border-gray-200 bg-gray-50/60 px-3 py-2.5 flex items-center gap-2.5 hover:bg-gray-100 transition-colors cursor-pointer select-none"
        >
          <span class="w-2 h-2 rounded-full shrink-0" :class="activeAgent?.status === 'active' ? 'bg-emerald-400' : (activeAgent?.status === 'connecting' ? 'bg-blue-400' : 'bg-gray-300')"></span>
          <span class="flex-1 text-left min-w-0">
            <span class="block text-[13px] font-semibold truncate" :class="hasActiveAgent ? 'text-gray-800' : 'text-gray-300'">{{ activeAgent?.name || '未选择智能体' }}</span>
            <span v-if="hasActiveAgent && activeAgent?.did" class="block text-[10px] text-gray-400 font-mono truncate">{{ activeAgent.did }}</span>
          </span>
          <button
            v-if="hasActiveAgent"
            @click.stop="openCurrentAgentMenu($event)"
            class="p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-200 rounded transition-colors shrink-0"
            title="编辑 / 移除当前智能体"
          >
            <MoreVertical class="w-3.5 h-3.5" />
          </button>
          <ChevronDown class="w-4 h-4 text-gray-400 shrink-0 transition-transform duration-200" :class="switcherOpen ? 'rotate-180' : ''" />
          <!-- 浮层下拉（作为 card 子节点，absolute 锚定 card；@click.stop 防止点击项冒泡触发 card 的 toggle） -->
          <div
            v-if="switcherOpen"
            @click.stop
            class="absolute left-0 right-0 top-full mt-1 bg-white rounded-lg border border-gray-100 py-1 shadow-lg max-h-72 overflow-y-auto z-50"
          >
            <button
              v-for="agent in agentList"
              :key="agent.id"
              @click="switchAgentAndClose(agent.id)"
              @contextmenu="onAgentContextMenu($event, agent)"
              :data-agent-item="agent.id"
              :class="[
                'w-full flex items-center gap-2.5 px-3 py-2 text-[13px] rounded-lg transition-colors',
                agent.id === getActiveAgentId() ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-600 hover:bg-gray-50'
              ]"
            >
              <span class="w-2 h-2 rounded-full shrink-0" :class="agent.status === 'active' ? 'bg-emerald-400' : (agent.status === 'connecting' ? 'bg-blue-400' : 'bg-gray-300')"></span>
              <span class="flex-1 text-left truncate">{{ agent.name }}</span>
            </button>
            <div v-if="agentList.length === 0" class="px-3 py-3 text-[11px] text-gray-400 text-center">暂无智能体</div>
            <div class="h-px bg-gray-100 my-1"></div>
            <button @click="openAddAndClose()" class="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] text-brand-600 hover:bg-brand-50 rounded-lg transition-colors">
              <Plus class="w-3.5 h-3.5" />
              <span>添加智能体</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Unified Nav -->
      <nav class="flex-1 overflow-y-auto px-3 pt-3 pb-2">

        <!-- 当前智能体导航：对话/会话历史/配置/对端节点；无 agent 时灰显禁用（不抖动） -->
        <div
          class="space-y-0.5"
          :class="hasActiveAgent ? '' : 'opacity-50 pointer-events-none'"
          :title="hasActiveAgent ? '' : '请先选择智能体'"
        >
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
            @click="navigate('/sessions')"
            :class="[
              'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
              activeNav === 'sessions' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
            ]"
          >
            <History class="w-4 h-4 mr-2.5 opacity-70" />
            <span>会话历史</span>
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

          <!-- 对端节点 子组（agent 发现的对端服务节点，从属于当前智能体；与溯源“节点管理”=协议节点不同） -->
          <div>
            <div class="px-2 py-1.5 flex items-center justify-between cursor-pointer select-none rounded-lg hover:bg-gray-50 transition-colors" @click="toggleNodesCollapsed()">
              <span class="flex items-center gap-1.5 text-[12px] font-medium text-gray-500">
                <ChevronDown :class="['w-3 h-3 transition-transform duration-200', nodesCollapsed ? '-rotate-90' : '']" />
                对端节点
              </span>
              <span class="text-[10px] text-gray-300">{{ agentNodes.length }}</span>
            </div>
            <div v-show="!nodesCollapsed" class="ml-4 border-l border-gray-100 pl-2 space-y-0.5 mt-0.5">
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
              <div v-if="agentNodes.length === 0" class="px-2 py-2 text-[11px] text-gray-300 text-center">未发现对端节点</div>
            </div>
          </div>
        </div>
      </nav>

      <!-- 底部钉住区：溯源 + 工具管理 + 用户配置 -->
      <div class="px-3 py-3 border-t border-gray-100 space-y-2">
        <!-- 溯源（静态标签 + 铺平子项，无折叠） -->
        <div>
          <div class="px-2.5 pb-1 flex items-center gap-2 text-[11px] font-medium text-gray-400">
            <Shield class="w-3.5 h-3.5" />
            <span>溯源</span>
          </div>
          <div class="ml-4 border-l border-gray-100 pl-2 space-y-0.5">
            <button
              @click="navigate('/trace/nodes')"
              :class="[
                'nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors',
                activeNav === 'trace-nodes' ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800'
              ]"
              title="协议节点 / 溯源后端（与上方对端节点不同）"
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
        </div>
        <!-- 工具管理 -->
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
        <div class="h-px bg-gray-100 mx-2"></div>
        <!-- 用户配置 -->
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
        <div class="text-[10px] text-gray-300 text-center pt-1">v0.2.0-alpha.2</div>
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
