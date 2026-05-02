/**
 * Agent Manager — manages multiple agent backends.
 * Each agent has its own baseUrl, WebSocket connection, and session context.
 */

export interface AgentEntry {
  id: string;
  name: string;
  baseUrl: string;       // e.g. "http://192.168.1.50:8001"
  status: 'active' | 'offline' | 'connecting';
}

const STORAGE_KEY = 'nanobot_agents';

// ---- Registry ----

let agents: AgentEntry[] = [];
let activeAgentId: string | null = null;
let onAgentSwitchCallbacks: Array<() => void> = [];

export function getAgents(): AgentEntry[] {
  return agents;
}

export function getActiveAgent(): AgentEntry | null {
  if (!activeAgentId) return null;
  return agents.find(a => a.id === activeAgentId) || null;
}

export function getActiveAgentId(): string | null {
  return activeAgentId;
}

export function getActiveAgentUrl(): string {
  const agent = getActiveAgent();
  return agent ? agent.baseUrl : '';
}

/** Build a full API URL for the given active agent path, e.g. /api/status */
export function apiUrl(path: string): string {
  const agent = getActiveAgent();
  if (!agent) return path;
  const base = agent.baseUrl.replace(/\/+$/, '');
  return `${base}${path}`;
}

/** Build a full WebSocket URL for the given active agent path, e.g. /ws */
export function wsUrl(path: string): string {
  const agent = getActiveAgent();
  if (!agent) return '';
  const base = agent.baseUrl.replace(/\/+$/, '');
  // replace http(s) with ws(s)
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}${path}`;
}

export function setActiveAgent(id: string): void {
  if (agents.find(a => a.id === id)) {
    activeAgentId = id;
    localStorage.setItem('nanobot_active_agent', id);
    // Notify all listeners
    onAgentSwitchCallbacks.forEach(cb => cb());
  }
}

export function onAgentSwitch(callback: () => void): void {
  onAgentSwitchCallbacks.push(callback);
}

export function addAgent(name: string, baseUrl: string): AgentEntry {
  // Ensure no trailing slash
  baseUrl = baseUrl.replace(/\/+$/, '');

  const id = 'agent_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6);
  const entry: AgentEntry = {
    id,
    name,
    baseUrl,
    status: 'offline',
  };
  agents.push(entry);
  persist();
  return entry;
}

export function removeAgent(id: string): void {
  agents = agents.filter(a => a.id !== id);
  if (activeAgentId === id) {
    activeAgentId = agents.length > 0 ? agents[0].id : null;
    localStorage.setItem('nanobot_active_agent', activeAgentId || '');
    if (activeAgentId) {
      onAgentSwitchCallbacks.forEach(cb => cb());
    }
  }
  persist();
}

export function updateAgentStatus(id: string, status: AgentEntry['status']): void {
  const agent = agents.find(a => a.id === id);
  if (agent) {
    agent.status = status;
    persist();
  }
}

export function renameAgent(id: string, newName: string): void {
  const agent = agents.find(a => a.id === id);
  if (agent) {
    agent.name = newName;
    persist();
  }
}

/** Test connectivity to an agent by hitting /api/status */
export async function testAgentConnection(baseUrl: string): Promise<{ ok: boolean; data?: any; error?: string }> {
  try {
    const url = baseUrl.replace(/\/+$/, '') + '/api/status';
    const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const data = await res.json();
    return { ok: true, data };
  } catch (e: any) {
    return { ok: false, error: e.message || 'Connection failed' };
  }
}

// ---- Persistence ----

function persist(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(agents));
}

export function loadAgents(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      agents = JSON.parse(raw);
    }
  } catch {
    agents = [];
  }

  // Restore active agent
  const savedId = localStorage.getItem('nanobot_active_agent');
  if (savedId && agents.find(a => a.id === savedId)) {
    activeAgentId = savedId;
  } else if (agents.length > 0) {
    activeAgentId = agents[0].id;
  }

  // Refresh all agent statuses on load
  agents.forEach(agent => {
    testAgentConnection(agent.baseUrl).then(result => {
      updateAgentStatus(agent.id, result.ok ? 'active' : 'offline');
      // Re-render sidebar if status changed
      if (typeof (window as any).renderAgentSidebar === 'function') {
        (window as any).renderAgentSidebar();
      }
    });
  });
}