<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useAttpProtocol } from '../composables/useAttpProtocol'
import { Server, Wrench, Bot, Play, Square, ScrollText, Loader2, CheckCircle2, XCircle, Upload, KeyRound } from 'lucide-vue-next'

const { llm, saveLlm, setMode } = useAttpProtocol()

interface HealthState { label: string; url: string; icon: any; status: 'unknown' | 'up' | 'down'; checking: boolean }

const services = ref<HealthState[]>([
  { label: '协议节点 :9000', url: 'http://localhost:9000/api/status', icon: Server, status: 'unknown', checking: false },
  { label: '工具节点 :9999', url: 'http://localhost:9999/attp/ad.json', icon: Wrench, status: 'unknown', checking: false },
  { label: '智能体 :8001', url: 'http://localhost:8001/api/nodes', icon: Bot, status: 'unknown', checking: false },
])

const busy = ref<'load' | 'up' | 'down' | 'logs' | null>(null)
const logs = ref<string>('')
const showLogs = ref(false)
let unsubscribe: (() => void) | null = null
let pollTimer: number | null = null

/** 把 llm 映射为 docker-compose 注入用的 env（仅非空项） */
function llmEnv(): Record<string, string> {
  const env: Record<string, string> = {}
  if (llm.value.apiKey) env.LLM_API_KEY = llm.value.apiKey
  if (llm.value.baseUrl) env.LLM_BASE_URL = llm.value.baseUrl
  if (llm.value.model) env.LLM_MODEL = llm.value.model
  return env
}

async function checkOne(s: HealthState) {
  s.checking = true
  try {
    const res = await window.electronAPI.request(s.url, { method: 'GET' })
    s.status = res?.ok ? 'up' : 'down'
  } catch {
    s.status = 'down'
  } finally {
    s.checking = false
  }
}

async function checkAll() {
  await Promise.all(services.value.map(checkOne))
}

async function run(action: 'up' | 'down' | 'logs') {
  if (busy.value) return
  busy.value = action
  showLogs.value = true
  if (action !== 'logs') logs.value += `\n▶ docker compose ${action} ...\n`
  try {
    await window.electronAPI.dockerCompose(action, llmEnv())
    if (action === 'up' || action === 'down') {
      setTimeout(checkAll, 1500)
    }
  } finally {
    busy.value = null
  }
}

async function loadTarball() {
  if (busy.value) return
  busy.value = 'load'
  showLogs.value = true
  try {
    const res = await window.electronAPI.loadImagesTarball()
    if (res?.ok) setTimeout(checkAll, 1500)
  } finally {
    busy.value = null
  }
}

async function onLlmBlur() {
  await saveLlm()
}

async function switchToFree() {
  if (!confirm('切换到自由配置模式？将以空白配置启动（演示身份不再生效）。')) return
  const ok = await setMode('free')
  if (ok) window.location.reload()  // 整体刷新，按新模式重建智能体列表/连接/只读态
}

onMounted(() => {
  unsubscribe = window.electronAPI.onDockerComposeOutput((chunk) => {
    logs.value += chunk
  })
  checkAll()
  pollTimer = window.setInterval(checkAll, 8000)
})

