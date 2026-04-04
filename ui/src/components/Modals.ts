export function renderModals() {
  return `
    <!-- ================= Trace Timeline Modal ================= -->
    <div id="trace-modal" class="fixed inset-0 z-50 hidden items-center justify-center bg-black/40 backdrop-blur-sm opacity-0 transition-opacity duration-300" onclick="window.closeTraceTimeline()">
        <!-- 溯源时间轴面板 -->
        <div class="timeline-content bg-white w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden scale-95 translate-y-4 transition-all duration-300" onclick="event.stopPropagation()">
            <!-- Header -->
            <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
                <div class="flex items-center gap-2">
                    <div class="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center">
                        <i data-lucide="git-merge" class="w-4 h-4 text-indigo-600"></i>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-gray-900">Message Trace</h3>
                        <p id="trace-session-id-label" class="text-[11px] text-gray-500 font-mono">ID: msg_79f8a2b1</p>
                    </div>
                </div>
                <button onclick="window.closeTraceTimeline()" class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>

            <!-- Timeline Content -->
            <div class="p-6 overflow-hidden relative min-h-[300px]" id="trace-timeline-wrapper">
                <div class="relative transition-all duration-300" id="trace-timeline-container">
                    <!-- 动态注入时间轴内容 -->
                </div>
            </div>
            
            <!-- Pagination Controls -->
            <div id="trace-pagination" class="px-6 py-2 border-t border-gray-100 flex items-center justify-between bg-white hidden">
                <button id="trace-prev-btn" class="p-1.5 text-gray-500 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                    <i data-lucide="chevron-left" class="w-4 h-4"></i>
                </button>
                <div id="trace-page-info" class="text-[12px] text-gray-500">Page 1 / 1</div>
                <button id="trace-next-btn" class="p-1.5 text-gray-500 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 rounded disabled:opacity-50 disabled:cursor-not-allowed transition-all">
                    <i data-lucide="chevron-right" class="w-4 h-4"></i>
                </button>
            </div>

            <div class="bg-gray-50 border-t border-gray-100 px-6 py-3 flex items-center justify-between">
                <span class="text-[11px] text-gray-500 font-mono flex items-center gap-1.5">
                    <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Validated Chain
                </span>
                <span id="trace-latency-value" class="text-[11px] font-medium text-gray-400">Total Latency: --ms</span>
            </div>
        </div>
    </div>

    <!-- ================= Flow Diagram Modal ================= -->
    <div id="flow-modal" class="fixed inset-0 z-[60] hidden items-center justify-center bg-black/40 backdrop-blur-sm opacity-0 transition-opacity duration-300" onclick="window.closeFlowDiagram()">
        <div class="flow-content bg-white w-[95%] max-w-5xl rounded-2xl shadow-2xl overflow-hidden scale-95 translate-y-4 transition-all duration-300 flex flex-col max-h-[90vh]" onclick="event.stopPropagation()">
            <!-- Header -->
            <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50 shrink-0">
                <div class="flex items-center gap-2">
                    <div class="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center">
                        <i data-lucide="network" class="w-4 h-4 text-indigo-600"></i>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-gray-900">Message Flow Traces</h3>
                        <p class="text-[11px] text-gray-500 font-mono">End-to-end communication mapping</p>
                    </div>
                </div>
                <div class="flex items-center gap-4">
                    <button onclick="window.closeFlowDiagram()" class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
                        <i data-lucide="x" class="w-5 h-5"></i>
                    </button>
                </div>
            </div>

            <!-- Flow Content (Scrollable List of Traces) -->
            <div class="p-6 overflow-y-auto w-full bg-gray-50/50 flex-1 space-y-6">
                
                <!-- ====== Trace 1 ====== -->
                <div class="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm overflow-x-auto">
                    <div class="text-[11px] font-bold text-gray-500 mb-6 flex justify-between items-center min-w-max">
                        <span class="text-gray-700 bg-gray-100 px-2 py-1 rounded">Trace #1: User Request "Deep Scan"</span>
                        <span class="text-emerald-600 flex items-center gap-1 bg-emerald-50 px-2 py-1 rounded border border-emerald-100"><i data-lucide="check-circle" class="w-3.5 h-3.5"></i> Success (124ms)</span>
                    </div>
                    
                    <div class="relative min-w-max">
                        <!-- Forward path (Emerald dashed) -->
                        <div class="flex items-center relative z-10 shrink-0">
                            <!-- 1. User -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="user" class="w-4 h-4 text-blue-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">User</span>
                                <span class="text-[10px] text-gray-500">Input</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[70px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">UI</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 2. Local Agent -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-gray-50 border border-gray-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="bot" class="w-4 h-4 text-gray-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">Local Agent</span>
                                <span class="text-[10px] text-gray-500">Router</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[70px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">ANP</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 3. Broker -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-indigo-50 border border-indigo-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="arrow-right-left" class="w-4 h-4 text-indigo-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800 text-center leading-tight">MQTT<br>Broker</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[70px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">TCP</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 4. Gateway -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-purple-50 border border-purple-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="server" class="w-4 h-4 text-purple-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">Gateway</span>
                                <span class="text-[10px] text-gray-500">Auth</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[70px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">Local</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 5. Target -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-orange-50 border border-orange-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="shield-check" class="w-4 h-4 text-orange-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800 text-center leading-tight">Target<br>Node</span>
                            </div>
                        </div>

                        <!-- Return path (Gray solid) tightly packed -->
                        <div class="relative mt-3 h-4 w-full shrink-0">
                            <div class="absolute top-1/2 left-[48px] right-[48px] h-px bg-gray-300">
                                <i data-lucide="chevron-left" class="w-4 h-4 text-gray-400 absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 bg-white"></i>
                                <div class="absolute top-1/2 left-1/2 -translate-y-1/2 -translate-x-1/2 px-3 py-0.5 bg-gray-50 border border-gray-200 rounded-full text-[10px] text-gray-600 font-medium shadow-sm whitespace-nowrap">
                                    Return Result to User
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- ====== Trace 2 ====== -->
                <div class="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm overflow-x-auto">
                    <div class="text-[11px] font-bold text-gray-500 mb-6 flex justify-between items-center min-w-max">
                        <span class="text-gray-700 bg-gray-100 px-2 py-1 rounded">Trace #2: Get System Status</span>
                        <span class="text-emerald-600 flex items-center gap-1 bg-emerald-50 px-2 py-1 rounded border border-emerald-100"><i data-lucide="check-circle" class="w-3.5 h-3.5"></i> Success (45ms)</span>
                    </div>
                    
                    <div class="relative min-w-max">
                        <div class="flex items-center relative z-10 shrink-0">
                            <!-- 1. User -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="user" class="w-4 h-4 text-blue-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">User</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[70px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">UI</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 2. Local Agent -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-gray-50 border border-gray-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="bot" class="w-4 h-4 text-gray-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">Local Agent</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[70px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">Local</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 3. Gateway -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-purple-50 border border-purple-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="server" class="w-4 h-4 text-purple-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">Gateway</span>
                            </div>
                        </div>

                        <!-- Return path tightly packed -->
                        <div class="relative mt-3 h-4 w-full shrink-0">
                            <div class="absolute top-1/2 left-[48px] right-[48px] h-px bg-gray-300">
                                <i data-lucide="chevron-left" class="w-4 h-4 text-gray-400 absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 bg-white"></i>
                                <div class="absolute top-1/2 left-1/2 -translate-y-1/2 -translate-x-1/2 px-3 py-0.5 bg-gray-50 border border-gray-200 rounded-full text-[10px] text-gray-600 font-medium shadow-sm whitespace-nowrap">
                                    Return Result to User
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- ====== Trace 3 ====== -->
                <div class="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm overflow-x-auto opacity-70">
                    <div class="text-[11px] font-bold text-gray-500 mb-6 flex justify-between items-center min-w-max">
                        <span class="text-gray-700 bg-gray-100 px-2 py-1 rounded">Trace #3: Keep-Alive Ping</span>
                        <span class="text-blue-500 flex items-center gap-1 bg-blue-50 px-2 py-1 rounded border border-blue-100"><i data-lucide="info" class="w-3.5 h-3.5"></i> Info (8ms)</span>
                    </div>
                    
                    <div class="relative min-w-max">
                        <div class="flex items-center relative z-10 shrink-0">
                            <!-- 1. Local Agent -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-gray-50 border border-gray-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="bot" class="w-4 h-4 text-gray-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800">Local Agent</span>
                            </div>

                            <!-- Line -->
                            <div class="flex-1 border-t border-emerald-300 border-dashed relative min-w-[120px]">
                                <div class="absolute top-0 left-1/2 -translate-y-1/2 -translate-x-1/2 px-2 bg-white text-[10px] text-emerald-600 border border-emerald-100 rounded shadow-sm font-mono whitespace-nowrap">Ping MQTT</div>
                                <i data-lucide="chevron-right" class="w-4 h-4 text-emerald-500 absolute right-0 top-0 -translate-y-1/2 translate-x-1/2 bg-white"></i>
                            </div>

                            <!-- 2. Broker -->
                            <div class="flex flex-col items-center w-24 relative">
                                <div class="w-10 h-10 rounded-full bg-indigo-50 border border-indigo-200 flex items-center justify-center shadow-sm mb-2">
                                    <i data-lucide="arrow-right-left" class="w-4 h-4 text-indigo-600"></i>
                                </div>
                                <span class="text-[11px] font-bold text-gray-800 text-center leading-tight">MQTT<br>Broker</span>
                            </div>
                        </div>

                        <!-- Return path tightly packed -->
                        <div class="relative mt-3 h-4 w-full shrink-0">
                            <div class="absolute top-1/2 left-[48px] right-[48px] h-px bg-gray-300">
                                <i data-lucide="chevron-left" class="w-4 h-4 text-gray-400 absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1/2 bg-white"></i>
                                <div class="absolute top-1/2 left-1/2 -translate-y-1/2 -translate-x-1/2 px-3 py-0.5 bg-gray-50 border border-gray-200 rounded-full text-[10px] text-gray-600 font-medium shadow-sm whitespace-nowrap">
                                    ACK
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

            </div>

            <!-- Footer Pagination -->
            <div class="px-6 py-4 border-t border-gray-100 bg-white flex items-center justify-between shrink-0">
                <span class="text-[12px] text-gray-500 font-medium">Showing 1-3 of 12 Traces</span>
                <div class="flex items-center gap-1">
                    <button class="px-3 py-1.5 border border-gray-200 text-gray-400 rounded-lg text-[12px] cursor-not-allowed">Previous</button>
                    <button class="px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-lg text-[12px] font-semibold border border-indigo-100">1</button>
                    <button class="px-3 py-1.5 hover:bg-gray-50 text-gray-600 rounded-lg text-[12px] transition">2</button>
                    <button class="px-3 py-1.5 hover:bg-gray-50 text-gray-600 rounded-lg text-[12px] transition">3</button>
                    <span class="px-2 text-gray-400 text-[12px]">...</span>
                    <button class="px-3 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-[12px] hover:bg-gray-50 transition shadow-sm">Next</button>
                </div>
            </div>

  `;
}
