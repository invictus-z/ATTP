<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { apiFetch } from '../transport'
import { Shield, Plus, X, Pencil, Trash2, Loader2, Server, Activity, ExternalLink } from 'lucide-vue-next'

interface TraceNode {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'checking'
}

const STORAGE_KEY = 'nanobot_trace_nodes'

const traceNodes = ref<TraceNode[]>([])
const showAddModal = ref(false)
const showEditModal = ref(false)
const newNodeName = ref('')
const newNodeUrl = ref('http://localhost:9000')
const editNodeName = ref('')
const editNodeUrl = ref('')
const editingNodeId = ref<string | null>(null)

// Toast state
const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error'>('success')

const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
  toastMessage.value = msg
  toastType.value = type
  toastVisible.value = true
  setTimeout(() => { toastVisible.value = false }, 2500)
}

// Load from localStorage
const loadNodes = () => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      traceNodes.value = parsed.map((n: TraceNode) => ({ ...n, status: 'checking' as const }))
    }
  } catch {
    traceNodes.value = []
  }
}

// Save to localStorage
const saveNodes = () => {
  const toStore = traceNodes.value.map(({ id, name, url }) => ({ id, name, url }))
  localStorage.setItem(STORAGE_KEY, JSON.stringify(toStore))
}

// Check node status
const checkNodeStatus = async (node: TraceNode) => {
  node.status = 'checking'
  try {
    const result = await apiFetch(`${node.url}/api/status`)
    node.status = result.ok ? 'online' : 'offline'
  } catch {
    node.status = 'offline'
  }
}

// Check all nodes
const checkAllNodes = () => {
  traceNodes.value.forEach(node => checkNodeStatus(node))
}

// Add node
const addNode = () => {
  const name = newNodeName.value.trim()
  const url = newNodeUrl.value.trim().replace(/\/$/, '')
  if (!name || !url) return

  const id = 'trace_' + Date.now().toString()
  const node: TraceNode = { id, name, url, status: 'checking' }
  traceNodes.value.push(node)
  saveNodes()
  checkNodeStatus(node)

  newNodeName.value = ''
  newNodeUrl.value = 'http://localhost:9000'
  showAddModal.value = false
  showToast(`溯源节点「${name}」已添加`)
}

// Edit node
const openEditModal = (node: TraceNode) => {
  editingNodeId.value = node.id
  editNodeName.value = node.name
  editNodeUrl.value = node.url
  showEditModal.value = true
}

const saveEditNode = () => {
  const name = editNodeName.value.trim()
  const url = editNodeUrl.value.trim().replace(/\/$/, '')
  if (!name || !url || !editingNodeId.value) return

  const node = traceNodes.value.find(n => n.id === editingNodeId.value)
  if (node) {
    node.name = name
    node.url = url
    node.status = 'checking'
    saveNodes()
    checkNodeStatus(node)
    showToast(`溯源节点「${name}」已更新`)
  }

  showEditModal.value = false
  editingNodeId.value = null
}

// Remove node
const removeNode = (id: string) => {
  const node = traceNodes.value.find(n => n.id === id)
  traceNodes.value = traceNodes.value.filter(n => n.id !== id)
  saveNodes()
  if (node) showToast(`溯源节点「${node.name}」已移除`)
}

// Test connection
const testConnection = async (node: TraceNode) => {
  await checkNodeStatus(node)
  if (node.status === 'online') {
    showToast(`「${node.name}」连接成功`, 'success')
  } else {
    showToast(`「${node.name}」连接失败`, 'error')
  }
}

