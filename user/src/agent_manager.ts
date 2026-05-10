/**
 * Agent Manager — manages multiple agent backends.
 * Each agent has its own baseUrl, WebSocket connection, and session context.
 */

import { ref } from 'vue';
import { apiFetch } from './transport';

export interface AgentEntry {
  id: string;
  name: string;
  baseUrl: string;       // e.g. "http://192.168.1.50:8001"
  status: 'active' | 'offline' | 'connecting';
}

const STORAGE_KEY = 'nanobot_agents';

// ---- Registry (reactive) ----

const agents = ref<AgentEntry[]>([]);
const activeAgentId = ref<string | null>(null);
let onAgentSwitchCallbacks: Array<() => void> = [];

export function getAgents(): AgentEntry[] {
  return agents.value;
}

export function getActiveAgent(): AgentEntry | null {
  if (!activeAgentId.value) return null;
  return agents.value.find(a => a.id === activeAgentId.value) || null;
}

export function getActiveAgentId(): string | null {
  return activeAgentId.value;
}

export function getAgentById(id: string): AgentEntry | null {
  return agents.value.find(a => a.id === id) || null;
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
  return agent ? wsUrlForAgent(agent, path) : '';
}

/** Build a full WebSocket URL for a specific agent */
export function wsUrlForAgent(agent: AgentEntry, path: string): string {
  const base = agent.baseUrl.replace(/\/+$/, '');
  const wsBase = base.replace(/^http/, 'ws');
  return `${wsBase}${path}`;
}

export function setActiveAgent(id: string): void {
  if (agents.value.find(a => a.id === id)) {
    activeAgentId.value = id;
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
  agents.value.push(entry);
  persist();

  // Auto-activate if this is the first agent or no active agent
  if (!activeAgentId.value) {
    activeAgentId.value = id;
    localStorage.setItem('nanobot_active_agent', id);
    onAgentSwitchCallbacks.forEach(cb => cb());
  }

  // Test connectivity
  testAgentConnection(entry.baseUrl).then(result => {
    updateAgentStatus(entry.id, result.ok ? 'active' : 'offline');
  });

  return entry;
}

export function removeAgent(id: string): void {
  agents.value = agents.value.filter(a => a.id !== id);
  if (activeAgentId.value === id) {
    activeAgentId.value = agents.value.length > 0 ? agents.value[0].id : null;
    localStorage.setItem('nanobot_active_agent', activeAgentId.value || '');
    if (activeAgentId.value) {
      onAgentSwitchCallbacks.forEach(cb => cb());
    }
  }
  persist();
}

export function updateAgentStatus(id: string, status: AgentEntry['status']): void {
  const agent = agents.value.find(a => a.id === id);
  if (agent) {
    agent.status = status;
    persist();
  }
}

export function renameAgent(id: string, newName: string): void {
  const agent = agents.value.find(a => a.id === id);
  if (agent) {
    agent.name = newName;
    persist();
  }
}

/** Test connectivity to an agent by hitting /api/status via IPC */
export async function testAgentConnection(baseUrl: string): Promise<{ ok: boolean; data?: any; error?: string }> {
  try {
    const url = baseUrl.replace(/\/+$/, '') + '/api/status';
    const result = await apiFetch(url);
    if (!result.ok) {
      return { ok: false, error: `HTTP ${result.status}` };
    }
    return { ok: true, data: result.data };
  } catch (e: any) {
    return { ok: false, error: e.message || 'Connection failed' };
  }
}

// ---- Persistence ----

function persist(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(agents.value));
}

export function loadAgents(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      agents.value = JSON.parse(raw);
    }
  } catch {
    agents.value = [];
  }

  // Restore active agent
  const savedId = localStorage.getItem('nanobot_active_agent');
  if (savedId && agents.value.find(a => a.id === savedId)) {
    activeAgentId.value = savedId;
  } else if (agents.value.length > 0) {
    activeAgentId.value = agents.value[0].id;
  }

  // Refresh all agent statuses on load
  agents.value.forEach(agent => {
    testAgentConnection(agent.baseUrl).then(result => {
      updateAgentStatus(agent.id, result.ok ? 'active' : 'offline');
    });
  });
}