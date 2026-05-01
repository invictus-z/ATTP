import { renderMarkdown } from './markdown';
import { getActiveAgent, getActiveAgentId, wsUrl, apiUrl, onAgentSwitch, updateAgentStatus } from './agent_manager';

export function setupChatLogic() {
  const chatInput = document.getElementById('home-chat-input') as HTMLTextAreaElement;
  const sendBtn = document.getElementById('home-send-btn');
  const messagesContainer = document.querySelector('#home-messages-container');
  const newChatBtn = document.getElementById('home-new-session-btn');

  if (!chatInput || !sendBtn || !messagesContainer) return;

  const statusBadge = document.getElementById('home-agent-status-badge');

  const updateAgentStatusBadge = (status: 'active' | 'offline' | 'connecting') => {
    if (!statusBadge) return;
    if (status === 'active') {
      statusBadge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-emerald-600 bg-emerald-50 border border-emerald-100 flex items-center gap-1.5';
      statusBadge.innerHTML = '<i data-lucide="activity" class="w-3 h-3"></i> Active';
    } else if (status === 'offline') {
      statusBadge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-amber-600 bg-amber-50 border border-amber-100 flex items-center gap-1.5';
      statusBadge.innerHTML = '<i data-lucide="activity" class="w-3 h-3"></i> Offline';
    } else {
      statusBadge.className = 'px-2 py-0.5 rounded-md text-[10px] font-medium text-gray-400 bg-gray-50 border border-gray-200 flex items-center gap-1.5';
      statusBadge.innerHTML = '<i data-lucide="loader-2" class="w-3 h-3 animate-spin"></i> Connecting...';
    }
    if ((window as any).lucide) (window as any).lucide.createIcons();
  };

  const updateHomeHeader = () => {
    const agent = getActiveAgent();
    const headerName = document.getElementById('home-agent-name');
    const headerDesc = document.getElementById('home-agent-desc');
    if (headerName && agent) headerName.innerText = agent.name;
    if (headerDesc && agent) headerDesc.innerText = `Agent backend at ${agent.baseUrl}`;
  };

  const getSessionKey = () => {
    const agentId = getActiveAgentId();
    return agentId ? `nanobot_sessions_${agentId}` : 'nanobot_sessions_default';
  };

  interface ChatMessage {
    role: 'user' | 'agent';
    content: string;
    senderOverride?: string;
    timestamp?: string;
  }
  interface ChatSession {
    id: string;
    title: string;
    messages: ChatMessage[];
    rtLogs?: { senderName: string; text: string }[];
    nodeHistories?: { [targetNode: string]: { role: 'user' | 'agent'; text: string; timeStr: string }[] };
    updatedAt: number;
    isPinned?: boolean;
    isUnread?: boolean;
    unreadCount?: number;
    senderName?: string;
  }

  let sessions: ChatSession[] = [];
  let currentSessionId: string | null = null;
  let batchMode = false;
  let selectedSessionIds = new Set<string>();
  let ws: WebSocket | null = null;
  let wsConnected = false;

  const loadSessions = () => {
    try { sessions = JSON.parse(localStorage.getItem(getSessionKey()) || '[]'); } catch { sessions = []; }
  };

  const saveSessions = () => {
    localStorage.setItem(getSessionKey(), JSON.stringify(sessions));
    renderSessionsList();
  };

  const createSession = (initialTitle: string) => {
    const newSession: ChatSession = {
      id: 'sess_' + Date.now().toString(),
      title: initialTitle,
      messages: [],
      rtLogs: [],
      nodeHistories: {},
      updatedAt: Date.now(),
    };
    sessions.unshift(newSession);
    currentSessionId = newSession.id;
    (window as any).currentSessionId = currentSessionId;
    saveSessions();
    renderCurrentSession();
    return newSession;
  };

  const getCurrentSession = () => sessions.find(s => s.id === currentSessionId);
  (window as any).getCurrentSession = getCurrentSession;

  const getDateKey = (ts: string) => {
    const d = new Date(ts);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  };

  const formatDateLabel = (ts: string) => {
    const d = new Date(ts);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const msgDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diffDays = Math.round((today.getTime() - msgDay.getTime()) / 86400000);
    const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    return `${d.getMonth() + 1}月${d.getDate()}日 ${weekdays[d.getDay()]}`;
  };

  const getDateSeparatorHtml = (ts: string) => `
    <div class="flex items-center justify-center my-4">
      <span class="px-3 py-1 bg-white border border-gray-100 rounded-full text-[11px] font-medium text-gray-400 shadow-sm">${formatDateLabel(ts)}</span>
    </div>`;

  const renderCurrentSession = () => {
    (messagesContainer as HTMLElement).innerHTML = '';
    const session = getCurrentSession();
    if (!session) return;
    let lastDateKey = '';
    session.messages.forEach(msg => {
      if (msg.timestamp) {
        const dateKey = getDateKey(msg.timestamp);
        if (dateKey !== lastDateKey) {
          (messagesContainer as HTMLElement).insertAdjacentHTML('beforeend', getDateSeparatorHtml(msg.timestamp));
          lastDateKey = dateKey;
        }
      }
      (messagesContainer as HTMLElement).insertAdjacentHTML('beforeend', renderMessageHtml(msg));
    });
    scrollToBottom();

    const rtLogs = document.getElementById('rt-log-container');
    if (rtLogs) {
      rtLogs.innerHTML = '';
      if (session.rtLogs) {
        session.rtLogs.forEach(log => {
          const div = document.createElement('div');
          div.className = 'text-xs text-gray-600 mb-1';
          div.innerHTML = `<span class="font-semibold text-gray-700">[${log.senderName}]</span> ${log.text}`;
          rtLogs.appendChild(div);
        });
        rtLogs.scrollTop = rtLogs.scrollHeight;
      }
    }

    const nodeCont = document.getElementById('node-messages-container');
    if (nodeCont) {
      nodeCont.innerHTML = '';
      const currentDid = (document.getElementById('node-header-did')?.innerText || '').trim();
      if (currentDid && session.nodeHistories && session.nodeHistories[currentDid]) {
        session.nodeHistories[currentDid].forEach(h => {
          const msgDiv = document.createElement('div');
          msgDiv.innerHTML = (window as any).renderNodeMessageHtml(h.role, h.text, h.timeStr);
          const actualNode = msgDiv.firstElementChild;
          if (actualNode) nodeCont.appendChild(actualNode);
        });
        if ((window as any).lucide) (window as any).lucide.createIcons();
        nodeCont.parentElement!.scrollTop = nodeCont.parentElement!.scrollHeight;
      }
    }
  };

  const formatTime = (ts: string) => {
    try {
      const d = new Date(ts);
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    } catch { return ''; }
  };

  const renderMessageHtml = (msg: ChatMessage) => {
    const timeStr = msg.timestamp ? formatTime(msg.timestamp) : '';
    if (msg.role === 'user') {
      return `
        <div class="flex justify-end group fade-in">
          <div class="max-w-[80%] flex flex-col items-end">
            <div class="flex items-center space-x-2 mb-1.5 px-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <span class="text-[11px] font-medium text-gray-500">You (Admin)</span>
              ${timeStr ? `<span class="text-[11px] text-gray-400">${timeStr}</span>` : ''}
            </div>
            <div class="bg-gray-800 text-white rounded-2xl rounded-tr-sm p-4 w-full shadow-md text-[14px]">${msg.content}</div>
          </div>
        </div>`;
    } else {
      const agent = getActiveAgent();
      const displaySender = msg.senderOverride || (agent ? agent.name : 'Agent');
      return `
        <div class="flex justify-start group fade-in">
          <div class="max-w-[80%] flex flex-col items-start">
            <div class="flex items-center gap-2 mb-1.5 px-1">
              <div class="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center border border-gray-200">
                <i data-lucide="bot" class="w-3 h-3 text-gray-600"></i>
              </div>
              <span class="text-[11px] font-medium text-gray-600">${displaySender}</span>
              ${timeStr ? `<span class="text-[11px] text-gray-400">${timeStr}</span>` : ''}
            </div>
            <div class="bg-white border border-gray-100 rounded-2xl rounded-tl-sm p-4 w-full shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] text-gray-700 text-[14px] leading-relaxed markdown-body">
              ${renderMarkdown(msg.content)}
            </div>
          </div>
        </div>`;
    }
  };

  const scrollToBottom = () => {
    const scrollArea = document.querySelector('#view-home .overflow-y-auto');
    if (scrollArea) scrollArea.scrollTop = scrollArea.scrollHeight;
    if ((window as any).lucide) (window as any).lucide.createIcons();
  };

  const addMessageToSession = (sessionId: string, role: 'user' | 'agent', content: string, senderOverride?: string) => {
    let session = sessions.find(s => s.id === sessionId);
    if (!session) {
      if (role === 'agent') {
        const agent = getActiveAgent();
        const senderName = senderOverride || (agent ? agent.name : 'Remote Agent');
        const newSession: ChatSession = {
          id: sessionId,
          title: `Message from ${senderName}`,
          messages: [],
          rtLogs: [],
          nodeHistories: {},
          updatedAt: Date.now(),
          isUnread: false,
          unreadCount: 0,
          senderName: senderName,
        };
        sessions.unshift(newSession);
        session = newSession;
      } else {
        session = createSession(content.slice(0, 20) + '...');
      }
    }
    if (session && !session.senderName && senderOverride) {
      const agent = getActiveAgent();
      if (senderOverride !== (agent ? agent.name : 'Agent')) session.senderName = senderOverride;
    }
    if (session.messages.length === 0 && role === 'user') {
      session.title = content.length > 20 ? content.slice(0, 20) + '...' : content;
    }
    if (role === 'agent' && currentSessionId !== sessionId) {
      if (!session.isUnread) session.isUnread = true;
      session.unreadCount = (session.unreadCount || 0) + 1;
    } else if (currentSessionId === sessionId && role === 'agent') {
      session.isUnread = false;
      session.unreadCount = 0;
    }
    const timestamp = new Date().toISOString();
    session.messages.push({ role, content, senderOverride, timestamp });
    session.updatedAt = Date.now();
    saveSessions();
    if (currentSessionId === sessionId) {
      const prevMsg = session.messages.length > 1 ? session.messages[session.messages.length - 2] : null;
      if (!prevMsg || !prevMsg.timestamp || getDateKey(timestamp) !== getDateKey(prevMsg.timestamp)) {
        (messagesContainer as HTMLElement).insertAdjacentHTML('beforeend', getDateSeparatorHtml(timestamp));
      }
      (messagesContainer as HTMLElement).insertAdjacentHTML('beforeend', renderMessageHtml({ role, content, senderOverride, timestamp }));
      scrollToBottom();
    }
    updateSessionsBadge();
  };

  // --- WebSocket ---
  const connectWebSocket = () => {
    if (ws) {
      ws.onopen = null; ws.onclose = null; ws.onerror = null; ws.onmessage = null;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
      ws = null;
    }
    wsConnected = false;
    const agent = getActiveAgent();
    if (!agent) { updateAgentStatusBadge('offline'); return; }
    const targetUrl = wsUrl('/ws');
    if (!targetUrl) { updateAgentStatusBadge('offline'); return; }
    updateAgentStatusBadge('connecting');
    updateAgentStatus(agent.id, 'connecting');
    try { ws = new WebSocket(targetUrl); } catch (e) {
      console.error('Failed to create WebSocket:', e);
      updateAgentStatusBadge('offline');
      updateAgentStatus(agent.id, 'offline');
      return;
    }
    ws.onopen = () => {
      wsConnected = true;
      console.log(`Connected to ${agent.name} over WebSocket`);
      updateAgentStatusBadge('active');
      updateAgentStatus(agent.id, 'active');
    };
    ws.onclose = () => {
      wsConnected = false;
      updateAgentStatusBadge('offline');
      updateAgentStatus(agent.id, 'offline');
    };
    ws.onerror = () => {
      wsConnected = false;
      updateAgentStatusBadge('offline');
      updateAgentStatus(agent.id, 'offline');
    };
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'chat' && data.content) {
          const isNodeMsg = data.metadata && data.metadata.is_node_message;
          const rtLat = document.getElementById('rt-latency');
          const rtLogs = document.getElementById('rt-log-container');
          if (rtLat && data.metadata && data.metadata.latency) rtLat.innerText = data.metadata.latency + ' ms';

          let senderName = agent ? agent.name : 'Agent';
          let rtLogSenderName = agent ? agent.name : 'Agent';
          if (data.metadata && data.metadata.is_node_message) {
            let nodeName = data.metadata.other_did || 'Node';
            if (nodeName !== 'Node') { const parts = nodeName.split(':'); nodeName = parts[parts.length - 1] || nodeName; }
            senderName = nodeName;
            rtLogSenderName = data.metadata.direction === 'in'
              ? `${nodeName} -> ${agent ? agent.name : 'Agent'}`
              : `${agent ? agent.name : 'Agent'} -> ${nodeName}`;
          }

          let targetSessionId = currentSessionId;
          if (data.metadata && data.metadata.Session_ID) targetSessionId = data.metadata.Session_ID;
          else if (data.Session_ID || data.session_id) targetSessionId = data.Session_ID || data.session_id;

          if (rtLogs && data.content) {
            const safeText = data.content.slice(0, 50).replace(/\n/g, ' ');
            if (targetSessionId) {
              let sess = sessions.find(s => s.id === targetSessionId);
              if (!sess) {
                sess = { id: targetSessionId, title: `Message from ${senderName}`, messages: [], rtLogs: [], nodeHistories: {}, updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName: senderName };
                sessions.unshift(sess);
                updateSessionsBadge();
              }
              if (!sess.senderName && senderName) {
                const agentObj = getActiveAgent();
                if (senderName !== (agentObj ? agentObj.name : 'Agent')) sess.senderName = senderName;
              }
              if (!sess.rtLogs) sess.rtLogs = [];
              sess.rtLogs.push({ senderName: rtLogSenderName, text: safeText });
              saveSessions();
            }
            if (targetSessionId === currentSessionId) {
              const div = document.createElement('div');
              div.className = 'text-xs text-gray-600 mb-1';
              div.innerHTML = `<span class="font-semibold text-gray-700">[${rtLogSenderName}]</span> ${safeText}`;
              rtLogs.appendChild(div);
              rtLogs.scrollTop = rtLogs.scrollHeight;
            }
          }

          if (isNodeMsg) {
            const traceModal = document.getElementById('trace-modal');
            if (traceModal && !traceModal.classList.contains('hidden')) {
              if (typeof (window as any).showTraceTimeline === 'function') (window as any).showTraceTimeline(currentSessionId);
            }
            let targetNode = data.metadata.other_did || data.session_id;
            if (targetNode.startsWith('LocalBroker:')) targetNode = targetNode.substring(12);
            const direction = data.metadata ? data.metadata.direction : 'in';
            const role = direction === 'out' ? 'user' : 'agent';
            addNodeMessage(targetSessionId || '', targetNode, role, data.content);
          } else {
            if (targetSessionId) addMessageToSession(targetSessionId, 'agent', data.content, senderName);
          }
        }
      } catch (e) { console.error('WS Error:', e); }
    };
  };

  const checkAgentStatus = () => {
    const statusUrl = apiUrl('/api/status');
    if (!statusUrl || !getActiveAgent()) { updateAgentStatusBadge('offline'); return; }
    fetch(statusUrl).then(res => res.json()).then(data => {
      if (wsConnected) return;
      updateAgentStatusBadge(data.status === 'active' ? 'connecting' : 'offline');
    }).catch(() => { if (!wsConnected) updateAgentStatusBadge('offline'); });
  };

  const initAgentContext = () => {
    loadSessions();
    updateHomeHeader();
    checkAgentStatus();
    connectWebSocket();
    if (sessions.length > 0) {
      currentSessionId = sessions[0].id;
      (window as any).currentSessionId = currentSessionId;
    } else {
      createSession('New Chat');
    }
    renderCurrentSession();
  };

  initAgentContext();
  onAgentSwitch(() => { initAgentContext(); });

  if (newChatBtn) {
    newChatBtn.addEventListener('click', () => { createSession('New Chat'); });
  }

  (window as any).loadSession = (id: string) => {
    const session = sessions.find(s => s.id === id);
    if (session) { session.isUnread = false; session.unreadCount = 0; saveSessions(); updateSessionsBadge(); }
    currentSessionId = id;
    (window as any).currentSessionId = currentSessionId;
    renderCurrentSession();
    const homeBtn = document.getElementById('nav-home');
    if (homeBtn) homeBtn.click();
  };

  (window as any).pinSessionRecord = (e: Event, id: string) => {
    e.stopPropagation();
    const session = sessions.find(s => s.id === id);
    if (session) { session.isPinned = !session.isPinned; saveSessions(); }
  };

  (window as any).deleteSessionRecord = (e: Event, id: string) => {
    e.stopPropagation();
    sessions = sessions.filter(s => s.id !== id);
    if (currentSessionId === id) {
      currentSessionId = sessions.length > 0 ? sessions[0].id : null;
      if (!currentSessionId) createSession('New Chat');
      else renderCurrentSession();
    }
    saveSessions();
  };

  // Batch operations
  const updateBatchUI = () => {
    const toolbar = document.getElementById('batch-toolbar');
    const batchBtn = document.getElementById('batch-mode-btn');
    const countEl = document.getElementById('batch-selected-count');
    const selectAllCb = document.getElementById('select-all-checkbox') as HTMLInputElement;
    if (!toolbar || !batchBtn) return;
    if (batchMode) {
      toolbar.classList.remove('hidden');
      batchBtn.innerHTML = '<i data-lucide="x" class="w-4 h-4"></i><span>取消管理</span>';
      batchBtn.className = 'px-3 py-2 text-[13px] font-medium text-gray-800 bg-gray-200 border border-gray-300 rounded-xl hover:bg-gray-300 transition-colors flex items-center gap-1.5';
    } else {
      toolbar.classList.add('hidden');
      batchBtn.innerHTML = '<i data-lucide="list-checks" class="w-4 h-4"></i><span>管理</span>';
      batchBtn.className = 'px-3 py-2 text-[13px] font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-xl hover:bg-gray-100 hover:border-gray-300 transition-colors flex items-center gap-1.5';
    }
    if (countEl) countEl.textContent = `已选 ${selectedSessionIds.size} 项`;
    if (selectAllCb) {
      const allIds = sessions.map(s => s.id);
      selectAllCb.checked = allIds.length > 0 && allIds.every(id => selectedSessionIds.has(id));
    }
    if ((window as any).lucide) (window as any).lucide.createIcons();
  };

  (window as any).toggleBatchMode = () => {
    batchMode = !batchMode;
    if (!batchMode) selectedSessionIds.clear();
    renderSessionsList((document.getElementById('session-search') as HTMLInputElement)?.value?.toLowerCase() || '');
    updateBatchUI();
  };

  (window as any).toggleSessionSelect = (e: Event, id: string) => {
    e.stopPropagation();
    if (selectedSessionIds.has(id)) selectedSessionIds.delete(id); else selectedSessionIds.add(id);
    const cb = (e.target as HTMLElement).querySelector('input[type=checkbox]') as HTMLInputElement || (e.target as HTMLInputElement);
    if (cb && cb.type === 'checkbox') cb.checked = selectedSessionIds.has(id);
    updateBatchUI();
  };

  (window as any).toggleSelectAll = (checked: boolean) => {
    if (checked) sessions.forEach(s => selectedSessionIds.add(s.id)); else selectedSessionIds.clear();
    document.querySelectorAll('.session-checkbox').forEach((cb: Element) => { (cb as HTMLInputElement).checked = checked; });
    updateBatchUI();
  };

  (window as any).batchDeleteSessions = () => {
    if (selectedSessionIds.size === 0) return;
    sessions = sessions.filter(s => !selectedSessionIds.has(s.id));
    if (selectedSessionIds.has(currentSessionId || '')) {
      currentSessionId = sessions.length > 0 ? sessions[0].id : null;
      (window as any).currentSessionId = currentSessionId;
      if (!currentSessionId) createSession('New Chat'); else renderCurrentSession();
    }
    selectedSessionIds.clear();
    batchMode = false;
    saveSessions();
    updateBatchUI();
  };

  (window as any).batchPinSessions = () => {
    if (selectedSessionIds.size === 0) return;
    sessions.forEach(s => { if (selectedSessionIds.has(s.id) && !s.isPinned) s.isPinned = true; });
    selectedSessionIds.clear();
    batchMode = false;
    saveSessions();
    updateBatchUI();
  };

  (window as any).batchUnpinSessions = () => {
    if (selectedSessionIds.size === 0) return;
    sessions.forEach(s => { if (selectedSessionIds.has(s.id) && s.isPinned) s.isPinned = false; });
    selectedSessionIds.clear();
    batchMode = false;
    saveSessions();
    updateBatchUI();
  };

  const updateSessionsBadge = () => {
    const unreadSessions = sessions.filter(s => s.isUnread && s.unreadCount && s.unreadCount > 0);
    const totalUnread = unreadSessions.reduce((sum, s) => sum + (s.unreadCount || 0), 0);
    const sessionsBtn = document.getElementById('nav-sessions');
    if (!sessionsBtn) return;
    const oldBadge = sessionsBtn.querySelector('.sessions-unread-badge');
    if (oldBadge) oldBadge.remove();
    if (totalUnread > 0) {
      sessionsBtn.classList.add('relative');
      const badge = document.createElement('span');
      badge.className = 'sessions-unread-badge absolute -top-1 -right-1 min-w-5 h-5 px-1 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-medium';
      badge.textContent = totalUnread > 99 ? '99+' : totalUnread.toString();
      sessionsBtn.appendChild(badge);
    }
  };

  (window as any).filterSessions = (event: Event) => {
    const q = (event.target as HTMLInputElement).value.toLowerCase();
    renderSessionsList(q);
  };

  const renderSessionsList = (query: string = '') => {
    const recentList = document.getElementById('recent-list');
    const pinnedList = document.getElementById('pinned-list');
    const pinnedSection = document.getElementById('pinned-section');
    const sessionCount = document.getElementById('session-count');
    if (sessionCount) sessionCount.innerText = `${sessions.length} Total`;
    if (!recentList || !pinnedList || !pinnedSection) return;
    recentList.innerHTML = '';
    pinnedList.innerHTML = '';
    const filteredSessions = sessions.filter(s => s.title.toLowerCase().includes(query));
    let hasPinned = false;

    filteredSessions.forEach(s => {
      const d = new Date(s.updatedAt);
      const timeStr = `${d.toLocaleDateString()} - ${d.toLocaleTimeString()}`;
      const pinText = s.isPinned ? '取消置顶' : '置顶';
      const pinIconClass = s.isPinned ? 'text-brand-600' : 'text-gray-600';
      const isSelected = selectedSessionIds.has(s.id);
      const clickAction = batchMode
        ? `onclick="window.toggleSessionSelect(event, '${s.id}')"`
        : `onclick="window.loadSession('${s.id}')"`;
      const selectedBorder = batchMode && isSelected ? 'border-gray-400 ring-1 ring-gray-300' : 'border-gray-200';
      const checkboxHtml = batchMode ? `<div class="flex items-center pl-1 pr-2" onclick="event.stopPropagation(); window.toggleSessionSelect(event, '${s.id}')"><input type="checkbox" class="session-checkbox w-4 h-4 rounded border-gray-300 accent-gray-800 cursor-pointer" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); window.toggleSessionSelect(event, '${s.id}')"></div>` : '';
      const menuHtml = batchMode ? '' : `
        <div class="relative">
          <button onclick="window.toggleMenu(event, 'menu-${s.id}')" class="p-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-xl transition-colors"><i data-lucide="more-horizontal" class="w-5 h-5 pointer-events-none"></i></button>
          <div id="menu-${s.id}" class="dropdown-menu hidden absolute right-0 mt-1 w-44 bg-white border border-gray-100 rounded-xl shadow-[0_10px_30px_-10px_rgba(0,0,0,0.1)] py-1 z-50">
            <button onclick="window.pinSessionRecord(event, '${s.id}')" class="w-full text-left px-3 py-2 text-[13px] ${pinIconClass} hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors"><i data-lucide="pin" class="w-3.5 h-3.5"></i> ${pinText}</button>
            <button onclick="event.stopPropagation(); window.closeAllDropdowns(); window.showTraceTimeline('${s.id}')" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors"><i data-lucide="network" class="w-3.5 h-3.5"></i> 查看通讯日志</button>
            <button onclick="event.stopPropagation()" class="w-full text-left px-3 py-2 text-[13px] text-gray-600 hover:bg-gray-50 hover:text-gray-900 flex items-center gap-2 transition-colors"><i data-lucide="download" class="w-3.5 h-3.5"></i> 导出溯源报告</button>
            <div class="h-px bg-gray-100 my-1"></div>
            <button onclick="window.deleteSessionRecord(event, '${s.id}')" class="w-full text-left px-3 py-2 text-[13px] text-brand-600 hover:bg-brand-50 flex items-center gap-2 transition-colors group"><i data-lucide="trash-2" class="w-3.5 h-3.5 group-hover:scale-110 transition-transform"></i> 删除</button>
          </div>
        </div>`;

      const htmlStr = `
        <div ${clickAction} class="session-item group relative flex items-center justify-between p-4 bg-white ${selectedBorder} rounded-2xl hover:border-gray-300 hover:shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] transition-all mb-3 cursor-pointer">
          ${checkboxHtml}
          <div class="flex items-center gap-4 flex-1">
            <div class="w-10 h-10 rounded-full bg-gray-50 border border-gray-200 text-gray-600 flex items-center justify-center shrink-0 relative">
              <i data-lucide="message-square" class="w-5 h-5"></i>
              ${s.unreadCount && s.unreadCount > 0 ? `<span class="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white text-xs rounded-full flex items-center justify-center font-medium">${s.unreadCount > 9 ? '9+' : s.unreadCount}</span>` : ''}
            </div>
            <div>
              <h3 class="text-[14px] font-medium text-gray-900 mb-0.5 ${s.isUnread ? 'font-semibold' : ''}">${s.title || 'Empty chat'}</h3>
              <div class="flex items-center gap-2 text-[12px] text-gray-500">
                <span>${s.senderName || (getActiveAgent() ? getActiveAgent()!.name : 'Agent')}</span>
                <span class="w-1 h-1 rounded-full bg-gray-300"></span>
                <span>${timeStr}</span>
              </div>
            </div>
          </div>
          ${menuHtml}
        </div>`;

      if (s.isPinned) { hasPinned = true; pinnedList.insertAdjacentHTML('beforeend', htmlStr); }
      else { recentList.insertAdjacentHTML('beforeend', htmlStr); }
    });

    if (hasPinned) pinnedSection.classList.remove('hidden'); else pinnedSection.classList.add('hidden');
    if ((window as any).lucide) (window as any).lucide.createIcons();
  };

  renderSessionsList();

  // --- Send message ---
  const sendMessage = () => {
    const text = chatInput.value.trim();
    if (!text || !currentSessionId) return;
    addMessageToSession(currentSessionId, 'user', text);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', content: text, session_id: currentSessionId }));
    } else {
      console.warn('WebSocket not open');
    }
    chatInput.value = '';
    chatInput.style.height = 'auto';
  };

  sendBtn.addEventListener('click', sendMessage);
  chatInput.addEventListener('keydown', (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  // --- Node View Chat Logic ---
  const nodeChatInput = document.getElementById('node-chat-input') as HTMLTextAreaElement;
  const nodeSendBtn = document.getElementById('node-send-btn') as HTMLButtonElement;
  const nodeMessagesContainer = document.getElementById('node-messages-container') as HTMLDivElement;

  (window as any).nodeHistories = (window as any).nodeHistories || {};

  (window as any).renderNodeMessageHtml = (role: 'user' | 'agent', text: string, timeStr: string) => {
    const contentClass = role === 'user'
      ? 'bg-gray-900 text-white rounded-2xl rounded-tr-sm px-5 py-3.5 shadow-sm ml-12'
      : 'bg-white border border-gray-100/80 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] text-gray-800 rounded-2xl rounded-tl-sm px-5 py-3.5 mr-12';
    return `
      <div class="${role === 'user' ? 'flex items-start justify-end gap-4' : 'flex items-start gap-4'}">
        ${role === 'agent' ? '<div class="w-8 h-8 rounded-full bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0 shadow-sm mt-1"><i data-lucide="shield-check" class="w-4 h-4 text-emerald-600"></i></div>' : ''}
        <div class="flex flex-col gap-1 ${role === 'user' ? 'items-end' : ''}">
          <div class="flex items-center gap-2 px-1">
            <span class="text-[11px] font-medium text-gray-500 uppercase tracking-wide">${role === 'user' ? 'Agent Request' : 'Node Trace'}</span>
            <span class="text-[10px] text-gray-400 font-mono">${timeStr}</span>
          </div>
          <div class="text-[14px] leading-relaxed relative group ${contentClass} markdown-body">
            ${role === 'agent' ? renderMarkdown(text) : text.replace(/\n/g, '<br>')}
          </div>
        </div>
        ${role === 'user' ? '<div class="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-100 flex items-center justify-center shrink-0 shadow-sm mt-1"><i data-lucide="blocks" class="w-4 h-4 text-indigo-600"></i></div>' : ''}
      </div>`;
  };

  const addNodeMessage = (targetSessionId: string, targetNode: string, role: 'user' | 'agent', text: string) => {
    const timeStr = new Date().toLocaleTimeString();
    if (targetSessionId && targetNode) {
      let sess = sessions.find(s => s.id === targetSessionId);
      if (!sess) {
        sess = { id: targetSessionId, title: `Message from ${targetNode}`, messages: [], rtLogs: [], nodeHistories: {}, updatedAt: Date.now(), isUnread: false, unreadCount: 0, senderName: targetNode };
        sessions.unshift(sess);
        updateSessionsBadge();
      }
      if (!sess.senderName) sess.senderName = targetNode;
      if (!sess.nodeHistories) sess.nodeHistories = {};
      if (!sess.nodeHistories[targetNode]) sess.nodeHistories[targetNode] = [];
      sess.nodeHistories[targetNode].push({ role, text, timeStr });
      if (currentSessionId !== targetSessionId) { sess.isUnread = true; sess.unreadCount = (sess.unreadCount || 0) + 1; }
      else { sess.isUnread = false; sess.unreadCount = 0; }
      saveSessions();
      updateSessionsBadge();
    }
    if (targetSessionId !== currentSessionId) return;
    const currentDid = (document.getElementById('node-header-did')?.innerText || '').trim();
    if (targetNode && currentDid && targetNode !== currentDid) return;
    const msgDiv = document.createElement('div');
    msgDiv.innerHTML = (window as any).renderNodeMessageHtml(role, text, timeStr);
    const actualNode = msgDiv.firstElementChild;
    if (actualNode) {
      nodeMessagesContainer.appendChild(actualNode);
      if ((window as any).lucide) (window as any).lucide.createIcons();
      nodeMessagesContainer.parentElement!.scrollTop = nodeMessagesContainer.parentElement!.scrollHeight;
    }
  };

  const sendNodeMessage = () => {
    const text = nodeChatInput.value.trim();
    const nodeDid = (document.getElementById('node-header-did')?.innerText || '').trim();
    if (!text || !nodeDid || !currentSessionId) return;
    const instructionText = `请使用 send_message_tool 将以下内容发送给节点 ${nodeDid}:\n\n${text}`;
    addMessageToSession(currentSessionId, 'user', instructionText);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', content: instructionText, session_id: currentSessionId }));
    }
    nodeChatInput.value = '';
    nodeChatInput.style.height = 'auto';
    const nodeView = document.getElementById('view-node-sec');
    if (nodeView) nodeView.classList.add('opacity-0', 'transition-opacity', 'duration-200');
    setTimeout(() => {
      (window as any).switchPage('view-home', 'nav-home');
      if (nodeView) nodeView.classList.remove('opacity-0');
    }, 200);
  };

  if (nodeSendBtn && nodeChatInput) {
    nodeSendBtn.addEventListener('click', sendNodeMessage);
    nodeChatInput.addEventListener('keydown', (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendNodeMessage(); }
    });
  }
}