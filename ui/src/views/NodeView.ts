export function renderNodeView() {
  return `
<div id="view-node-sec" class="page-view flex flex-col h-full hidden fade-in">
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
        <div class="max-w-4xl mx-auto">
            <div class="flex items-start justify-between">
                <div class="flex items-center gap-4">
                    <!-- 头像 -->
                    <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-emerald-50 to-emerald-100 border border-emerald-200 flex items-center justify-center shadow-sm">
                        <div id="node-header-icon"><i data-lucide="shield-check" class="w-6 h-6 text-emerald-600"></i></div>
                    </div>
                    <!-- 核心信息 -->
                    <div>
                        <div class="flex items-center gap-2.5 mb-1">
                            <h2 id="node-header-name" class="text-xl font-semibold text-gray-900 tracking-tight">Home Security Agent</h2>
                            <span id="node-header-status-badge" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 flex items-center gap-1.5">
                                <span class="w-1 h-1 rounded-full bg-emerald-500"></span> Online
                            </span>
                        </div>
                        <p id="node-header-desc" class="text-sm text-gray-500">负责监控家庭内网 IOT 设备行为，执行本地安全策略拦截异常请求。</p>
                    </div>
                </div>
                
                <!-- 快捷操作按钮 -->
                <div class="flex items-center gap-2">
                    <button class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 rounded-lg transition border border-transparent hover:border-gray-200">
                        <i data-lucide="more-horizontal" class="w-4 h-4"></i>
                    </button>
                </div>
            </div>

            <!-- 详细参数区 -->
            <div class="mt-5 flex items-center flex-wrap gap-x-6 gap-y-3">
                <div class="flex items-center gap-2 text-sm">
                    <span class="text-gray-400 font-medium text-[11px] uppercase tracking-wide">DID</span>
                    <code id="node-header-did" class="text-[13px] text-gray-600 bg-gray-50 border border-gray-100 px-2 py-0.5 rounded-md font-mono">did:wba:home.local:sec-01</code>
                </div>
                <div class="flex items-center gap-2 text-sm">
                    <span class="text-gray-400 font-medium text-[11px] uppercase tracking-wide">Endpoint</span>
                    <span id="node-header-endpoint" class="text-[13px] text-gray-600 flex items-center gap-1"><i data-lucide="link-2" class="w-3 h-3 text-gray-400"></i>http://192.168.1.100:8081/anp</span>
                </div>
                <div class="flex items-center gap-2 text-sm">
                    <span class="text-gray-400 font-medium text-[11px] uppercase tracking-wide">Skills</span>
                    <div id="node-header-skills" class="flex items-center gap-1.5"><span class="text-[11px] px-2 py-0.5 rounded-md bg-gray-50 text-gray-500 border border-gray-100 font-mono">security_check</span></div>
                </div>
            </div>
        </div>
    </header>

    <div class="flex-1 overflow-y-auto p-8 relative">
        <div class="max-w-4xl mx-auto space-y-8 pb-4" id="node-messages-container">
            <div class="flex items-center justify-center my-4">
               <span class="px-3 py-1 bg-white border border-gray-100 rounded-full text-[11px] font-medium cursor-pointer text-gray-400 hover:text-gray-600 hover:bg-gray-50 shadow-sm transition" onclick="if(window.currentSessionId) (window as any).showTraceTimeline(window.currentSessionId)">🕹️ View Trace Logs</span>
            </div>
        </div>
    </div>
    
    <div class="p-5 bg-surface border-t border-gray-100 shrink-0">
        <div class="max-w-4xl mx-auto relative flex items-end bg-white border border-gray-200 focus-within:border-gray-300 focus-within:shadow-[0_0_0_4px_rgba(0,0,0,0.02)] rounded-2xl p-2 transition-all duration-200">
            <!-- 附件按钮 -->
            <button class="p-2.5 text-gray-400 hover:text-gray-600 rounded-xl hover:bg-gray-50 transition-colors shrink-0">
                <i data-lucide="paperclip" class="w-5 h-5"></i>
            </button>
            
            <!-- 文本输入框 -->
            <textarea 
                id="node-chat-input"
                rows="1" 
                class="w-full bg-transparent border-none focus:ring-0 text-[14px] text-gray-800 placeholder-gray-400 resize-none py-3 px-2 mx-1 max-h-32" 
                placeholder="Message Selected Agent Node..."
                style="outline: none;"
            ></textarea>
            
            <!-- 发送按钮 -->
            <button id="node-send-btn" class="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 transition-colors shadow-sm shrink-0">
                <i data-lucide="arrow-up" class="w-5 h-5"></i>
            </button>
        </div>
        <div class="max-w-4xl mx-auto mt-2 text-center">
            <span class="text-[10px] text-gray-400">Local Agent will send this request via ANP protocol. Press <kbd class="font-sans px-1 rounded bg-gray-100 border border-gray-200">Enter</kbd> to send.</span>
        </div>
    </div>
</div>
  `;
}
