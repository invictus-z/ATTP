<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useAttpProtocol } from '../composables/useAttpProtocol'
import type { UserAttpConfig } from '../transport'
import { User, ShieldCheck, Link, Plus, Trash2, Check, CheckCircle, XCircle, AlertCircle, Info, Shield, Lock, Repeat } from 'lucide-vue-next'

const {
  userConfig, initialized: attpInitialized, privateKeyLoaded,
  isDemoMode,
  loadAppState, saveUserConfig, setMode,
  addProtocolNode, removeProtocolNode, addAgent, removeAgent,
} = useAttpProtocol()

const newProtocolNodeName = ref('')
const newProtocolNodeUrl = ref('')
const newAgentName = ref('')
const newAgentDid = ref('')
const newAgentUrl = ref('')

// userConfig 已由 App.vue 启动时加载（demo 模式下内含 resources 演示配置）；此处直接展示。
const cfg = computed<UserAttpConfig>(() => userConfig)
// ready = 配置对象已从后端加载就绪；不再要求 did 非空（free 模式空白配置就是要让用户填）
const ready = computed(() => !!cfg.value && attpInitialized.value)
const readonly = computed(() => isDemoMode.value)

async function switchMode() {
  // 演示↔自由双向切换
  if (!confirm(isDemoMode.value
    ? '切换到自由配置模式？将以自有配置启动（若无则生成空白模板）。'
    : '切换到演示模式？将使用内置预置身份（只读）。')) return
  const ok = await setMode(isDemoMode.value ? 'free' : 'demo')
  if (ok) {
    // 切换后整体刷新：智能体列表 / WS 连接 / 全局只读态按新模式重建，避免状态残留
    window.location.reload()
  }
}

// Toast state
const toastVisible = ref(false)
const toastMessage = ref('')
const toastType = ref<'success' | 'error' | 'warning'>('success')

const toastClass = computed(() => {
  switch (toastType.value) {
    case 'success': return 'bg-emerald-50 border-emerald-100 text-emerald-700'
    case 'error': return 'bg-red-50 border-red-100 text-red-700'
    case 'warning': return 'bg-amber-50 border-amber-100 text-amber-700'
    default: return 'bg-gray-50 border-gray-100 text-gray-700'
  }
})

const toastIcon = computed(() => {
  switch (toastType.value) {
    case 'success': return CheckCircle
    case 'error': return XCircle
    case 'warning': return AlertCircle
    default: return Info
  }
})

function showToast(message: string, type: 'success' | 'error' | 'warning', duration = 3000) {
  toastMessage.value = message
  toastType.value = type
  toastVisible.value = true
  setTimeout(() => { toastVisible.value = false }, duration)
}

async function saveAttpConfig() {
  const ok = await saveUserConfig()
  if (ok) showToast('User configuration saved', 'success')
  else showToast('Failed to save user configuration', 'error')
}

function handleAddProtocolNode() {
  const name = newProtocolNodeName.value.trim()
  const url = newProtocolNodeUrl.value.trim()
  if (name && url) { addProtocolNode(name, url); newProtocolNodeName.value = ''; newProtocolNodeUrl.value = '' }
}

function handleAddAgent() {
  const name = newAgentName.value.trim()
  const did = newAgentDid.value.trim()
  const url = newAgentUrl.value.trim()
  if (name && url) { addAgent(name, url, did || undefined); newAgentName.value = ''; newAgentDid.value = ''; newAgentUrl.value = '' }
}

