<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useChat } from '../composables/useChat'
import { getActiveAgent } from '../agent_manager'
import { Search, X, ListChecks, Pin, PinOff, MessageSquare, MoreHorizontal, Network, Download, Trash2, Clock, Inbox } from 'lucide-vue-next'

const router = useRouter()
const {
  filteredSessions, searchQuery, currentSessionId, sessions,
  batchMode, selectedSessionIds,
  loadSession, deleteSessionRecord, pinSessionRecord,
  toggleBatchMode, toggleSessionSelect, toggleSelectAll,
  batchDeleteSessions, batchPinSessions, batchUnpinSessions,
} = useChat()

const openMenuId = ref<string | null>(null)

const pinnedSessions = computed(() => filteredSessions.value.filter(s => s.isPinned))
const unpinnedSessions = computed(() => filteredSessions.value.filter(s => !s.isPinned))
const activeAgent = computed(() => getActiveAgent())

const openSession = (id: string) => {
  loadSession(id)
  router.push('/home')
}

const formatSessionTime = (ts: number) => {
  const d = new Date(ts)
  return `${d.toLocaleDateString()} - ${d.toLocaleTimeString()}`
}

const toggleMenu = (id: string, event?: Event) => {
  if (event) event.stopPropagation()
  openMenuId.value = openMenuId.value === id ? null : id
}

const closeMenu = () => { openMenuId.value = null }

const handlePin = (id: string) => {
  pinSessionRecord(id)
  closeMenu()
}

const handleDelete = (id: string) => {
  deleteSessionRecord(id)
  closeMenu()
}

const handleViewTrace = (id: string) => {
  closeMenu()
  // Dispatch event for trace modal
  window.dispatchEvent(new CustomEvent('show-trace-timeline', { detail: { sessionId: id } }))
}

const handleExport = (event: Event) => {
  event.stopPropagation()
  closeMenu()
  // Dispatch export toast event
  window.dispatchEvent(new CustomEvent('show-export-toast'))
}
</script>

