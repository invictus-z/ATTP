<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useSettings } from '../composables/useSettings'
import { Loader2, AlertTriangle, CheckCircle, XCircle, AlertCircle, Info, Fingerprint, Radio, Server, Trash2, Plus, Globe, Wrench, HeartPulse, RotateCcw, Check, RefreshCw, Network } from 'lucide-vue-next'

const {
  config, configStatus, configSaving, configReloading,
  toastVisible, toastMessage, toastType,
  loadConfig, saveConfig, refreshConfig, reloadConfig,
  addNodeAd, removeNodeAd,
  addToolNodeAd, removeToolNodeAd,
} = useSettings()

onMounted(() => { loadConfig() })

window.addEventListener('load-settings', () => { loadConfig() })

const statusBadgeClass = computed(() => {
  switch (configStatus.value) {
    case 'active': return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100'
    case 'disabled': return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100'
    case 'error': return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-red-500 bg-red-50 border border-red-100'
    default: return 'px-2 py-0.5 rounded-md text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200'
  }
})

const statusLabel = computed(() => {
  switch (configStatus.value) {
    case 'active': return 'Active'
    case 'disabled': return 'Disabled'
    case 'error': return 'Error'
    default: return 'Loading...'
  }
})

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
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">Settings</h2>
          <span :class="statusBadgeClass">{{ statusLabel }}</span>
        </div>
        <p class="text-sm text-gray-500">管理 ATTP 网络配置，包括 DID 身份、客户端连接、服务器设置及其他服务配置。</p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto p-8 relative">
      <div class="max-w-4xl mx-auto space-y-6 pb-4">

        <div v-if="configStatus === 'loading'" class="flex items-center justify-center py-16">
          <div class="flex items-center gap-3 text-gray-400">
            <Loader2 class="w-5 h-5 animate-spin" />
            <span class="text-sm">Loading configuration...</span>
          </div>
        </div>

        <div v-else-if="configStatus === 'disabled'">
          <div class="bg-amber-50 border border-amber-100 rounded-xl p-6 text-center">
            <div class="w-12 h-12 rounded-xl bg-amber-100 flex items-center justify-center mx-auto mb-3">
              <AlertTriangle class="w-6 h-6 text-amber-500" />
            </div>
            <h3 class="text-sm font-semibold text-amber-800 mb-1">ATTP Not Enabled</h3>
            <p class="text-xs text-amber-600">请在 ~/.nanobot/config.json 中启用 ATTP 并运行 agent 以使用配置管理功能。</p>
          </div>
        </div>

        <div v-else-if="configStatus === 'active'" class="space-y-6">

          <!-- Group 1: DID Identity -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
              <Fingerprint class="w-3.5 h-3.5" /><span>DID Identity</span>
            </div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID</label>
                <input type="text" v-model="config.did" placeholder="did:wba:..." class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
              </div>
            </div>
          </div>

          <!-- Group 2: ATTP Client -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
              <Radio class="w-3.5 h-3.5" /><span>ATTP Client</span>
            </div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID Doc Path</label>
                <input type="text" v-model="config.attpClient.didDocPath" placeholder="~/.attp/agent/nanobot/did/did.json" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
              </div>
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID Key Path</label>
                <input type="text" v-model="config.attpClient.didKeyPath" placeholder="~/.attp/agent/nanobot/did/key-1_private.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
              </div>
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Node ADs</label>
                <div class="space-y-2">
                  <div v-for="(ad, index) in config.attpClient.nodeAds" :key="index" class="flex items-center gap-2">
                    <input type="text" v-model="config.attpClient.nodeAds[index]" placeholder="http://host:port/agent/ad.json" class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                    <button @click="removeNodeAd(index)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"><Trash2 class="w-4 h-4" /></button>
                  </div>
                </div>
                <button @click="addNodeAd" class="mt-2 flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"><Plus class="w-3.5 h-3.5" /><span>Add Node AD</span></button>
              </div>
            </div>
          </div>

          <!-- Group 3: ATTP Server -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
              <Server class="w-3.5 h-3.5" /><span>ATTP Server</span>
            </div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Name</label><input type="text" v-model="config.attpServer.name" placeholder="My Agent" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300"></div>
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Prefix</label><input type="text" v-model="config.attpServer.prefix" placeholder="/agent" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
              </div>
              <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Description</label><input type="text" v-model="config.attpServer.description" placeholder="Agent description" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300"></div>
              <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Server Host</label><input type="text" v-model="config.attpServer.serverHost" placeholder="127.0.0.1" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Server Port</label><input type="number" v-model.number="config.attpServer.serverPort" placeholder="8000" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
              </div>
              <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Private Key Path</label><input type="text" v-model="config.attpServer.privateKeyPath" placeholder="~/.attp/agent/nanobot/did/server_private.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
              <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Public Key Path</label><input type="text" v-model="config.attpServer.publicKeyPath" placeholder="~/.attp/agent/nanobot/did/server_public.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
            </div>
          </div>

          <!-- Group 4: Web App -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1"><Globe class="w-3.5 h-3.5" /><span>Web App</span></div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Host</label><input type="text" v-model="config.webApp.host" placeholder="127.0.0.1" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Port</label><input type="number" v-model.number="config.webApp.port" placeholder="8001" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
              </div>
            </div>
          </div>

          <!-- Group 5: Tool -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1"><Wrench class="w-3.5 h-3.5" /><span>Tool</span></div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div class="grid grid-cols-2 gap-4">
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Host</label><input type="text" v-model="config.tool.host" placeholder="127.0.0.1" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Port</label><input type="number" v-model.number="config.tool.port" placeholder="8002" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
              </div>
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Tool Node Ads</label>
                <div class="space-y-2">
                  <div v-for="(ad, index) in config.tool.toolNodeAds" :key="index" class="flex items-center gap-2">
                    <input type="text" v-model="config.tool.toolNodeAds[index]" placeholder="http://tool-node:8080/ad.json" class="flex-1 text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                    <button @click="removeToolNodeAd(index)" class="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors shrink-0"><Trash2 class="w-4 h-4" /></button>
                  </div>
                </div>
                <button @click="addToolNodeAd" class="mt-2 flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"><Plus class="w-3.5 h-3.5" /><span>Add Tool Node AD</span></button>
              </div>
            </div>
          </div>

          <!-- Group 6: Heartbeat -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1"><HeartPulse class="w-3.5 h-3.5" /><span>Heartbeat</span></div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div class="grid grid-cols-3 gap-4">
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Interval (s)</label><input type="number" v-model.number="config.heartbeat.interval" placeholder="30" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Timeout (s)</label><input type="number" v-model.number="config.heartbeat.timeout" placeholder="90" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
                <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Max Fail</label><input type="number" v-model.number="config.heartbeat.maxFail" placeholder="3" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
              </div>
            </div>
          </div>

          <!-- Group 7: Protocol Node -->
          <div>
            <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1"><Network class="w-3.5 h-3.5" /><span>Protocol Node</span></div>
            <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
              <div class="flex items-center gap-3">
                <label class="block text-[11px] font-medium text-gray-400 uppercase">Enabled</label>
                <button type="button" @click="config.protocolNode.enabled = !config.protocolNode.enabled" :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none', config.protocolNode.enabled ? 'bg-emerald-500' : 'bg-gray-200']">
                  <span :class="['inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform shadow-sm', config.protocolNode.enabled ? 'translate-x-4.5' : 'translate-x-0.5']" />
                </button>
              </div>
              <div><label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Config Path</label><input type="text" v-model="config.protocolNode.configPath" placeholder="~/.attp/protocol_node/config.json" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono"></div>
            </div>
          </div>

          <!-- Action Buttons -->
          <div class="flex items-center justify-between pt-2">
            <div class="space-y-0.5">
              <p class="text-[11px] text-gray-400">配置将保存至 ~/.attp/agent/nanobot/config.json</p>
              <p class="text-[10px] text-gray-300"><strong>Refresh</strong> 从磁盘重读 · <strong>Save</strong> 仅保存 · <strong>Reload</strong> 保存并应用</p>
            </div>
            <div class="flex items-center gap-3">
              <button @click="refreshConfig()" class="px-4 py-2 text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 hover:text-gray-700 transition-colors" title="从磁盘重新读取配置文件">
                <span class="flex items-center gap-1.5"><RotateCcw class="w-3.5 h-3.5" /> Refresh</span>
              </button>
              <button @click="saveConfig()" :disabled="configSaving" class="px-5 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm disabled:opacity-70" title="保存配置到文件（不立即生效）">
                <span class="flex items-center gap-1.5">
                  <component :is="configSaving ? Loader2 : Check" :class="configSaving ? 'w-3.5 h-3.5 animate-spin' : 'w-3.5 h-3.5'" />
                  {{ configSaving ? 'Saving...' : 'Save Changes' }}
                </span>
              </button>
              <button @click="reloadConfig()" :disabled="configReloading" class="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-xl hover:bg-emerald-700 transition-colors shadow-sm disabled:opacity-70" title="重新读取配置并应用（hot-reload）">
                <span class="flex items-center gap-1.5">
                  <component :is="configReloading ? Loader2 : RefreshCw" :class="configReloading ? 'w-3.5 h-3.5 animate-spin' : 'w-3.5 h-3.5'" />
                  {{ configReloading ? 'Reloading...' : 'Reload' }}
                </span>
              </button>
            </div>
          </div>
        </div>

        <div v-else-if="configStatus === 'error'">
          <div class="bg-red-50 border border-red-100 rounded-xl p-6 text-center">
            <div class="w-12 h-12 rounded-xl bg-red-100 flex items-center justify-center mx-auto mb-3"><AlertTriangle class="w-6 h-6 text-red-500" /></div>
            <h3 class="text-sm font-semibold text-red-800 mb-1">Connection Error</h3>
            <p class="text-xs text-red-600">无法连接到 Agent，请检查 Agent 是否在运行。</p>
            <button @click="loadConfig()" class="mt-3 px-4 py-2 text-sm text-red-600 bg-red-100 hover:bg-red-200 rounded-lg transition-colors">重试</button>
          </div>
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