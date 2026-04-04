export function renderHomeView() {
  return `
<div id="view-home" class="page-view flex flex-col h-full hidden fade-in">
            <!-- 头部 Profile -->
            <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
                <div class="max-w-4xl mx-auto">
                    <div class="flex items-start justify-between">
                        <div class="flex items-center gap-4">
                            <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-gray-50 to-gray-100 border border-gray-200 flex items-center justify-center shadow-sm">
                                <i data-lucide="bot" class="w-6 h-6 text-gray-600"></i>
                            </div>
                            <div>
                                <div class="flex items-center gap-2.5 mb-1">
                                    <h2 class="text-xl font-semibold text-gray-900 tracking-tight">Local Manager Agent</h2>
                                    <span id="home-agent-status-badge" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-1.5">
                                        <i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i> Connecting...
                                    </span>
                                </div>
                                <p class="text-sm text-gray-500">你本机的主控 Agent，负责调度全网节点、分配任务及执行本地脚本。</p>
                            </div>
                        </div>
                        
                        <!-- NEW: 新建会话按钮 -->
                        <button id="home-new-session-btn" class="p-2 bg-gray-50 text-gray-600 hover:bg-gray-100 hover:text-gray-900 rounded-lg transition-colors border border-gray-200 shadow-sm flex items-center gap-2 text-sm font-medium">
                            <i data-lucide="plus" class="w-4 h-4"></i>
                            New Chat
                        </button>
                    </div>
                </div>
            </header>
<div class="flex flex-1 overflow-hidden">
<div class="flex-1 flex flex-col relative">


            <!-- 聊天记录区 -->
            <div class="flex-1 overflow-y-auto p-8 relative">
                <div id="home-messages-container" class="max-w-4xl mx-auto space-y-8 pb-4">
                </div>
            </div>

            <!-- 输入框 -->
            <div class="p-5 bg-surface border-t border-gray-100 shrink-0">
                <div class="max-w-4xl mx-auto relative flex items-end bg-white border border-gray-200 focus-within:border-gray-300 focus-within:shadow-[0_0_0_4px_rgba(0,0,0,0.02)] rounded-2xl p-2 transition-all duration-200">
                    <button class="p-2.5 text-gray-400 hover:text-gray-600 rounded-xl hover:bg-gray-50 transition-colors shrink-0">
                        <i data-lucide="paperclip" class="w-5 h-5"></i>
                    </button>
                    <textarea id="home-chat-input" rows="1" class="w-full bg-transparent border-none focus:ring-0 text-[14px] text-gray-800 placeholder-gray-400 resize-none py-3 px-2 mx-1 max-h-32" style="outline: none;" placeholder="Command Local Agent..."></textarea>
                    <button id="home-send-btn" class="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-colors shadow-sm shrink-0">
                        <i data-lucide="arrow-up" class="w-5 h-5"></i>
                    </button>
                </div>
            </div>
        
</div>

        <div id="home-right-panel" class="w-80 border-l border-gray-100 bg-gray-50 flex flex-col h-full hidden lg:flex">
             <div class="p-6 border-b border-gray-100 bg-white">
                 <h3 class="text-sm font-semibold text-gray-900">Real-time Network</h3>
             </div>
             <div class="flex-1 overflow-y-auto p-6 space-y-4">
                 
                 <div class="bg-white p-4 rounded-xl border border-gray-100">
                     <div class="text-[11px] font-medium text-gray-400 uppercase mb-3">Logs</div>
                     <div id="rt-log-container" class="space-y-3"></div>
                 </div>
             </div>
        </div>
        </div>
        </div>
  `;
}
