/**
 * Agent Manager — manages multiple agent backends.
 * Each agent has its own baseUrl, WebSocket connection, and session context.
 */

import { ref } from 'vue';
import { apiFetch, type UserAttpConfig } from './transport';

export interface AgentEntry {
  id: string;
  name: string;
  baseUrl: string;       // e.g. "http://192.168.1.50:8001"
  did?: string;          // Agent 的 DID 身份（如 did:wba:host:agent-name）
  status: 'active' | 'offline' | 'connecting';
}

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
  if (!agent) {
    console.warn(`[DEBUG-CONN][apiUrl] No active agent — returning raw path: ${path}`);
    return path;
  }
  const base = agent.baseUrl.replace(/\/+$/, '');
  const fullUrl = `${base}${path}`;
  console.log(`[DEBUG-CONN][apiUrl] agent="${agent.name}" baseUrl="${agent.baseUrl}" → ${fullUrl}`);
  return fullUrl;
}

/** Build a full WebSocket URL for the given active agent path, e.g. /ws */
export function wsUrl(path: string): string {
  const agent = getActiveAgent();
  if (!agent) {
    console.warn(`[DEBUG-CONN][wsUrl] No active agent — returning empty`);
    return '';
  }
  return wsUrlForAgent(agent, path);
}

/** Build a full WebSocket URL for a specific agent */
export function wsUrlForAgent(agent: AgentEntry, path: string): string {
  const base = agent.baseUrl.replace(/\/+$/, '');
  const wsBase = base.replace(/^http/, 'ws');
  const fullUrl = `${wsBase}${path}`;
  console.log(`[DEBUG-CONN][wsUrlForAgent] agent="${agent.name}" baseUrl="${agent.baseUrl}" → wsUrl="${fullUrl}"`);
  return fullUrl;
}

export function setActiveAgent(id: string): void {
  if (agents.value.find(a => a.id === id)) {
    activeAgentId.value = id;
    localStorage.setItem('attp_active_agent', id);
    // Notify all listeners
    onAgentSwitchCallbacks.forEach(cb => cb());
  }
}

export function onAgentSwitch(callback: () => void): void {
  onAgentSwitchCallbacks.push(callback);
}

export function addAgent(name: string, baseUrl: string, did?: string): AgentEntry {
  // Ensure no trailing slash
  baseUrl = baseUrl.replace(/\/+$/, '');

  const id = 'agent_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6);
  const entry: AgentEntry = {
    id,
    name,
    baseUrl,
    did: did || '',
    status: 'offline',
  };
  agents.value.push(entry);
  persist();

  // Auto-activate if this is the first agent or no active agent
  if (!activeAgentId.value) {
    activeAgentId.value = id;
    localStorage.setItem('attp_active_agent', id);
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
    localStorage.setItem('attp_active_agent', activeAgentId.value || '');
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
  const url = baseUrl.replace(/\/+$/, '') + '/api/status';
  console.log(`[DEBUG-CONN][testAgent] Testing connection → ${url}`);
  try {
    const result = await apiFetch(url);
    if (!result.ok) {
      console.warn(`[DEBUG-CONN][testAgent] ✗ ${url} → FAIL: HTTP ${result.status}, error="${result.error}"`);
      return { ok: false, error: `HTTP ${result.status}` };
    }
    console.log(`[DEBUG-CONN][testAgent] ✓ ${url} → OK, data=`, result.data);
    return { ok: true, data: result.data };
  } catch (e: any) {
    console.error(`[DEBUG-CONN][testAgent] !!! ${url} → EXCEPTION: ${e.message || e}`);
    return { ok: false, error: e.message || 'Connection failed' };
  }
}

// ---- Persistence ----

async function persist(): Promise<void> {
  try {
    const state = await window.electronAPI.readAppState();
    const config: UserAttpConfig = state.ok && state.userConfig
      ? { ...state.userConfig }
      : { did: '', didDocPath: '', didKeyPath: '', protocolNodes: [], toolNodes: [], agents: [] };
    // Deep-clone to strip Vue reactive proxies (not serializable through Electron IPC)
    config.agents = JSON.parse(JSON.stringify(agents.value.map(a => ({ name: a.name, baseUrl: a.baseUrl, did: a.did }))));
    await window.electronAPI.saveUserConfig(JSON.parse(JSON.stringify(config)));
  } catch (e) {
    console.error('[AgentManager] persist failed:', e);
  }
}

export async function loadAgents(): Promise<void> {
  console.log('[DEBUG-CONN][loadAgents] Loading agents from user config...');
  try {
    const state = await window.electronAPI.readAppState();
    console.log('[DEBUG-CONN][loadAgents] readAppState result:', state.ok ? 'OK' : 'FAIL', state.error || '');
    if (state.ok && state.userConfig?.agents) {
      agents.value = state.userConfig.agents.map((a: any, i: number) => ({
        id: 'agent_' + i + '_' + a.baseUrl.replace(/[^a-zA-Z0-9]/g, '_'),
        name: a.name,
        baseUrl: a.baseUrl,
        did: a.did || '',
        status: 'offline' as const,
      }));
      console.log(`[DEBUG-CONN][loadAgents] Loaded ${agents.value.length} agent(s):`);
      agents.value.forEach(a => {
        console.log(`[DEBUG-CONN][loadAgents]   - "${a.name}" id=${a.id} baseUrl="${a.baseUrl}" did="${a.did}"`);
      });
    } else {
      console.warn('[DEBUG-CONN][loadAgents] No agents found in config (data.agents empty or missing)');
    }
  } catch (e) {
    console.error('[DEBUG-CONN][loadAgents] Exception:', e);
    agents.value = [];
  }

  // Restore active agent
  if (agents.value.length > 0) {
    activeAgentId.value = agents.value[0].id;
    console.log(`[DEBUG-CONN][loadAgents] Active agent set to: ${activeAgentId.value} ("${agents.value[0].name}")`);
  } else {
    console.warn('[DEBUG-CONN][loadAgents] No agents available — active agent is null');
  }

  // Refresh all agent statuses on load
  agents.value.forEach(agent => {
    testAgentConnection(agent.baseUrl).then(result => {
      updateAgentStatus(agent.id, result.ok ? 'active' : 'offline');
    });
  });
}