onUnmounted(() => {
  if (unsubscribe) unsubscribe()
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="flex flex-col h-full fade-in">
    <!-- 换色头部（琥珀色，区别于其它页面） -->
    <header class="bg-gradient-to-r from-amber-50 to-orange-50 border-b border-amber-100 shrink-0 px-8 py-6 z-10">
      <div class="max-w-4xl mx-auto">
        <div class="flex items-center gap-2.5 mb-1.5">
          <span class="px-2 py-0.5 rounded-md text-[10px] font-medium text-red-600 bg-red-50 border border-red-100">演示模式</span>
          <h2 class="text-xl font-semibold text-gray-900 tracking-tight">后端服务</h2>
        </div>
        <p class="text-sm text-gray-500">启动由 docker 编排好的 协议 / 工具(add) / 智能体(nanobot) 三节点。需先启动 docker-desktop </p>
      </div>
    </header>

    <div class="flex-1 overflow-y-auto p-8">
      <div class="max-w-4xl mx-auto space-y-6 pb-4">

        <!-- 服务健康状态 -->
        <div class="bg-white p-5 rounded-xl border border-gray-100">
          <div class="text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3">服务状态</div>
          <div class="grid grid-cols-3 gap-3">
            <div v-for="s in services" :key="s.url" class="flex items-center gap-2.5 p-3 rounded-lg bg-gray-50 border border-gray-100">
              <component :is="s.icon" class="w-4 h-4 text-gray-500 shrink-0" />
              <div class="flex-1 min-w-0">
                <div class="text-xs font-medium text-gray-700 truncate">{{ s.label }}</div>
                <div class="flex items-center gap-1 mt-0.5">
                  <Loader2 v-if="s.checking" class="w-3 h-3 text-gray-400 animate-spin" />
                  <CheckCircle2 v-else-if="s.status === 'up'" class="w-3 h-3 text-emerald-500" />
                  <XCircle v-else-if="s.status === 'down'" class="w-3 h-3 text-red-400" />
                  <span class="text-[10px]" :class="s.status === 'up' ? 'text-emerald-600' : s.status === 'down' ? 'text-red-400' : 'text-gray-400'">
                    {{ s.status === 'up' ? '在线' : s.status === 'down' ? '离线' : '未知' }}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <button @click="checkAll" class="mt-3 text-[11px] text-gray-400 hover:text-gray-600">↻ 立即刷新</button>
        </div>

        <!-- LLM 配置（注入 agent + protocol 两容器） -->
        <div class="bg-white p-5 rounded-xl border border-gray-100">
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3">
            <KeyRound class="w-3.5 h-3.5" /><span>LLM 配置</span>
          </div>
          <div class="space-y-3">
            <div>
              <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">API Key</label>
              <input type="password" v-model="llm.apiKey" @blur="onLlmBlur" placeholder="sk-..." class="w-full text-sm bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-gray-300 focus:bg-white font-mono">
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Base URL</label>
                <input type="text" v-model="llm.baseUrl" @blur="onLlmBlur" placeholder="https://api.deepseek.com" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-gray-300 focus:bg-white font-mono">
              </div>
              <div>
                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Model</label>
                <input type="text" v-model="llm.model" @blur="onLlmBlur" placeholder="deepseek-chat" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-gray-300 focus:bg-white font-mono">
              </div>
            </div>
          </div>
          <p class="text-[11px] text-gray-400 mt-3">用于智能体（nanobot）与协议节点（意图追踪）。启动时会自动注入对应容器。</p>
        </div>

        <!-- 控制按钮 -->
        <div class="bg-white p-5 rounded-xl border border-gray-100">
          <div class="text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3">镜像编排</div>
          <div class="flex flex-wrap gap-2.5">
            <button @click="loadTarball()" :disabled="!!busy" class="px-4 py-2 text-sm font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 disabled:opacity-50 flex items-center gap-1.5">
              <Loader2 v-if="busy === 'load'" class="w-3.5 h-3.5 animate-spin" /><Upload v-else class="w-3.5 h-3.5" /> 导入离线镜像
            </button>
            <button @click="run('up')" :disabled="!!busy" class="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5">
              <Loader2 v-if="busy === 'up'" class="w-3.5 h-3.5 animate-spin" /><Play v-else class="w-3.5 h-3.5" /> 启动
            </button>
            <button @click="run('down')" :disabled="!!busy" class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 flex items-center gap-1.5">
              <Loader2 v-if="busy === 'down'" class="w-3.5 h-3.5 animate-spin" /><Square v-else class="w-3.5 h-3.5" /> 停止
            </button>
            <button @click="run('logs')" :disabled="!!busy" class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 flex items-center gap-1.5">
              <Loader2 v-if="busy === 'logs'" class="w-3.5 h-3.5 animate-spin" /><ScrollText v-else class="w-3.5 h-3.5" /> 查看日志
            </button>
          </div>
          <p class="text-[11px] text-gray-400 mt-3">
            
          </p>
        </div>

        <!-- 日志输出 -->
        <div v-if="showLogs" class="bg-gray-900 rounded-xl border border-gray-800">
          <div class="flex items-center justify-between px-4 py-2 border-b border-gray-800">
            <span class="text-[11px] font-medium text-gray-400">输出</span>
            <button @click="logs = ''" class="text-[11px] text-gray-500 hover:text-gray-300">清空</button>
          </div>
          <pre class="text-[11px] text-gray-300 font-mono p-4 max-h-64 overflow-auto whitespace-pre-wrap">{{ logs || '（等待输出...）' }}</pre>
        </div>

      </div>
    </div>
  </div>
</template>