<template>
  <div class="flex flex-col h-full overflow-hidden" @click="closeMenu">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
      <div class="max-w-4xl mx-auto flex items-end justify-between">
        <div>
          <div class="flex items-center gap-2.5 mb-1.5">
            <h2 class="text-xl font-semibold text-gray-900 tracking-tight">Sessions</h2>
            <span class="px-2 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200">{{ sessions.length }} Total</span>
          </div>
          <p class="text-sm text-gray-500">查看、置顶或删除你与各个 Agent 节点产生的历史交互会话记录。</p>
        </div>
        <div class="flex items-center gap-3">
          <!-- Search -->
          <div class="relative w-64 hidden md:block">
            <Search class="w-4 h-4 text-gray-400 absolute left-3 top-2.5 pointer-events-none" />
            <input type="text" v-model="searchQuery" placeholder="Search sessions..." class="w-full pl-9 pr-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-400" />
          </div>
          <!-- Batch Mode Button -->
          <button @click.stop="toggleBatchMode()" :class="[
            'px-3 py-2 text-[13px] font-medium rounded-xl transition-colors flex items-center gap-1.5',
            batchMode
              ? 'text-gray-800 bg-gray-200 border border-gray-300 hover:bg-gray-300'
              : 'text-gray-600 bg-gray-50 border border-gray-200 hover:bg-gray-100 hover:border-gray-300'
          ]">
            <component :is="batchMode ? X : ListChecks" class="w-4 h-4" />
            <span>{{ batchMode ? '取消管理' : '管理' }}</span>
          </button>
        </div>
      </div>
    </header>

    <!-- Session List Body -->
    <div class="flex-1 overflow-y-auto p-8 relative">
      <div class="max-w-4xl mx-auto space-y-8 pb-4">
        <!-- Pinned Section -->
        <div v-if="pinnedSessions.length > 0">
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
            <Pin class="w-3.5 h-3.5" />
            <span>Pinned Sessions</span>
          </div>
          <div class="space-y-3">
            <div
              v-for="session in pinnedSessions"
              :key="session.id"
              @click="batchMode ? toggleSessionSelect(session.id) : openSession(session.id)"
              :class="[
                'group relative flex items-center justify-between p-4 bg-white rounded-2xl hover:border-gray-300 hover:shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] transition-all cursor-pointer',
                batchMode && selectedSessionIds.has(session.id) ? 'border-gray-400 ring-1 ring-gray-300' : 'border border-gray-200'
              ]"
            >
              <!-- Checkbox (batch mode) -->
              <div v-if="batchMode" class="flex items-center pl-1 pr-2" @click.stop="toggleSessionSelect(session.id)">
                <input type="checkbox" class="w-4 h-4 rounded border-gray-300 accent-gray-800 cursor-pointer" :checked="selectedSessionIds.has(session.id)" @click.stop="toggleSessionSelect(session.id)" />
              </div>
              <!-- Card Content -->
              <div class="flex items-center gap-4 flex-1">
                <div class="w-10 h-10 rounded-full bg-gray-50 border border-gray-200 text-gray-600 flex items-center justify-center shrink-0 relative">
                  <MessageSquare class="w-5 h-5" />
                  <span v-if="session.unreadCount && session.unreadCount > 0" class="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-medium">{{ session.unreadCount > 9 ? '9+' : session.unreadCount }}</span>
                </div>
                <div>
                  <h3 :class="['text-[14px] mb-0.5', session.isUnread ? 'font-semibold text-gray-900' : 'font-medium text-gray-900']">{{ session.title || 'Empty chat' }}</h3>
                  <div class="flex items-center gap-2 text-[12px] text-gray-500">
                    <span>{{ session.senderName || (activeAgent ? activeAgent.name : 'Agent') }}</span>
                    <span class="w-1 h-1 rounded-full bg-gray-300"></span>
                    <span>{{ formatSessionTime(session.updatedAt) }}</span>
                  </div>
                </div>
              </div>
              <!-- Menu (non-batch) -->
              <div v-if="!batchMode" class="relative">
                <button @click.stop="toggleMenu(session.id, $event)" class="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-xl transition-colors">
                  <MoreHorizontal class="w-5 h-5 pointer-events-none" />
                </button>
                <div v-if="openMenuId === session.id" class="absolute right-0 mt-1 w-44 bg-white border border-gray-100 rounded-xl shadow-[0_10px_30px_-10px_rgba(0,0,0,0.1)] py-1 z-50" @click.stop>
                  <button @click="handlePin(session.id)" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors">
                    <Pin class="w-3.5 h-3.5" /> {{ session.isPinned ? '取消置顶' : '置顶' }}
                  </button>
                  <button @click="handleViewTrace(session.id)" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors">
                    <Network class="w-3.5 h-3.5" /> 查看通讯日志
                  </button>
                  <button @click="handleExport($event)" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors">
                    <Download class="w-3.5 h-3.5" /> 导出溯源报告
                  </button>
                  <div class="h-px bg-gray-100 my-1"></div>
                  <button @click="handleDelete(session.id)" class="w-full text-left px-3 py-2 text-[13px] text-red-600 hover:bg-red-50 flex items-center gap-2 transition-colors group">
                    <Trash2 class="w-3.5 h-3.5 group-hover:scale-110 transition-transform" /> 删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Recent Section -->
        <div>
          <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
            <Clock class="w-3.5 h-3.5" />
            <span>Recent History</span>
          </div>
          <div class="space-y-3">
            <div
              v-for="session in unpinnedSessions"
              :key="session.id"
              @click="batchMode ? toggleSessionSelect(session.id) : openSession(session.id)"
              :class="[
                'group relative flex items-center justify-between p-4 bg-white rounded-2xl hover:border-gray-300 hover:shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] transition-all cursor-pointer',
                batchMode && selectedSessionIds.has(session.id) ? 'border-gray-400 ring-1 ring-gray-300' : 'border border-gray-200'
              ]"
            >
              <!-- Checkbox (batch mode) -->
              <div v-if="batchMode" class="flex items-center pl-1 pr-2" @click.stop="toggleSessionSelect(session.id)">
                <input type="checkbox" class="w-4 h-4 rounded border-gray-300 accent-gray-800 cursor-pointer" :checked="selectedSessionIds.has(session.id)" @click.stop="toggleSessionSelect(session.id)" />
              </div>
              <!-- Card Content -->
              <div class="flex items-center gap-4 flex-1">
                <div class="w-10 h-10 rounded-full bg-gray-50 border border-gray-200 text-gray-600 flex items-center justify-center shrink-0 relative">
                  <MessageSquare class="w-5 h-5" />
                  <span v-if="session.unreadCount && session.unreadCount > 0" class="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-medium">{{ session.unreadCount > 9 ? '9+' : session.unreadCount }}</span>
                </div>
                <div>
                  <h3 :class="['text-[14px] mb-0.5', session.isUnread ? 'font-semibold text-gray-900' : 'font-medium text-gray-900']">{{ session.title || 'Empty chat' }}</h3>
                  <div class="flex items-center gap-2 text-[12px] text-gray-500">
                    <span>{{ session.senderName || (activeAgent ? activeAgent.name : 'Agent') }}</span>
                    <span class="w-1 h-1 rounded-full bg-gray-300"></span>
                    <span>{{ formatSessionTime(session.updatedAt) }}</span>
                  </div>
                </div>
              </div>
              <!-- Menu (non-batch) -->
              <div v-if="!batchMode" class="relative">
                <button @click.stop="toggleMenu(session.id, $event)" class="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-xl transition-colors">
                  <MoreHorizontal class="w-5 h-5 pointer-events-none" />
                </button>
                <div v-if="openMenuId === session.id" class="absolute right-0 mt-1 w-44 bg-white border border-gray-100 rounded-xl shadow-[0_10px_30px_-10px_rgba(0,0,0,0.1)] py-1 z-50" @click.stop>
                  <button @click="handlePin(session.id)" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors">
                    <Pin class="w-3.5 h-3.5" /> {{ session.isPinned ? '取消置顶' : '置顶' }}
                  </button>
                  <button @click="handleViewTrace(session.id)" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors">
                    <Network class="w-3.5 h-3.5" /> 查看通讯日志
                  </button>
                  <button @click="handleExport($event)" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors">
                    <Download class="w-3.5 h-3.5" /> 导出溯源报告
                  </button>
                  <div class="h-px bg-gray-100 my-1"></div>
                  <button @click="handleDelete(session.id)" class="w-full text-left px-3 py-2 text-[13px] text-red-600 hover:bg-red-50 flex items-center gap-2 transition-colors group">
                    <Trash2 class="w-3.5 h-3.5 group-hover:scale-110 transition-transform" /> 删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="filteredSessions.length === 0" class="flex flex-col items-center justify-center py-20 text-gray-400">
          <div class="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mb-4">
            <Inbox class="w-8 h-8 text-gray-300" />
          </div>
          <p class="text-sm">暂无会话记录</p>
          <p class="text-xs text-gray-300 mt-1">开始新对话后这里会显示记录</p>
        </div>
      </div>
    </div>

    <!-- Batch Operations Toolbar -->
    <div v-if="batchMode" class="fixed bottom-0 left-[260px] right-0 bg-white border-t border-gray-200 shadow-[0_-4px_20px_-10px_rgba(0,0,0,0.1)] z-30 transition-all">
      <div class="max-w-4xl mx-auto px-8 py-3 flex items-center justify-between">
        <div class="flex items-center gap-4">
          <label class="flex items-center gap-2 cursor-pointer text-[13px] text-gray-600 hover:text-gray-800 select-none">
            <input type="checkbox" @change="toggleSelectAll(($event.target as HTMLInputElement).checked)" class="w-4 h-4 rounded border-gray-300 text-gray-800 focus:ring-gray-400 cursor-pointer accent-gray-800" />
            <span>全选</span>
          </label>
          <span class="text-[13px] text-gray-400">已选 {{ selectedSessionIds.size }} 项</span>
        </div>
        <div class="flex items-center gap-2">
          <button @click="batchPinSessions()" class="px-3 py-1.5 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
            <Pin class="w-3.5 h-3.5" />
            置顶
          </button>
          <button @click="batchUnpinSessions()" class="px-3 py-1.5 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
            <PinOff class="w-3.5 h-3.5" />
            取消置顶
          </button>
          <button @click="batchDeleteSessions()" class="px-3 py-1.5 text-[13px] font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors flex items-center gap-1.5">
            <Trash2 class="w-3.5 h-3.5" />
            删除
          </button>
          <div class="w-px h-6 bg-gray-200 mx-1"></div>
          <button @click="toggleBatchMode()" class="px-3 py-1.5 text-[13px] font-medium text-gray-500 hover:text-gray-700 transition-colors">
            取消
          </button>
        </div>
      </div>
    </div>
  </div>
</template>