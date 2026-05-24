<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch } from '../transport'
import { useAttpProtocol } from '../composables/useAttpProtocol'
import {
  Shield, Plus, X, Pencil, Trash2, Loader2, Activity, ExternalLink,
  Wrench, ChevronDown, ChevronRight, RefreshCw, Search, Info, Box
} from 'lucide-vue-next'

// ─── Types ───────────────────────────────────────────────────────────

interface ToolNode {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'checking'
}

interface ToolAd {
  type: string
  version: string
  identifier: string
  name: string
  description: string
  attp_endpoint: string
  public_key_endpoint: string
  mcp_tools: { name: string; description?: string }[]
}

// ─── State ───────────────────────────────────────────────────────────

const { userConfig, saveToolNodes: configSaveToolNodes } = useAttpProtocol()

const toolNodes = ref<ToolNode[]>([])
const nodePanelOpen = ref(false)
const showAddModal = ref(false)
const showEditModal = ref(false)
const newNodeName = ref('')
const newNodeUrl = ref('http://localhost:8003/attp')
const editNodeName = ref('')
const editNodeUrl = ref('')
const editingNodeId = ref<string | null>(null)

// 详情查看状态
const selectedNodeId = ref<string | null>(null)
const selectedAd = ref<ToolAd | null>(null)
const adLoading = ref(false)

// ─── Toast ───────────────────────────────────────────────────────────

const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error'>('success')

const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
  toastMessage.value = msg
  toastType.value = type
  toastVisible.value = true
  setTimeout(() => { toastVisible.value = false }, 2500)
}

// ─── Node CRUD ───────────────────────────────────────────────────────

const loadNodes = () => {
  const stored = userConfig.toolNodes || []
  toolNodes.value = stored.map((n, i) => ({
    id: 'tool_' + i + '_' + n.url.replace(/[^a-zA-Z0-9]/g, '_'),
    name: n.name,
    url: n.url,
    status: 'checking' as const,
  }))
}

const saveNodes = async () => {
  await configSaveToolNodes(toolNodes.value.map(({ name, url }) => ({ name, url })))
}

const checkNodeStatus = async (node: ToolNode) => {
  node.status = 'checking'
  try {
    // 工具节点的 health 端点：{prefix}/health
    const healthUrl = `${node.url.replace(/\/+$/, '')}/health`
    const result = await apiFetch(healthUrl)
    node.status = result.ok ? 'online' : 'offline'
  } catch {
    node.status = 'offline'
  }
}

const checkAllNodes = () => {
  toolNodes.value.forEach(node => checkNodeStatus(node))
}

const addNode = async () => {
  const name = newNodeName.value.trim()
  const url = newNodeUrl.value.trim().replace(/\/$/, '')
  if (!name || !url) return
  const id = 'tool_' + Date.now().toString()
  const node: ToolNode = { id, name, url, status: 'checking' }
  toolNodes.value.push(node)
  await saveNodes()
  checkNodeStatus(node)
  newNodeName.value = ''
  newNodeUrl.value = 'http://localhost:8003/attp'
  showAddModal.value = false
  showToast(`工具节点「${name}」已添加`)
}

const openEditModal = (node: ToolNode) => {
  editingNodeId.value = node.id
  editNodeName.value = node.name
  editNodeUrl.value = node.url
  showEditModal.value = true
}

const saveEditNode = async () => {
  const name = editNodeName.value.trim()
  const url = editNodeUrl.value.trim().replace(/\/$/, '')
  if (!name || !url || !editingNodeId.value) return
  const idx = toolNodes.value.findIndex(n => n.id === editingNodeId.value)
  if (idx >= 0) {
    toolNodes.value[idx].name = name
    toolNodes.value[idx].url = url
    toolNodes.value[idx].status = 'checking'
    await saveNodes()
    checkNodeStatus(toolNodes.value[idx])
    showToast(`工具节点「${name}」已更新`)
  }
  showEditModal.value = false
  editingNodeId.value = null
}

const removeNode = async (id: string) => {
  const node = toolNodes.value.find(n => n.id === id)
  toolNodes.value = toolNodes.value.filter(n => n.id !== id)
  await saveNodes()
  if (selectedNodeId.value === id) {
    selectedNodeId.value = null
    selectedAd.value = null
  }
  if (node) showToast(`工具节点「${node.name}」已移除`)
}

const testConnection = async (node: ToolNode) => {
  await checkNodeStatus(node)
  showToast(
    node.status === 'online' ? `「${node.name}」连接成功` : `「${node.name}」连接失败`,
    node.status === 'online' ? 'success' : 'error'
  )
}

