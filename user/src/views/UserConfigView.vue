<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAttpProtocol } from '../composables/useAttpProtocol'
import { User, ShieldCheck, Link, Plus, Trash2, Check, CheckCircle, XCircle, AlertCircle, Info, Shield } from 'lucide-vue-next'
import { computed } from 'vue'

const {
  userConfig, initialized: attpInitialized, privateKeyLoaded,
  loadUserConfig, saveUserConfig,
  addProtocolNode, removeProtocolNode, addAgent, removeAgent,
} = useAttpProtocol()

const newProtocolNodeName = ref('')
const newProtocolNodeUrl = ref('')
const newAgentName = ref('')
const newAgentDid = ref('')
const newAgentUrl = ref('')

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

onMounted(() => { loadUserConfig() })
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">User Config</h2>
          <span v-if="attpInitialized" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100">已配置</span>
          <span v-else class="px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100">未配置</span>
        </div>
        <p class="text-sm text-gray-500">管理用户端 ATTP 身份配置，包括 DID、密钥路径、协议节点和已知 Agent。</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto p-8 relative">
      <div class="max-w-4xl mx-auto space-y-6 pb-4">

        <!-- User DID Identity -->
        <div>
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
            <User class="w-3.5 h-3.5" />
            <span>User ATTP Identity</span>
          </div>
          <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">User DID</label>
              <input type="text" v-model="userConfig.did" placeholder="did:wba:..." class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
            </div>
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID Document Path</label>
              <input type="text" v-model="userConfig.didDocPath" placeholder="~/.attp/user/did/did.json" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
            </div>
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Private Key Path</label>
              <input type="text" v-model="userConfig.didKeyPath" placeholder="~/.attp/user/did/key-1_private.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
              <p v-if="userConfig.didKeyPath && !privateKeyLoaded" class="mt-1 text-[10px] text-amber-500">⚠ 密钥将在下次发送消息时加载</p>
              <p v-if="userConfig.didKeyPath && privateKeyLoaded" class="mt-1 text-[10px] text-emerald-500">✓ 密钥已加载</p>
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
              <div v-for="(node, index) in userConfig.protocolNodes" :key="'proto-'+index" class="flex items-center gap-2">
                <span class="text-xs text-gray-500 w-24 shrink-0 truncate">{{ node.name }}</span>
                <input type="text" :value="node.url" readonly class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 font-mono text-gray-600">
                <button @click="removeProtocolNode(index)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"><Trash2 class="w-4 h-4" /></button>
              </div>
              <div v-if="userConfig.protocolNodes.length === 0" class="text-[12px] text-gray-300 text-center py-2">暂无协议节点</div>
              <div class="flex items-center gap-2">
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
            <span>Known Agents</span>
          </div>
          <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
            <div class="space-y-2">
              <div v-for="(agent, index) in userConfig.agents" :key="'agent-'+index" class="flex items-center gap-2">
                <span class="text-xs text-gray-500 w-20 shrink-0 truncate">{{ agent.name }}</span>
                <span v-if="agent.did" class="text-[10px] text-gray-400 font-mono truncate max-w-[140px] shrink-0" :title="agent.did">{{ agent.did }}</span>
                <span v-else class="text-[10px] text-gray-300 shrink-0">no DID</span>
                <input type="text" :value="agent.baseUrl" readonly class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 font-mono text-gray-600">
                <button @click="removeAgent(index)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"><Trash2 class="w-4 h-4" /></button>
              </div>
              <div class="flex items-center gap-2">
                <input type="text" v-model="newAgentName" placeholder="Name" class="w-16 shrink-0 text-sm bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300">
                <input type="text" v-model="newAgentDid" placeholder="did:wba:..." class="w-36 shrink-0 text-sm bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                <input type="text" v-model="newAgentUrl" placeholder="http://host:port" class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono" @keydown.enter="handleAddAgent">
                <button @click="handleAddAgent" class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded-lg transition-colors shrink-0"><Plus class="w-4 h-4" /></button>
              </div>
            </div>
          </div>
        </div>

        <!-- Save Button -->
        <div class="flex justify-end pt-2">
          <div class="text-[11px] text-gray-400 mr-auto leading-tight pt-1">配置将保存至 ~/.attp/user/config.json</div>
          <button @click="saveAttpConfig()" class="px-5 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm">
            <span class="flex items-center gap-1.5"><Check class="w-3.5 h-3.5" /> Save User Config</span>
          </button>
        </div>

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