onMounted(() => {
  loadNodes()
  checkAllNodes()
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">溯源模块</h2>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200">{{ traceNodes.length }} 节点</span>
        </div>
        <p class="text-sm text-gray-500">管理溯源协议节点，用于行为溯源、分析报告及污点审计。会话创建时可绑定对应溯源节点。</p>
      </div>
    </header>

    <!-- Content -->
    <div class="flex-1 overflow-y-auto p-8 relative">
      <div class="max-w-4xl mx-auto space-y-6 pb-4">

        <!-- Actions Bar -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <button @click="checkAllNodes" class="px-3 py-2 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 hover:border-gray-300 transition-colors flex items-center gap-1.5">
              <Activity class="w-3.5 h-3.5" />
              检测连接
            </button>
          </div>
          <button @click="showAddModal = true" class="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm flex items-center gap-1.5">
            <Plus class="w-4 h-4" />
            添加溯源节点
          </button>
        </div>

        <!-- Node List -->
        <div class="space-y-3">
          <div
            v-for="node in traceNodes"
            :key="node.id"
            class="group relative flex items-center justify-between p-5 bg-white rounded-2xl border border-gray-200 hover:border-gray-300 hover:shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] transition-all"
          >
            <!-- Left: Info -->
            <div class="flex items-center gap-4 flex-1">
              <div class="w-11 h-11 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center shadow-sm shrink-0">
                <Shield class="w-5.5 h-5.5 text-indigo-600" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2.5 mb-1">
                  <h3 class="text-[14px] font-semibold text-gray-900 truncate">{{ node.name }}</h3>
                  <span v-if="node.status === 'online'" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 flex items-center gap-1">
                    <span class="w-1 h-1 rounded-full bg-emerald-500"></span> Online
                  </span>
                  <span v-else-if="node.status === 'offline'" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100 flex items-center gap-1">
                    <span class="w-1 h-1 rounded-full bg-amber-500"></span> Offline
                  </span>
                  <span v-else class="px-2 py-0.5 rounded-md text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-1">
                    <Loader2 class="w-3 h-3 animate-spin" /> 检测中
                  </span>
                </div>
                <div class="flex items-center gap-1.5 text-[12px] text-gray-500 font-mono">
                  <Server class="w-3 h-3 text-gray-400 shrink-0" />
                  <span class="truncate" :title="node.url">{{ node.url }}</span>
                </div>
              </div>
            </div>

            <!-- Right: Actions -->
            <div class="flex items-center gap-1.5 shrink-0">
              <button @click="testConnection(node)" class="p-2 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors" title="测试连接">
                <ExternalLink class="w-4 h-4" />
              </button>
              <button @click="openEditModal(node)" class="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors" title="编辑">
                <Pencil class="w-4 h-4" />
              </button>
              <button @click="removeNode(node.id)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors" title="删除">
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="traceNodes.length === 0" class="flex flex-col items-center justify-center py-20 text-gray-400">
          <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
            <Shield class="w-8 h-8 text-gray-300" />
          </div>
          <p class="text-sm">暂无溯源协议节点</p>
          <p class="text-xs text-gray-300 mt-1">添加溯源节点以启用行为溯源和污点审计功能</p>
          <button @click="showAddModal = true" class="mt-4 px-4 py-2 text-sm text-indigo-500 hover:text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-xl hover:bg-indigo-100 transition-colors flex items-center gap-1.5">
            <Plus class="w-3.5 h-3.5" />
            添加第一个节点
          </button>
        </div>
      </div>
    </div>

    <!-- Add Node Modal -->
    <div v-if="showAddModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showAddModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[420px] p-6">
        <div class="flex items-center justify-between mb-5">
          <h3 class="text-sm font-semibold text-gray-800">添加溯源节点</h3>
          <button @click="showAddModal = false" class="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
            <X class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点名称</label>
            <input v-model="newNodeName" placeholder="e.g. 主溯源服务" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点地址</label>
            <input v-model="newNodeUrl" placeholder="http://localhost:9000" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors font-mono" />
            <p class="text-[10px] text-gray-400 mt-1">溯源协议节点的 HTTP 地址，如 http://host:port</p>
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <button @click="showAddModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button @click="addNode" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors">添加节点</button>
        </div>
      </div>
    </div>

    <!-- Edit Node Modal -->
    <div v-if="showEditModal" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="showEditModal = false">
      <div class="bg-white rounded-xl shadow-xl border border-gray-100 w-[420px] p-6">
        <div class="flex items-center justify-between mb-5">
          <h3 class="text-sm font-semibold text-gray-800">编辑溯源节点</h3>
          <button @click="showEditModal = false" class="p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
            <X class="w-4 h-4" />
          </button>
        </div>
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点名称</label>
            <input v-model="editNodeName" placeholder="e.g. 主溯源服务" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1.5">节点地址</label>
            <input v-model="editNodeUrl" placeholder="http://localhost:9000" class="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-300 transition-colors font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-6">
          <button @click="showEditModal = false" class="px-4 py-2 text-sm text-gray-500 hover:bg-gray-50 rounded-lg transition-colors">取消</button>
          <button @click="saveEditNode" class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors">保存</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
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