// ─── Ad.json 查询 ────────────────────────────────────────────────────

const fetchAd = async (node: ToolNode) => {
  selectedNodeId.value = node.id
  selectedAd.value = null
  adLoading.value = true
  try {
    // 尝试获取 ad.json，路径可能是 /ad.json 或 {attp_prefix}/ad.json
    let adUrl = `${node.url.replace(/\/+$/, '')}/ad.json`
    let result = await apiFetch(adUrl)
    
    // 如果 /ad.json 失败，尝试 /attp/ad.json
    if (!result.ok) {
      adUrl = `${node.url.replace(/\/+$/, '')}/attp/ad.json`
      result = await apiFetch(adUrl)
    }
    
    if (result.ok && result.data) {
      selectedAd.value = result.data as ToolAd
    } else {
      showToast('获取工具描述失败', 'error')
    }
  } catch {
    showToast('请求失败', 'error')
  } finally {
    adLoading.value = false
  }
}

// ─── Helpers ─────────────────────────────────────────────────────────

const formatDid = (did: string) => {
  if (!did) return '--'
  const parts = did.split(':')
  return parts.length > 1 ? parts[parts.length - 1] : did
}

// ─── Lifecycle ───────────────────────────────────────────────────────

onMounted(() => {
  loadNodes()
  checkAllNodes()
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-5xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">工具模块</h2>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200">{{ toolNodes.length }} 节点</span>
        </div>
        <p class="text-sm text-gray-500">工具节点管理 · 探活检测 · 服务描述</p>
      </div>
    </header>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto relative">
      <div class="max-w-5xl mx-auto p-8 space-y-6 pb-8">

        <!-- ── Node Management Panel ── -->
        <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div
            @click="nodePanelOpen = !nodePanelOpen"
            class="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50/50 transition-colors cursor-pointer select-none"
          >
            <div class="flex items-center gap-3">
              <component :is="nodePanelOpen ? ChevronDown : ChevronRight" class="w-4 h-4 text-gray-400" />
              <span class="text-[13px] font-medium text-gray-700">工具节点管理</span>
              <span class="text-[11px] text-gray-400">{{ toolNodes.filter(n => n.status === 'online').length }} / {{ toolNodes.length }} 在线</span>
            </div>
            <button
              @click.stop="showAddModal = true"
              class="px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 hover:border-gray-300 transition-colors flex items-center gap-1"
            >
              <Plus class="w-3.5 h-3.5" /> 添加
            </button>
          </div>

          <div v-if="nodePanelOpen" class="border-t border-gray-100 px-5 py-4 space-y-3">
            <div class="flex items-center justify-between mb-2">
              <button @click="checkAllNodes" class="px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
                <Activity class="w-3.5 h-3.5" /> 检测全部
              </button>
            </div>
            <div v-for="node in toolNodes" :key="node.id"
              class="group flex items-center justify-between p-3 bg-gray-50/50 rounded-xl border border-gray-100 hover:border-gray-200 transition-all"
            >
              <div class="flex items-center gap-3 flex-1 min-w-0">
                <div class="w-9 h-9 rounded-lg bg-cyan-50 border border-cyan-100 flex items-center justify-center shrink-0">
                  <Wrench class="w-4 h-4 text-cyan-600" />
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-[13px] font-medium text-gray-800 truncate">{{ node.name }}</span>
                    <span v-if="node.status === 'online'" class="px-1.5 py-0.5 rounded text-[9px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100">Online</span>
                    <span v-else-if="node.status === 'offline'" class="px-1.5 py-0.5 rounded text-[9px] font-medium text-amber-600 bg-amber-50 border border-amber-100">Offline</span>
                    <span v-else class="px-1.5 py-0.5 rounded text-[9px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-0.5"><Loader2 class="w-2.5 h-2.5 animate-spin" />检测中</span>
                  </div>
                  <div class="text-[11px] text-gray-400 font-mono truncate">{{ node.url }}</div>
                </div>
              </div>
              <div class="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <button @click="testConnection(node)" class="p-1.5 text-gray-400 hover:text-cyan-600 hover:bg-cyan-50 rounded-lg transition-colors" title="测试"><ExternalLink class="w-3.5 h-3.5" /></button>
                <button @click="fetchAd(node)" class="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors" title="查看描述"><Search class="w-3.5 h-3.5" /></button>
                <button @click="openEditModal(node)" class="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors" title="编辑"><Pencil class="w-3.5 h-3.5" /></button>
                <button @click="removeNode(node.id)" class="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors" title="删除"><Trash2 class="w-3.5 h-3.5" /></button>
              </div>
            </div>
            <div v-if="toolNodes.length === 0" class="text-center py-6 text-gray-400 text-[13px]">
              暂无工具节点，请先添加
            </div>
          </div>
        </div>

        <!-- ── Tool Nodes Grid ── -->
        <div v-if="toolNodes.length > 0" class="grid grid-cols-1 gap-4">
          <div v-for="node in toolNodes" :key="node.id"
            class="bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-gray-300 transition-all"
            :class="selectedNodeId === node.id ? 'ring-2 ring-indigo-200 border-indigo-300' : ''"
          >
            <div class="p-5">
              <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                    :class="node.status === 'online' ? 'bg-cyan-50 border border-cyan-100' : 'bg-gray-50 border border-gray-200'">
                    <Wrench class="w-5 h-5" :class="node.status === 'online' ? 'text-cyan-600' : 'text-gray-400'" />
                  </div>
                  <div>
                    <div class="flex items-center gap-2">
                      <span class="text-[14px] font-semibold text-gray-800">{{ node.name }}</span>
                      <span v-if="node.status === 'online'" class="w-2 h-2 rounded-full bg-emerald-400"></span>
                      <span v-else-if="node.status === 'offline'" class="w-2 h-2 rounded-full bg-gray-300"></span>
                      <Loader2 v-else class="w-3 h-3 text-gray-400 animate-spin" />
                    </div>
                    <div class="text-[11px] text-gray-400 font-mono">{{ node.url }}</div>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <button
                    @click="fetchAd(node)"
                    :disabled="node.status !== 'online'"
                    class="px-3 py-1.5 text-[12px] font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 rounded-lg hover:bg-indigo-100 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <Search class="w-3 h-3" /> 查看描述
                  </button>
                  <button @click="testConnection(node)" class="p-1.5 text-gray-400 hover:text-cyan-600 hover:bg-cyan-50 rounded-lg transition-colors" title="刷新状态">
                    <RefreshCw class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── No Data State ── -->
        <div v-if="toolNodes.length === 0" class="flex flex-col items-center justify-center py-20 text-gray-400">
          <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
            <Wrench class="w-8 h-8 text-gray-300" />
          </div>
          <p class="text-sm">请先添加工具节点</p>
          <p class="text-xs text-gray-300 mt-1">支持 ATTP 工具节点、MCP 代理等</p>
        </div>

        <!-- ── Ad Detail Panel ── -->
        <div v-if="adLoading" class="flex items-center justify-center py-12 text-gray-400">
          <Loader2 class="w-5 h-5 animate-spin mr-2" />
          <span class="text-sm">正在获取工具描述...</span>
        </div>

        <div v-if="!adLoading && selectedAd" class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div class="px-5 py-4 border-b border-gray-100 flex items-center gap-3">
            <div class="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center">
              <Info class="w-4 h-4 text-indigo-600" />
            </div>
            <div>
              <span class="text-[14px] font-semibold text-gray-800">{{ selectedAd.name || '未命名工具' }}</span>
              <span class="ml-2 px-1.5 py-0.5 rounded text-[9px] font-medium text-indigo-600 bg-indigo-50 border border-indigo-100">{{ selectedAd.type || 'attp-tool-node' }}</span>
              <span v-if="selectedAd.version" class="ml-1 text-[10px] text-gray-400">v{{ selectedAd.version }}</span>
            </div>
          </div>

          <div class="p-5 space-y-5">
            <!-- Basic Info -->
            <div class="space-y-3">
              <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">基本信息</div>
              <div class="grid grid-cols-2 gap-3">
                <div class="bg-gray-50/50 rounded-lg p-3 border border-gray-100">
                  <div class="text-[10px] text-gray-400 mb-1">DID</div>
                  <div class="text-[12px] font-mono text-gray-700 truncate" :title="selectedAd.identifier">{{ selectedAd.identifier || '--' }}</div>
                </div>
                <div class="bg-gray-50/50 rounded-lg p-3 border border-gray-100">
                  <div class="text-[10px] text-gray-400 mb-1">ATTP Endpoint</div>
                  <div class="text-[12px] font-mono text-gray-700 truncate" :title="selectedAd.attp_endpoint">{{ selectedAd.attp_endpoint || '--' }}</div>
                </div>
              </div>

              <!-- Description -->
              <div v-if="selectedAd.description" class="bg-gray-50/50 rounded-lg p-3 border border-gray-100">
                <div class="text-[10px] text-gray-400 mb-1">描述</div>
                <p class="text-[12px] text-gray-700 leading-relaxed">{{ selectedAd.description }}</p>
              </div>

              <div v-if="selectedAd.public_key_endpoint" class="bg-gray-50/50 rounded-lg p-3 border border-gray-100">
                <div class="text-[10px] text-gray-400 mb-1">公钥端点</div>
                <div class="text-[12px] font-mono text-gray-700 truncate">{{ selectedAd.public_key_endpoint }}</div>
              </div>
            </div>

            <!-- MCP Tools -->
            <div v-if="selectedAd.mcp_tools && selectedAd.mcp_tools.length > 0">
              <div class="text-[11px] font-medium text-gray-400 uppercase tracking-wider mb-3">MCP 工具 ({{ selectedAd.mcp_tools.length }})</div>
              <div class="space-y-2">
                <div v-for="(tool, idx) in selectedAd.mcp_tools" :key="idx"
                  class="flex items-start gap-3 p-3 bg-gray-50/50 rounded-lg border border-gray-100"
                >
                  <div class="w-7 h-7 rounded-md bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0 mt-0.5">
                    <Box class="w-3.5 h-3.5 text-emerald-600" />
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="text-[12px] font-medium text-gray-800">{{ tool.name }}</div>
                    <div v-if="tool.description" class="text-[11px] text-gray-500 mt-0.5 leading-relaxed">{{ tool.description }}</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Raw AD JSON -->
            <details>
              <summary class="text-[11px] text-gray-400 cursor-pointer hover:text-gray-600 transition-colors">查看原始 ad.json</summary>
              <div class="mt-2 bg-gray-50 rounded-lg p-3 text-[11px] font-mono text-gray-600 whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto">
                {{ JSON.stringify(selectedAd, null, 2) }}
              </div>
            </details>
          </div>
        </div>

      </div>
    </div>

    <!-- ── Add Node Modal ── -->
    <div v-if="showAddModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showAddModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[420px] p-6">
        <div class="flex items-center justify-between mb-5">
          <h3 class="text-sm font-semibold text-gray-800">添加工具节点</h3>
          <button @click="showAddModal = false" class="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
            <X class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点名称</label>
            <input v-model="newNodeName" placeholder="e.g. Web Reader" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:border-cyan-300 transition-colors" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点地址</label>
            <input v-model="newNodeUrl" placeholder="http://localhost:8003/attp" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:border-cyan-300 transition-colors font-mono" />
            <p class="text-[10px] text-gray-400 mt-1">工具节点的 HTTP 地址（含 ATTP 前缀）</p>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <button @click="showAddModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button @click="addNode" class="px-4 py-2 text-sm font-medium text-white bg-cyan-600 rounded-lg hover:bg-cyan-700 transition-colors">添加节点</button>
        </div>
      </div>
    </div>

    <!-- ── Edit Node Modal ── -->
    <div v-if="showEditModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showEditModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[420px] p-6">
        <div class="flex items-center justify-between mb-5">
          <h3 class="text-sm font-semibold text-gray-800">编辑工具节点</h3>
          <button @click="showEditModal = false" class="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
            <X class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点名称</label>
            <input v-model="editNodeName" placeholder="e.g. Web Reader" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:border-cyan-300 transition-colors" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点地址</label>
            <input v-model="editNodeUrl" placeholder="http://localhost:8003/attp" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:border-cyan-300 transition-colors font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <button @click="showEditModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button @click="saveEditNode" class="px-4 py-2 text-sm font-medium text-white bg-cyan-600 rounded-lg hover:bg-cyan-700 transition-colors">保存</button>
        </div>
      </div>
    </div>

    <!-- ── Toast ── -->
    <div :class="[
      'fixed top-6 right-6 z-50 transition-all duration-300',
      toastVisible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-10 pointer-events-none'
    ]">
      <div :class="[
        'flex items-center gap-2.5 px-4 py-3 rounded-xl border shadow-lg text-sm',
        toastType === 'success' ? 'bg-emerald-50 border-emerald-100 text-emerald-700' : 'bg-red-50 border-red-100 text-red-700'
      ]">
        <component :is="toastType === 'success' ? Shield : X" class="w-4 h-4" />
        <span>{{ toastMessage }}</span>
      </div>
    </div>
  </div>
</template>
