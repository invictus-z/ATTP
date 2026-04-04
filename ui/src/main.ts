import { setupChatLogic } from './chat_logic';
import './style.css';
import { renderSidebar } from './components/Sidebar';
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

app.innerHTML = `
  ${renderSidebar()}
  
  <main class="flex-1 flex flex-col relative h-full bg-surface" id="main-content">
    ${renderHomeView()}
    ${renderNodeView()}
    ${renderSessionsView()}
    ${renderSettingsView()}
  </main>
  
  ${renderModals()}
`;

// Initialize logic
setupLogic();
setupChatLogic();

// Import and run lucide icons if it's available globally or inject script
const script = document.createElement('script');
script.src = "https://unpkg.com/lucide@latest";
script.onload = () => {
    if (window.lucide) {
        window.lucide.createIcons();
    }
};
document.head.appendChild(script);

