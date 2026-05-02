export function renderSessionsView() {
  return `
<div id="view-sessions" class="page-view flex flex-col h-full hidden fade-in">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
        <div class="max-w-4xl mx-auto flex items-end justify-between">
            <div>
                <div class="flex items-center gap-2.5 mb-1.5">
                    <h2 class="text-xl font-semibold text-gray-900 tracking-tight">Sessions</h2>
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-medium text-gray-500 bg-gray-100 border border-gray-200" id="session-count">0 Total</span>
                </div>
                <p class="text-sm text-gray-500">查看、置顶或删除你与各个 Agent 节点产生的历史交互会话记录。</p>
            </div>
            <div class="flex items-center gap-3">
                <!-- 搜索框辅助 -->
                <div class="relative w-64 hidden md:block">
                    <i data-lucide="search" class="w-4 h-4 text-gray-400 absolute left-3 top-2.5"></i>
                    <input type="text" id="session-search" placeholder="Search sessions..." onkeyup="window.filterSessions(event)" class="w-full pl-9 pr-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-400">
                </div>
                <!-- 批量管理按钮 -->
                <button id="batch-mode-btn" onclick="window.toggleBatchMode()" class="px-3 py-2 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 hover:border-gray-300 transition-colors flex items-center gap-1.5">
                    <i data-lucide="list-checks" class="w-4 h-4"></i>
                    <span>管理</span>
                </button>
            </div>
        </div>
    </header>

    <!-- 会话列表主体 -->
    <div class="flex-1 overflow-y-auto p-8 relative" id="sessions-scroll-area">
        <div class="max-w-4xl mx-auto space-y-8 pb-4">
            <!-- 分区 1：置顶会话 (Pinned) -->
            <div id="pinned-section" class="hidden">
                <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
                    <i data-lucide="pin" class="w-3.5 h-3.5"></i>
                    <span>Pinned Sessions</span>
                </div>
                <div id="pinned-list"></div>
            </div>

            <!-- 分区 2：最近会话 (Recent) -->
            <div id="recent-section">
                <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
                    <i data-lucide="clock" class="w-3.5 h-3.5"></i>
                    <span>Recent History</span>
                </div>
                <div id="recent-list"></div>
            </div>
        </div>
    </div>

    <!-- 批量操作底部工具栏 -->
    <div id="batch-toolbar" class="hidden fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 shadow-[0_-4px_20px_-10px_rgba(0,0,0,0.1)] z-30 transition-all">
        <div class="max-w-4xl mx-auto px-8 py-3 flex items-center justify-between">
            <div class="flex items-center gap-4">
                <label class="flex items-center gap-2 cursor-pointer text-[13px] text-gray-600 hover:text-gray-800 select-none">
                    <input type="checkbox" id="select-all-checkbox" onchange="window.toggleSelectAll(this.checked)" class="w-4 h-4 rounded border-gray-300 text-gray-800 focus:ring-gray-400 cursor-pointer accent-gray-800">
                    <span>全选</span>
                </label>
                <span id="batch-selected-count" class="text-[13px] text-gray-400">已选 0 项</span>
            </div>
            <div class="flex items-center gap-2">
                <button onclick="window.batchPinSessions()" class="px-3 py-1.5 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
                    <i data-lucide="pin" class="w-3.5 h-3.5"></i>
                    置顶
                </button>
                <button onclick="window.batchUnpinSessions()" class="px-3 py-1.5 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors flex items-center gap-1.5">
                    <i data-lucide="pin-off" class="w-3.5 h-3.5"></i>
                    取消置顶
                </button>
                <button onclick="window.batchDeleteSessions()" class="px-3 py-1.5 text-[13px] font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors flex items-center gap-1.5">
                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                    删除
                </button>
                <div class="w-px h-6 bg-gray-200 mx-1"></div>
                <button onclick="window.toggleBatchMode()" class="px-3 py-1.5 text-[13px] font-medium text-gray-500 hover:text-gray-700 transition-colors">
                    取消
                </button>
            </div>
        </div>
    </div>
</div>
  `;
}
