import { setupChatLogic } from './chat_logic';
import './style.css';
import { loadAgents } from './agent_manager';
import { renderSidebar, setupAddAgentButton } from './components/Sidebar';
import { renderAddAgentModal } from './components/AddAgentModal';
import { renderModals } from './components/Modals';
import { renderHomeView } from './views/HomeView';
import { renderNodeView } from './views/NodeView';
import { renderSessionsView } from './views/SessionsView';
import { renderSettingsView } from './views/SettingsView';
import { setupLogic } from './logic';

declare global {
  interface Window { lucide: any; }
}

const app = document.querySelector<HTMLDivElement>('#app')!;

// Load persisted agents first
loadAgents();

app.innerHTML = `
  ${renderSidebar()}
  
  <main class="flex-1 flex flex-col relative h-full bg-surface" id="main-content">
    ${renderHomeView()}
    ${renderNodeView()}
    ${renderSessionsView()}
    ${renderSettingsView()}
  </main>
  
  ${renderModals()}
  ${renderAddAgentModal()}
`;

// Initialize logic
setupLogic();
setupChatLogic();

// Render agent sidebar list
if (typeof (window as any).renderAgentSidebar === 'function') {
  (window as any).renderAgentSidebar();
}

// Setup the '+' button after DOM is ready
setupAddAgentButton();

// Global click delegation for add-agent buttons (survives re-renders)
document.addEventListener('click', (e) => {
  const target = e.target as HTMLElement;
  const addAgentBtn = target.closest('[data-action="open-add-agent"]');
  if (addAgentBtn) {
    e.preventDefault();
    e.stopPropagation();
    if (typeof (window as any).openAddAgentModal === 'function') {
      (window as any).openAddAgentModal();
    } else {
      // Fallback: direct DOM manipulation
      const m = document.getElementById('add-agent-modal');
      if (m) { m.classList.remove('hidden', 'opacity-0'); m.classList.add('flex'); }
    }
  }
});

// Import and run lucide icons if it's available globally or inject script
const script = document.createElement('script');
script.src = "https://unpkg.com/lucide@latest";
script.onload = () => {
    if (window.lucide) {
        window.lucide.createIcons();
    }
};
document.head.appendChild(script);

