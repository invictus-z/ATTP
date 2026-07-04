<script setup lang="ts">
import { ref } from 'vue'
import { useAttpProtocol } from '../composables/useAttpProtocol'
import { Rocket, Sliders, FlaskConical, ShieldAlert, Loader2 } from 'lucide-vue-next'

const { setMode } = useAttpProtocol()
const busy = ref<'demo' | 'free' | null>(null)

async function pick(mode: 'demo' | 'free') {
  if (busy.value) return
  busy.value = mode
  await setMode(mode)
  // setMode 成功后 needsInit 变 false，App.vue 自动切回主界面；无需手动跳转
  busy.value = null
}
</script>

<template>
  <div class="h-screen w-full flex items-center justify-center bg-gradient-to-br from-gray-50 via-white to-gray-100">
    <div class="w-full max-w-3xl px-6">
      <!-- 品牌头 -->
      <div class="text-center mb-10">
        <div class="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gray-900 text-white mb-4">
          <FlaskConical class="w-7 h-7" />
        </div>
        <h1 class="text-2xl font-semibold text-gray-900 tracking-tight">谛听 · ATTP</h1>
        <p class="text-sm text-gray-500 mt-1.5">可溯源安全智能体互联系统 — 首次启动，请选择使用模式</p>
      </div>

      <!-- 两张模式卡片 -->
      <div class="grid grid-cols-2 gap-5">
        <!-- 演示模式 -->
        <button
          @click="pick('demo')"
          :disabled="!!busy"
          class="group text-left bg-white rounded-2xl border-2 border-gray-100 p-6 hover:border-red-200 hover:shadow-lg transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          <div class="flex items-center gap-3 mb-3">
            <div class="w-10 h-10 rounded-xl bg-red-50 text-red-500 flex items-center justify-center group-hover:bg-red-100 transition-colors">
              <Rocket class="w-5 h-5" />
            </div>
            <span v-if="busy === 'demo'" class="text-red-500"><Loader2 class="w-4 h-4 animate-spin" /></span>
          </div>
          <div class="flex items-center gap-2 mb-1.5">
            <h3 class="text-base font-semibold text-gray-900">演示/快速测试模式</h3>
            <span class="px-1.5 py-0.5 rounded text-[10px] font-medium text-red-600 bg-red-50 border border-red-100">演示模式</span>
          </div>
          <p class="text-[13px] text-gray-500 leading-relaxed">
            开箱即用：套用预置 DID 身份与密钥（DID文档已在 attp-diting.cn 部署），
            协议节点 / 智能体 / 工具 由 docker 镜像构建，可一键拉起快速体验完整溯源链路。
          </p>
          <p class="text-[11px] text-gray-400 mt-3">⚠ 身份为公开共享，仅供演示。</p>
        </button>

        <!-- 自由配置模式 -->
        <button
          @click="pick('free')"
          :disabled="!!busy"
          class="group text-left bg-white rounded-2xl border-2 border-gray-100 p-6 hover:border-gray-300 hover:shadow-lg transition-all duration-200 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          <div class="flex items-center gap-3 mb-3">
            <div class="w-10 h-10 rounded-xl bg-gray-100 text-gray-600 flex items-center justify-center group-hover:bg-gray-200 transition-colors">
              <Sliders class="w-5 h-5" />
            </div>
            <span v-if="busy === 'free'" class="text-gray-500"><Loader2 class="w-4 h-4 animate-spin" /></span>
          </div>
          <h3 class="text-base font-semibold text-gray-900 mb-1.5">自由配置模式</h3>
          <p class="text-[13px] text-gray-500 leading-relaxed">
            空白配置启动，请自行生成 / 导入 DID 与密钥，配置协议节点与智能体。
            适合真实部署与自由扩展。
          </p>
          <p class="text-[11px] text-amber-500 mt-3 flex items-center gap-1">
            <ShieldAlert class="w-3.5 h-3.5" /> 未配置 DID 前，协议功能不可用
          </p>
        </button>
      </div>

      <p class="text-center text-[11px] text-gray-400 mt-8">v0.2.0-alpha.1.demo</p>
    </div>
  </div>
</template>
