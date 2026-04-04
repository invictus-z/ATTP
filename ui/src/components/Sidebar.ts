export function renderSidebar() {
  return `
<aside class="w-[260px] bg-white border-r border-gray-100 flex flex-col shrink-0">
        
        <!-- 用户/系统信息 -->
        <div class="h-16 flex items-center px-5 mb-2">
            <div class="w-7 h-7 rounded-lg bg-gray-100 border border-gray-200 flex items-center justify-center mr-3">
                <i data-lucide="bot" class="w-4 h-4 text-gray-600"></i>
            </div>
            <div class="flex flex-col">
                <span class="text-sm font-semibold text-gray-800">Nanobot Local</span>
                <span class="text-[11px] text-gray-400">Safe Agent</span>
            </div>
        </div>

        <!-- 导航菜单 -->
        <nav class="flex-1 overflow-y-auto px-3 space-y-6">
            
            <!-- 分组 1: MAIN -->
            <div>
                <div class="px-2 text-[11px] font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                    <span>Main</span>
                    <i data-lucide="minus" class="w-3 h-3 opacity-50"></i>
                </div>
                <button id="nav-home" onclick="window.switchPage('view-home', 'nav-home')" class="nav-btn w-full flex items-center px-2.5 py-2 text-sm text-gray-500 hover:bg-gray-50 hover:text-gray-800 rounded-lg transition-colors">
                    <i data-lucide="message-square" class="w-4 h-4 mr-3 opacity-70"></i>
                    <span>Home (Local Agent)</span>
                </button>
            </div>

            <!-- 分组 2: NETWORK (折叠展开 Nodes) -->
            <div>
                <div class="px-2 text-[11px] font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                    <span>Network</span>
                    <i data-lucide="minus" class="w-3 h-3 opacity-50"></i>
                </div>
                <!-- 父级分类 (可折叠) -->
                <button onclick="window.toggleNodes()" class="w-full flex items-center justify-between px-2.5 py-2 text-sm text-gray-800 font-medium hover:bg-gray-50 rounded-lg transition-colors group">
                    <div class="flex items-center">
                        <i data-lucide="network" class="w-4 h-4 mr-3 opacity-70 text-gray-500"></i>
                        <span>Nodes</span>
                    </div>
                    <i data-lucide="chevron-down" id="nodes-chevron" class="w-4 h-4 text-gray-400 transition-transform duration-300"></i>
                </button>
                
                <!-- 子节点列表 (缩进排列)，添加动画容器 -->
                <div id="nodes-list" class="pl-7 pr-2 mt-1 space-y-0.5 overflow-hidden transition-all duration-300" style="max-height: 200px;"></div>
            </div>

            <!-- 分组 3: AGENT -->
            <div>
                <div class="px-2 text-[11px] font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                    <span>Agent</span>
                    <i data-lucide="minus" class="w-3 h-3 opacity-50"></i>
                </div>
                <button class="w-full flex items-center px-2.5 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition-colors">
                    <i data-lucide="zap" class="w-4 h-4 mr-3 opacity-70"></i>
                    <span>Skills</span>
                </button>
                <button id="nav-sessions" onclick="window.switchPage('view-sessions', 'nav-sessions')" class="nav-btn relative w-full flex items-center px-2.5 py-2 text-sm text-gray-500 hover:bg-gray-50 hover:text-gray-800 rounded-lg transition-colors">
                    <i data-lucide="history" class="w-4 h-4 mr-3 opacity-70"></i>
                    <span>Sessions</span>
                </button>
            </div>
            
        </nav>

        <!-- 底部设置 -->
        <div class="p-4 mt-auto">
            <button id="nav-settings" onclick="window.switchPage('view-settings', 'nav-settings'); window.loadSettingsConfig();" class="nav-btn w-full flex items-center px-2.5 py-2 text-sm text-gray-500 hover:bg-gray-50 hover:text-gray-800 rounded-lg transition-colors">
                <i data-lucide="settings" class="w-4 h-4 mr-3 opacity-70"></i>
                <span>Settings</span>
            </button>
        </div>
    </aside>
  `;
}