onMounted(() => {
  // 刷新应用态（userConfig 已是 singleton，此处确保最新；mode/llm 同步）
  loadAppState()
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">User Config</h2>
          <span v-if="readonly" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-red-600 bg-red-50 border border-red-100 flex items-center gap-1">
            <Lock class="w-2.5 h-2.5" />演示模式（只读）
          </span>
          <span v-else-if="cfg.did" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100">已配置</span>
          <span v-else class="px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100">未配置</span>
          <button @click="switchMode()" class="ml-auto px-3 py-1.5 text-[12px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
            <Repeat class="w-3.5 h-3.5" />
            {{ isDemoMode ? '切换到自由配置' : '切换到演示模式' }}
          </button>
        </div>
        <p class="text-sm text-gray-500">管理用户端 ATTP 配置，包括 DID、密钥路径、协议节点和已知 Agent。</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto p-8 relative">
      <div class="max-w-4xl mx-auto space-y-6 pb-4">

        <!-- 演示模式只读提示 -->
        <div v-if="readonly" class="flex items-start gap-2.5 p-4 rounded-xl bg-amber-50 border border-amber-100 text-[12px] text-amber-700">
          <Lock class="w-4 h-4 shrink-0 mt-0.5" />
          <span>当前为<strong>演示模式</strong>，展示固定的预置身份与节点配置（只读），不可修改。如需自定义，点上方「切换到自由配置」。</span>
        </div>

        <!-- 自由模式空白引导：未填 DID 时提示下一步 -->
        <div v-if="!readonly && ready && !cfg.did" class="flex items-start gap-2.5 p-4 rounded-xl bg-sky-50 border border-sky-100 text-[12px] text-sky-700">
          <Info class="w-4 h-4 shrink-0 mt-0.5" />
          <span>当前为<strong>自由配置模式</strong>，尚无身份。请填写 User DID / 密钥路径 / 协议节点并点底部 Save；DID 与密钥可用仓库 <code class="bg-sky-100 px-1 rounded">scripts/did_creator.py</code> 生成。</span>
        </div>

        <div v-if="!ready" class="text-center text-sm text-gray-400 py-12">加载配置中…</div>

        <template v-else>
        <!-- User DID Identity -->
        <div>
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
            <User class="w-3.5 h-3.5" />
            <span>用户 ATTP 身份</span>
          </div>
          <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">用户 DID</label>
              <input type="text" v-model="cfg.did" :disabled="readonly" placeholder="did:wba:..." class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono disabled:bg-gray-50 disabled:text-gray-500">
            </div>
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID 文档路径</label>
              <input type="text" v-model="cfg.didDocPath" :disabled="readonly" placeholder="~/.attp/user/did/did.json" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono disabled:bg-gray-50 disabled:text-gray-500">
            </div>
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">私钥路径</label>
              <input type="text" v-model="cfg.didKeyPath" :disabled="readonly" placeholder="~/.attp/user/did/key-1_private.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono disabled:bg-gray-50 disabled:text-gray-500">
              <p v-if="!readonly && cfg.didKeyPath && !privateKeyLoaded" class="mt-1 text-[10px] text-amber-500">⚠ 密钥将在下次发送消息时加载</p>
              <p v-if="!readonly && cfg.didKeyPath && privateKeyLoaded" class="mt-1 text-[10px] text-emerald-500">✓ 密钥已加载</p>
            </div>
          </div>
        </div>

        <!-- Protocol Nodes（协议节点） -->
        <div>
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
            <Shield class="w-3.5 h-3.5" />
            <span>协议节点</span>
            <span class="text-[10px] font-normal text-gray-300 normal-case tracking-normal">（Protocol / 协议节点）</span>
          </div>
          <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
            <div class="space-y-2">
              <div v-for="(node, index) in cfg.protocolNodes" :key="'proto-'+index" class="flex items-center gap-2">
                <span class="text-xs text-gray-500 w-24 shrink-0 truncate">{{ node.name }}</span>
                <input type="text" :value="node.url" readonly class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 font-mono text-gray-600">
                <button v-if="!readonly" @click="removeProtocolNode(index)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"><Trash2 class="w-4 h-4" /></button>
              </div>
              <div v-if="cfg.protocolNodes.length === 0" class="text-[12px] text-gray-300 text-center py-2">暂无协议节点</div>
              <div v-if="!readonly" class="flex items-center gap-2">
                <input type="text" v-model="newProtocolNodeName" placeholder="名称" class="w-24 shrink-0 text-sm bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300">
                <input type="text" v-model="newProtocolNodeUrl" placeholder="http://host:port" class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono" @keydown.enter="handleAddProtocolNode">
                <button @click="handleAddProtocolNode" class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded-lg transition-colors shrink-0"><Plus class="w-4 h-4" /></button>
              </div>
            </div>
          </div>
        </div>

        <!-- Known Agents -->
        <div>
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
            <Link class="w-3.5 h-3.5" />
            <span>智能体</span>
          </div>
          <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
            <div class="space-y-2">
              <div v-for="(agent, index) in cfg.agents" :key="'agent-'+index" class="flex items-center gap-2">
                <span class="text-xs text-gray-500 w-20 shrink-0 truncate">{{ agent.name }}</span>
                <span v-if="agent.did" class="text-[10px] text-gray-400 font-mono truncate max-w-[140px] shrink-0" :title="agent.did">{{ agent.did }}</span>
                <span v-else class="text-[10px] text-gray-300 shrink-0">no DID</span>
                <input type="text" :value="agent.baseUrl" readonly class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 font-mono text-gray-600">
                <button v-if="!readonly" @click="removeAgent(index)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"><Trash2 class="w-4 h-4" /></button>
              </div>
              <div v-if="cfg.agents.length === 0" class="text-[12px] text-gray-300 text-center py-2">暂无 Agent</div>
              <div v-if="!readonly" class="flex items-center gap-2">
                <input type="text" v-model="newAgentName" placeholder="Name" class="w-16 shrink-0 text-sm bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300">
                <input type="text" v-model="newAgentDid" placeholder="did:wba:..." class="w-36 shrink-0 text-sm bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                <input type="text" v-model="newAgentUrl" placeholder="http://host:port" class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono" @keydown.enter="handleAddAgent">
                <button @click="handleAddAgent" class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded-lg transition-colors shrink-0"><Plus class="w-4 h-4" /></button>
              </div>
            </div>
          </div>
        </div>

        <!-- Save Button（演示模式隐藏） -->
        <div v-if="!readonly" class="flex justify-end pt-2">
          <div class="text-[11px] text-gray-400 mr-auto leading-tight pt-1">配置将保存至 ~/.attp/user/config.json</div>
          <button @click="saveAttpConfig()" class="px-5 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm">
            <span class="flex items-center gap-1.5"><Check class="w-3.5 h-3.5" /> Save User Config</span>
          </button>
        </div>
        </template>

      </div>
    </div>

    <!-- Toast -->
    <div :class="['fixed top-6 right-6 z-50 transition-all duration-300', toastVisible ? 'opacity-100 translate-x-0' : 'opacity-0 translate-x-10 pointer-events-none']">
      <div :class="['flex items-center gap-2.5 px-4 py-3 rounded-xl border shadow-lg text-sm', toastClass]">
        <component :is="toastIcon" class="w-4 h-4" />
        <span>{{ toastMessage }}</span>
      </div>
    </div>
  </div>
</template>
