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
            <!-- 搜索框辅助 -->
            <div class="relative w-64 hidden md:block">
                <i data-lucide="search" class="w-4 h-4 text-gray-400 absolute left-3 top-2.5"></i>
                <input type="text" id="session-search" placeholder="Search sessions..." onkeyup="window.filterSessions(event)" class="w-full pl-9 pr-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-400">
            </div>
        </div>
    </header>

    <!-- 会话列表主体 -->
    <div class="flex-1 overflow-y-auto p-8 relative">
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
</div>
  `;
}
