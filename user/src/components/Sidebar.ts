import { getAgents, getActiveAgent, getActiveAgentId, setActiveAgent, removeAgent, onAgentSwitch } from '../agent_manager';

export function renderSidebar() {
  return `
<aside class="w-[260px] bg-white border-r border-gray-100 flex flex-col shrink-0">
        
        <!-- 用户/系统信息 -->
        <div class="h-16 flex items-center px-5 mb-2">
            <div class="w-7 h-7 rounded-lg bg-gray-100 border border-gray-200 flex items-center justify-center mr-3">
                <i data-lucide="bot" class="w-4 h-4 text-gray-600"></i>
            </div>
            <div class="flex flex-col">
                <span class="text-sm font-semibold text-gray-800">Nanobot</span>
                <span class="text-[11px] text-gray-400">Multi-Agent Workspace</span>
            </div>
        </div>

        <!-- 导航菜单 -->
        <nav class="flex-1 overflow-y-auto px-3 space-y-6">
            
            <!-- 分组 1: AGENTS -->
            <div>
                <div class="px-2 text-[11px] font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                    <span>Agents</span>
                    <button data-action="open-add-agent" class="p-0.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors cursor-pointer" title="Add Agent">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="pointer-events:none;display:block"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                    </button>
                </div>
                <div id="agents-list" class="space-y-0.5">
                  <!-- Agent items rendered dynamically -->
                </div>
                <!-- Empty state -->
                <div id="agents-empty" class="px-2 py-4 text-center hidden">
                    <p class="text-[11px] text-gray-400 mb-2">No agents added</p>
                    <button data-action="open-add-agent" class="text-[11px] text-indigo-500 hover:text-indigo-700 flex items-center gap-1 mx-auto transition-colors cursor-pointer">
                        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="pointer-events:none"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg> Add your first agent
                    </button>
                </div>
            </div>

            <!-- 分组 2: MAIN -->
            <div id="sidebar-main-section" class="hidden">
                <div class="px-2 text-[11px] font-medium text-gray-400 mb-1.5 flex items-center justify-between">
                    <span>Main</span>
                    <i data-lucide="minus" class="w-3 h-3 opacity-50"></i>
                </div>
                <button id="nav-home" onclick="window.switchPage('view-home', 'nav-home')" class="nav-btn w-full flex items-center px-2.5 py-2 text-sm text-gray-500 hover:bg-gray-50 hover:text-gray-800 rounded-lg transition-colors">
                    <i data-lucide="message-square" class="w-4 h-4 mr-3 opacity-70"></i>
                    <span>Home</span>
                </button>
            </div>

            <!-- 分组 3: NETWORK (折叠展开 Nodes) -->
            <div id="sidebar-network-section" class="hidden">
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
                
                <!-- 子节点列表 -->
                <div id="nodes-list" class="pl-7 pr-2 mt-1 space-y-0.5 overflow-hidden transition-all duration-300" style="max-height: 200px;"></div>
            </div>

            <!-- 分组 4: AGENT -->
            <div id="sidebar-agent-section" class="hidden">
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

// ---- Dynamic Agent List Rendering ----

declare global {
  interface Window {
    renderAgentSidebar: () => void;
    switchToAgent: (agentId: string) => void;
    removeAgentFromSidebar: (event: Event, agentId: string) => void;
  }
}

window.renderAgentSidebar = function () {
  const agentsList = document.getElementById('agents-list');
  const agentsEmpty = document.getElementById('agents-empty');
  const mainSection = document.getElementById('sidebar-main-section');
  const networkSection = document.getElementById('sidebar-network-section');
  const agentSection = document.getElementById('sidebar-agent-section');

  if (!agentsList || !agentsEmpty) return;

  const agents = getAgents();
  const activeId = getActiveAgentId();

  // Show/hide sections based on whether an agent is active
  const hasActive = !!getActiveAgent();
  if (mainSection) mainSection.classList.toggle('hidden', !hasActive);
  if (networkSection) networkSection.classList.toggle('hidden', !hasActive);
  if (agentSection) agentSection.classList.toggle('hidden', !hasActive);

  if (agents.length === 0) {
    agentsList.innerHTML = '';
    agentsEmpty.classList.remove('hidden');
    return;
  }

  agentsEmpty.classList.add('hidden');

  agentsList.innerHTML = agents.map(agent => {
    const isActive = agent.id === activeId;
    const statusColor = agent.status === 'active' ? 'bg-emerald-400' : (agent.status === 'connecting' ? 'bg-blue-400' : 'bg-gray-300');
    const activeClasses = isActive ? 'bg-brand-50 text-brand-600 font-medium' : 'text-gray-500 hover:bg-gray-50 hover:text-gray-800';
    const iconOpacity = isActive ? 'opacity-90' : 'opacity-70';

    return `
      <div class="group relative flex items-center">
        <button onclick="window.switchToAgent('${agent.id}')" 
            class="nav-btn w-full flex items-center px-2.5 py-2 text-[13px] rounded-lg transition-colors ${activeClasses}" 
            title="${agent.baseUrl}">
            <i data-lucide="server" class="w-4 h-4 mr-2.5 ${iconOpacity}"></i>
            <span class="flex-1 text-left truncate">${agent.name}</span>
            <span class="w-1.5 h-1.5 rounded-full ${statusColor} shrink-0 mr-1"></span>
        </button>
        <!-- Delete button (shown on hover) -->
        <button onclick="window.removeAgentFromSidebar(event, '${agent.id}')" 
            class="absolute right-1 top-1/2 -translate-y-1/2 p-1 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition-all" 
            title="Remove agent">
            <i data-lucide="x" class="w-3 h-3"></i>
        </button>
      </div>
    `;
  }).join('');

  if ((window as any).lucide) (window as any).lucide.createIcons();
};

window.switchToAgent = function (agentId: string) {
  const currentActive = getActiveAgentId();
  if (agentId === currentActive) return;

  setActiveAgent(agentId);
  window.renderAgentSidebar();

  // Trigger full UI refresh for the new agent context
  if (typeof (window as any).switchPage === 'function') {
    (window as any).switchPage('view-home', 'nav-home');
  }
};

window.removeAgentFromSidebar = function (event: Event, agentId: string) {
  event.stopPropagation();
  removeAgent(agentId);
  window.renderAgentSidebar();
};

// Listen for agent switch events to re-render sidebar
onAgentSwitch(() => {
  window.renderAgentSidebar();
});

// Setup the '+' button click handlers (called from main.ts after DOM ready)
export function setupAddAgentButton() {
  // Top '+' button
  const btn = document.getElementById('open-add-agent-btn');
  if (btn) {
    btn.addEventListener('click', () => {
      if (typeof (window as any).openAddAgentModal === 'function') {
        (window as any).openAddAgentModal();
      }
    });
  }

  // Empty state "Add your first agent" button
  const firstBtn = document.getElementById('add-first-agent-btn');
  if (firstBtn) {
    firstBtn.addEventListener('click', () => {
      if (typeof (window as any).openAddAgentModal === 'function') {
        (window as any).openAddAgentModal();
      }
    });
  }
}
