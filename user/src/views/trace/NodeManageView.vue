<script setup lang="ts">
/**
 * 视图1 — 协议节点管理。
 * 节点 CRUD + 在线状态检测（/api/status）。
 */
import { onMounted, ref } from 'vue'
import {
  Shield, Plus, X, Pencil, Trash2, Loader2, Activity, ExternalLink,
  CheckCircle2, XCircle,
} from 'lucide-vue-next'
import { useProtocolNodes } from '../../composables/useProtocolNodes'
import { useToast } from '../../composables/useToast'
import { useAttpProtocol } from '../../composables/useAttpProtocol'

const {
  traceNodes, loadNodes, checkAllNodes, addNode, updateNode, removeNode, testConnection,
} = useProtocolNodes()
const { showToast, toastVisible, toastMessage, toastType } = useToast()
const { isDemoMode } = useAttpProtocol()

const showAddModal = ref(false)
const showEditModal = ref(false)
const newNodeName = ref('')
const newNodeUrl = ref('http://localhost:9000')
const editNodeName = ref('')
const editNodeUrl = ref('')
const editingNodeId = ref<string | null>(null)

const doAdd = async () => {
  if (isDemoMode.value) return  // 演示模式只读
  const ok = await addNode(newNodeName.value, newNodeUrl.value)
  if (ok) {
    showToast(`协议节点「${newNodeName.value.trim()}」已添加`)
    newNodeName.value = ''
    newNodeUrl.value = 'http://localhost:9000'
    showAddModal.value = false
  } else {
    showToast('添加失败：名称/URL 为空或 URL 已存在', 'error')
  }
}

const openEdit = (id: string, name: string, url: string) => {
  if (isDemoMode.value) return  // 演示模式只读
  editingNodeId.value = id
  editNodeName.value = name
  editNodeUrl.value = url
  showEditModal.value = true
}

const doEdit = async () => {
  if (!editingNodeId.value) return
  const ok = await updateNode(editingNodeId.value, editNodeName.value, editNodeUrl.value)
  if (ok) {
    showToast(`协议节点「${editNodeName.value.trim()}」已更新`)
    showEditModal.value = false
    editingNodeId.value = null
  } else {
    showToast('更新失败：名称/URL 为空', 'error')
  }
}

const doRemove = async (id: string, name: string) => {
  if (isDemoMode.value) return  // 演示模式只读
  const ok = await removeNode(id)
  if (ok) showToast(`协议节点「${name}」已移除`)
}

const doTest = async (name: string, node: { url: string }) => {
  const n = traceNodes.value.find(x => x.url === node.url)
  if (!n) return
  const status = await testConnection(n)
  showToast(
    status === 'online' ? `「${name}」连接成功` : `「${name}」连接失败`,
    status === 'online' ? 'success' : 'error',
  )
}

onMounted(() => {
  loadNodes(true)
  checkAllNodes()
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-5xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">协议节点管理</h2>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200">{{ traceNodes.length }} 节点</span>
        </div>
        <p class="text-sm text-gray-500">添加 / 编辑 / 删除 / 在线检测协议节点</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto">
      <div class="max-w-5xl mx-auto p-8 space-y-6 pb-8">
        <!-- Actions -->
        <div class="flex items-center justify-between">
          <button @click="checkAllNodes" class="px-3.5 py-2 text-[13px] font-medium text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 hover:border-gray-300 transition-colors flex items-center gap-1.5">
            <Activity class="w-4 h-4" /> 检测全部
          </button>
          <button @click="!isDemoMode && (showAddModal = true)" :disabled="isDemoMode" class="px-4 py-2 text-[13px] font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed">
            <Plus class="w-4 h-4" /> 添加节点
          </button>
        </div>

        <!-- Node Grid -->
        <div v-if="traceNodes.length === 0" class="bg-white rounded-2xl border border-dashed border-gray-200 py-16 text-center">
          <Shield class="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p class="text-sm text-gray-400">暂无协议节点，点击「添加节点」开始</p>
        </div>

        <div v-else class="grid grid-cols-2 gap-4">
          <div v-for="node in traceNodes" :key="node.id"
            class="bg-white rounded-2xl border border-gray-200 p-5 hover:border-gray-300 transition-colors"
          >
            <div class="flex items-start justify-between mb-3">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0">
                  <Shield class="w-5 h-5 text-indigo-600" />
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-[14px] font-semibold text-gray-800 truncate">{{ node.name }}</span>
                    <span v-if="node.status === 'online'" class="px-1.5 py-0.5 rounded text-[9px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100">Online</span>
                    <span v-else-if="node.status === 'offline'" class="px-1.5 py-0.5 rounded text-[9px] font-medium text-amber-600 bg-amber-50 border border-amber-100">Offline</span>
                    <span v-else class="px-1.5 py-0.5 rounded text-[9px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-0.5"><Loader2 class="w-2.5 h-2.5 animate-spin" />检测中</span>
                  </div>
                  <div class="text-[11px] text-gray-400 font-mono truncate mt-0.5">{{ node.url }}</div>
                </div>
              </div>
            </div>

            <div class="flex items-center gap-1 justify-end">
              <button @click="doTest(node.name, node)" class="px-2.5 py-1.5 text-[12px] text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors flex items-center gap-1">
                <ExternalLink class="w-3.5 h-3.5" /> 测试
              </button>
              <button @click="openEdit(node.id, node.name, node.url)" :disabled="isDemoMode" class="px-2.5 py-1.5 text-[12px] text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors flex items-center gap-1 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                <Pencil class="w-3.5 h-3.5" /> 编辑
              </button>
              <button @click="doRemove(node.id, node.name)" :disabled="isDemoMode" class="px-2.5 py-1.5 text-[12px] text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors flex items-center gap-1 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                <Trash2 class="w-3.5 h-3.5" /> 删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Modal -->
    <div v-if="showAddModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="showAddModal = false">
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-900">添加协议节点</h3>
          <button @click="showAddModal = false" class="p-1 text-gray-400 hover:text-gray-600"><X class="w-4 h-4" /></button>
        </div>
        <div class="space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">名称</label>
            <input v-model="newNodeName" placeholder="例如：ATTP Node 1" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">URL</label>
            <input v-model="newNodeUrl" placeholder="http://localhost:9000" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showAddModal = false" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
          <button @click="doAdd" class="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800">添加</button>
        </div>
      </div>
    </div>

    <!-- Edit Modal -->
    <div v-if="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="showEditModal = false">
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-900">编辑协议节点</h3>
          <button @click="showEditModal = false" class="p-1 text-gray-400 hover:text-gray-600"><X class="w-4 h-4" /></button>
        </div>
        <div class="space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">名称</label>
            <input v-model="editNodeName" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200" />
          </div>
          <div>
            <label class="block text-[11px] font-medium text-gray-400 mb-1">URL</label>
            <input v-model="editNodeUrl" class="w-full px-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-200 font-mono" />
          </div>
        </div>
        <div class="flex justify-end gap-2 mt-5">
          <button @click="showEditModal = false" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">取消</button>
          <button @click="doEdit" class="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800">保存</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <transition name="toast">
      <div v-if="toastVisible"
        class="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-4 py-2.5 rounded-xl shadow-lg text-[13px] font-medium flex items-center gap-2"
        :class="toastType === 'success' ? 'bg-gray-900 text-white' : 'bg-red-600 text-white'"
      >
        <CheckCircle2 v-if="toastType === 'success'" class="w-4 h-4" />
        <XCircle v-else class="w-4 h-4" />
        {{ toastMessage }}
      </div>
    </transition>
  </div>
</template>
