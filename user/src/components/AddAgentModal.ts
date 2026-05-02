import { addAgent, testAgentConnection, setActiveAgent, updateAgentStatus } from '../agent_manager';

export function renderAddAgentModal(): string {
  return `
    <!-- Add Agent Modal -->
    <div id="add-agent-modal" class="fixed inset-0 z-50 hidden items-center justify-center bg-black/40 backdrop-blur-sm opacity-0 transition-opacity duration-300" onclick="window.closeAddAgentModal()">
      <div class="bg-white w-full max-w-md rounded-2xl shadow-2xl overflow-hidden scale-95 translate-y-4 transition-all duration-300" onclick="event.stopPropagation()">
        <!-- Header -->
        <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
          <div class="flex items-center gap-2">
            <div class="w-8 h-8 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center">
              <i data-lucide="plus" class="w-4 h-4 text-indigo-600"></i>
            </div>
            <div>
              <h3 class="text-sm font-semibold text-gray-900">Add Agent</h3>
              <p class="text-[11px] text-gray-500">Connect to a remote Agent backend</p>
            </div>
          </div>
          <button onclick="window.closeAddAgentModal()" class="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition">
            <i data-lucide="x" class="w-4 h-4"></i>
          </button>
        </div>

        <!-- Form -->
        <div class="p-6 space-y-4">
          <div>
            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Agent Name</label>
            <input type="text" id="add-agent-name" placeholder="My Agent" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300">
          </div>
          <div>
            <label class="block text-[11px] font-medium text-gray-400 uppercase mb-1.5">Server URL</label>
            <input type="text" id="add-agent-url" placeholder="http://192.168.1.50:8001" class="w-full text-sm bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 focus:outline-none focus:border-gray-300 focus:bg-white transition-colors placeholder:text-gray-300 font-mono">
          </div>

          <!-- Status message -->
          <div id="add-agent-status" class="hidden text-[12px] px-3 py-2 rounded-lg"></div>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-gray-100 flex items-center justify-between bg-gray-50/50">
          <button onclick="window.testAddAgentConnection()" id="add-agent-test-btn" class="px-4 py-2 text-sm text-gray-600 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 hover:text-gray-800 transition-colors flex items-center gap-1.5">
            <i data-lucide="radio" class="w-3.5 h-3.5"></i>
            Test Connection
          </button>
          <div class="flex items-center gap-2">
            <button onclick="window.closeAddAgentModal()" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors">
              Cancel
            </button>
            <button onclick="window.confirmAddAgent()" id="add-agent-confirm-btn" class="px-5 py-2 text-sm font-medium text-white bg-gray-900 rounded-xl hover:bg-gray-800 transition-colors shadow-sm">
              Add Agent
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
}

// ---- Window functions for modal interaction ----

declare global {
  interface Window {
    openAddAgentModal: () => void;
    closeAddAgentModal: () => void;
    testAddAgentConnection: () => void;
    confirmAddAgent: () => void;
  }
}

window.openAddAgentModal = function () {
  console.log('[AddAgentModal] openAddAgentModal called');
  
  // Remove any existing dynamic modal
  const existingOverlay = document.getElementById('dynamic-agent-modal');
  if (existingOverlay) existingOverlay.remove();

  // Create overlay directly on body to bypass all CSS issues
  const overlay = document.createElement('div');
  overlay.id = 'dynamic-agent-modal';
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  Object.assign(overlay.style, {
    position: 'fixed', inset: '0', zIndex: '99999',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(4px)'
  });

  const card = document.createElement('div');
  Object.assign(card.style, {
    background: 'white', borderRadius: '16px', width: '100%', maxWidth: '420px',
    boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', overflow: 'hidden'
  });
  card.onclick = (e) => e.stopPropagation();

  card.innerHTML = `
    <div style="padding:16px 24px;border-bottom:1px solid #f3f4f6;display:flex;align-items:center;justify-content:space-between;background:#fafafa">
      <div><h3 style="font-size:14px;font-weight:600;color:#111827;margin:0">Add Agent</h3>
      <p style="font-size:11px;color:#6b7280;margin:2px 0 0">Connect to a remote Agent backend</p></div>
      <button id="dam-close" style="padding:6px;color:#9ca3af;cursor:pointer;border:none;background:none;font-size:18px">✕</button>
    </div>
    <div style="padding:24px;display:flex;flex-direction:column;gap:16px">
      <div>
        <label style="display:block;font-size:11px;font-weight:500;color:#9ca3af;text-transform:uppercase;margin-bottom:6px">Agent Name</label>
        <input type="text" id="dam-name" placeholder="My Agent" style="width:100%;font-size:14px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:10px 16px;outline:none;font-family:inherit;box-sizing:border-box">
      </div>
      <div>
        <label style="display:block;font-size:11px;font-weight:500;color:#9ca3af;text-transform:uppercase;margin-bottom:6px">Server URL</label>
        <input type="text" id="dam-url" placeholder="http://192.168.1.50:8001" style="width:100%;font-size:14px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;padding:10px 16px;outline:none;font-family:monospace;box-sizing:border-box">
      </div>
      <div id="dam-status" style="display:none;font-size:12px;padding:8px 12px;border-radius:8px"></div>
    </div>
    <div style="padding:16px 24px;border-top:1px solid #f3f4f6;display:flex;align-items:center;justify-content:space-between;background:#fafafa">
      <button id="dam-test" style="padding:8px 16px;font-size:14px;color:#4b5563;background:white;border:1px solid #e5e7eb;border-radius:12px;cursor:pointer">Test Connection</button>
      <div style="display:flex;gap:8px">
        <button id="dam-cancel" style="padding:8px 16px;font-size:14px;color:#6b7280;border:none;background:none;cursor:pointer">Cancel</button>
        <button id="dam-confirm" style="padding:8px 20px;font-size:14px;font-weight:500;color:white;background:#111827;border:none;border-radius:12px;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,0.05)">Add Agent</button>
      </div>
    </div>
  `;

  overlay.appendChild(card);
  document.body.appendChild(overlay);

  // Wire up buttons
  document.getElementById('dam-close')!.onclick = () => overlay.remove();
  document.getElementById('dam-cancel')!.onclick = () => overlay.remove();
  
  document.getElementById('dam-test')!.onclick = async () => {
    const url = (document.getElementById('dam-url') as HTMLInputElement).value.trim();
    const statusDiv = document.getElementById('dam-status')!;
    if (!url) {
      Object.assign(statusDiv.style, { display: 'block', background: '#fffbeb', color: '#b45309', border: '1px solid #fde68a' });
      statusDiv.textContent = 'Please enter a server URL';
      return;
    }
    const testBtn = document.getElementById('dam-test') as HTMLButtonElement;
    testBtn.textContent = 'Testing...'; testBtn.disabled = true;
    Object.assign(statusDiv.style, { display: 'block', background: '#f9fafb', color: '#6b7280', border: '1px solid #e5e7eb' });
    statusDiv.textContent = 'Testing connection...';
    const result = await testAgentConnection(url);
    if (result.ok) {
      Object.assign(statusDiv.style, { background: '#ecfdf5', color: '#047857', border: '1px solid #a7f3d0' });
      statusDiv.textContent = 'Connected successfully!';
    } else {
      Object.assign(statusDiv.style, { background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca' });
      statusDiv.textContent = 'Failed: ' + result.error;
    }
    testBtn.textContent = 'Test Connection'; testBtn.disabled = false;
  };

  document.getElementById('dam-confirm')!.onclick = async () => {
    const name = (document.getElementById('dam-name') as HTMLInputElement).value.trim();
    const url = (document.getElementById('dam-url') as HTMLInputElement).value.trim();
    const statusDiv = document.getElementById('dam-status')!;
    if (!name || !url) {
      Object.assign(statusDiv.style, { display: 'block', background: '#fffbeb', color: '#b45309', border: '1px solid #fde68a' });
      statusDiv.textContent = 'Please fill in both name and URL';
      return;
    }
    const confirmBtn = document.getElementById('dam-confirm') as HTMLButtonElement;
    confirmBtn.textContent = 'Adding...'; confirmBtn.disabled = true;
    const result = await testAgentConnection(url);
    const entry = addAgent(name, url);
    updateAgentStatus(entry.id, result.ok ? 'active' : 'offline');
    setActiveAgent(entry.id);
    if (typeof (window as any).renderAgentSidebar === 'function') {
      (window as any).renderAgentSidebar();
    }
    overlay.remove();
  };

  (document.getElementById('dam-name') as HTMLInputElement).focus();
};

window.closeAddAgentModal = function () {
  const dynamic = document.getElementById('dynamic-agent-modal');
  if (dynamic) { dynamic.remove(); return; }
  const modal = document.getElementById('add-agent-modal');
  if (modal) modal.remove();
};

window.testAddAgentConnection = async function () {
  const urlInput = document.getElementById('add-agent-url') as HTMLInputElement;
  const statusDiv = document.getElementById('add-agent-status') as HTMLDivElement;
  const testBtn = document.getElementById('add-agent-test-btn') as HTMLButtonElement;

  if (!urlInput || !statusDiv) return;
  const url = urlInput.value.trim();
  if (!url) {
    statusDiv.classList.remove('hidden');
    statusDiv.className = 'text-[12px] px-3 py-2 rounded-lg bg-amber-50 text-amber-700 border border-amber-100';
    statusDiv.innerHTML = 'Please enter a server URL';
    return;
  }

  // Show testing state
  if (testBtn) {
    testBtn.disabled = true;
    testBtn.innerHTML = '<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Testing...';
    if ((window as any).lucide) (window as any).lucide.createIcons();
  }

  statusDiv.classList.remove('hidden');
  statusDiv.className = 'text-[12px] px-3 py-2 rounded-lg bg-gray-50 text-gray-500 border border-gray-200';
  statusDiv.innerHTML = 'Testing connection...';

  const result = await testAgentConnection(url);

  if (result.ok) {
    statusDiv.className = 'text-[12px] px-3 py-2 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-100';
    statusDiv.innerHTML = `<span class="flex items-center gap-1.5"><i data-lucide="check-circle" class="w-3.5 h-3.5"></i> Connected successfully</span>`;
  } else {
    statusDiv.className = 'text-[12px] px-3 py-2 rounded-lg bg-red-50 text-red-700 border border-red-100';
    statusDiv.innerHTML = `<span class="flex items-center gap-1.5"><i data-lucide="x-circle" class="w-3.5 h-3.5"></i> Failed: ${result.error}</span>`;
  }

  if ((window as any).lucide) (window as any).lucide.createIcons();

  if (testBtn) {
    testBtn.disabled = false;
    testBtn.innerHTML = '<i data-lucide="radio" class="w-3.5 h-3.5"></i> Test Connection';
    if ((window as any).lucide) (window as any).lucide.createIcons();
  }
};

window.confirmAddAgent = async function () {
  const nameInput = document.getElementById('add-agent-name') as HTMLInputElement;
  const urlInput = document.getElementById('add-agent-url') as HTMLInputElement;
  const statusDiv = document.getElementById('add-agent-status') as HTMLDivElement;
  const confirmBtn = document.getElementById('add-agent-confirm-btn') as HTMLButtonElement;

  if (!nameInput || !urlInput) return;

  const name = nameInput.value.trim();
  const url = urlInput.value.trim();

  if (!name || !url) {
    if (statusDiv) {
      statusDiv.classList.remove('hidden');
      statusDiv.className = 'text-[12px] px-3 py-2 rounded-lg bg-amber-50 text-amber-700 border border-amber-100';
      statusDiv.innerHTML = 'Please fill in both name and URL';
    }
    return;
  }

  // Show loading on confirm button
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.innerHTML = '<span class="flex items-center gap-1.5"><i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i> Adding...</span>';
    if ((window as any).lucide) (window as any).lucide.createIcons();
  }

  // Test connection first
  const result = await testAgentConnection(url);

  if (!result.ok) {
    // Still add it but warn
    if (statusDiv) {
      statusDiv.classList.remove('hidden');
      statusDiv.className = 'text-[12px] px-3 py-2 rounded-lg bg-amber-50 text-amber-700 border border-amber-100';
      statusDiv.innerHTML = `<span class="flex items-center gap-1.5"><i data-lucide="alert-triangle" class="w-3.5 h-3.5"></i> Cannot reach agent (${result.error}). Adding anyway...</span>`;
      if ((window as any).lucide) (window as any).lucide.createIcons();
    }
  }

  const entry = addAgent(name, url);
  updateAgentStatus(entry.id, result.ok ? 'active' : 'offline');

  // Set as active agent
  setActiveAgent(entry.id);

  // Re-render sidebar
  if (typeof (window as any).renderAgentSidebar === 'function') {
    (window as any).renderAgentSidebar();
  }

  // Close modal
  window.closeAddAgentModal();
};

