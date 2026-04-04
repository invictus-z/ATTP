export function renderSettingsView() {
  return `
<div id="view-settings" class="page-view flex flex-col h-full hidden fade-in">
    <!-- Header -->
    <header class="bg-white border-b border-gray-100 shrink-0 px-8 py-6 shadow-[0_4px_20px_-15px_rgba(0,0,0,0.05)] z-10">
        <div class="max-w-4xl mx-auto">
            <div class="flex items-center gap-2.5 mb-1.5">
                <h2 class="text-xl font-semibold text-gray-900 tracking-tight">Settings</h2>
                <span id="settings-anp-badge" class="px-2 py-0.5 rounded-md text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200">
                    Loading...
                </span>
            </div>
            <p class="text-sm text-gray-500">管理 ANP 网络配置，包括 DID 身份、客户端连接和服务器设置。</p>
        </div>
    </header>

    <!-- 配置内容区 -->
    <div class="flex-1 overflow-y-auto p-8 relative">
        <div class="max-w-4xl mx-auto space-y-6 pb-4">

            <!-- 加载状态 -->
            <div id="settings-loading" class="flex items-center justify-center py-16">
                <div class="flex items-center gap-3 text-gray-400">
                    <i data-lucide="loader-2" class="w-5 h-5 animate-spin"></i>
                    <span class="text-sm">Loading configuration...</span>
                </div>
            </div>

            <!-- ANP 未启用提示 -->
            <div id="settings-disabled" class="hidden">
                <div class="bg-amber-50 border border-amber-100 rounded-xl p-6 text-center">
                    <div class="w-12 h-12 rounded-xl bg-amber-100 flex items-center justify-center mx-auto mb-3">
                        <i data-lucide="alert-triangle" class="w-6 h-6 text-amber-500"></i>
                    </div>
                    <h3 class="text-sm font-semibold text-amber-800 mb-1">ANP Not Enabled</h3>
                    <p class="text-xs text-amber-600">请在 ~/.nanobot/config.json 中启用 ANP 以使用配置管理功能。</p>
                </div>
            </div>

            <!-- 配置表单 -->
            <div id="settings-form-container" class="hidden space-y-6">

                <!-- 分组 1: DID Identity -->
                <div>
                    <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
                        <i data-lucide="fingerprint" class="w-3.5 h-3.5"></i>
                        <span>DID Identity</span>
                    </div>
                    <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID</label>
                            <input type="text" id="cfg-did" placeholder="did:wba:..." class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                        </div>
                    </div>
                </div>

                <!-- 分组 2: ANP Client -->
                <div>
                    <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
                        <i data-lucide="radio" class="w-3.5 h-3.5"></i>
                        <span>ANP Client</span>
                    </div>
                    <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID Doc Path</label>
                            <input type="text" id="cfg-did-doc-path" placeholder="~/.nanobot/anp/did.json" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">DID Key Path</label>
                            <input type="text" id="cfg-did-key-path" placeholder="~/.nanobot/anp/key-1_private.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Node ADs</label>
                            <div id="cfg-node-ads-list" class="space-y-2"></div>
                            <button onclick="window.addNodeAd()" class="mt-2 flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors">
                                <i data-lucide="plus" class="w-3.5 h-3.5"></i>
                                <span>Add Node AD</span>
                            </button>
                        </div>
                    </div>
                </div>

                <!-- 分组 3: ANP Server -->
                <div>
                    <div class="flex items-center gap-2 text-[11px] font-semibold text-gray-400 tracking-wider uppercase mb-3 px-1">
                        <i data-lucide="server" class="w-3.5 h-3.5"></i>
                        <span>ANP Server</span>
                    </div>
                    <div class="bg-white p-5 rounded-xl border border-gray-100 space-y-4">
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Name</label>
                                <input type="text" id="cfg-server-name" placeholder="My Agent" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300">
                            </div>
                            <div>
                                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Prefix</label>
                                <input type="text" id="cfg-server-prefix" placeholder="/agent" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                            </div>
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Description</label>
                            <input type="text" id="cfg-server-desc" placeholder="Agent description" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300">
                        </div>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Server Port</label>
                                <input type="number" id="cfg-server-port" placeholder="8000" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                            </div>
                            <div></div>
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Private Key Path</label>
                            <input type="text" id="cfg-server-private-key" placeholder="~/.nanobot/anp/server_private.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Public Key Path</label>
                            <input type="text" id="cfg-server-public-key" placeholder="~/.nanobot/anp/server_public.pem" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
                        </div>
                    </div>
                </div>

                <!-- Save 按钮 -->
                <div class="flex items-center justify-between pt-2">
                    <p class="text-[11px] text-gray-400">配置将保存至 ~/.nanobot/anp/anp_config.json</p>
                    <div class="flex items-center gap-3">
                        <button onclick="window.reloadSettingsConfig()" class="px-4 py-2 text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 hover:text-gray-700 transition-colors">
                            <span class="flex items-center gap-1.5"><i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> Reload</span>
                        </button>
                        <button onclick="window.saveSettingsConfig()" id="settings-save-btn" class="px-5 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm">
                            <span class="flex items-center gap-1.5"><i data-lucide="check" class="w-3.5 h-3.5"></i> Save Changes</span>
                        </button>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <!-- Toast 提示 -->
    <div id="settings-toast" class="fixed top-6 right-6 z-50 opacity-0 translate-x-10 pointer-events-none transition-all duration-300">
        <div class="flex items-center gap-2.5 px-4 py-3 rounded-xl border shadow-lg text-sm" id="settings-toast-inner">
            <i id="settings-toast-icon" data-lucide="check-circle" class="w-4 h-4"></i>
            <span id="settings-toast-text">Saved</span>
        </div>
    </div>
</div>
  `;
}