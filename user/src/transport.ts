/**
 * Transport Layer — Renderer Process
 * Provides a unified API for HTTP and WebSocket communication,
 * routing all requests through Electron IPC (via window.electronAPI).
 */

// ---- User ATTP Config ----

export interface UserAttpConfig {
  did: string;
  didDocPath: string;
  didKeyPath: string;
  defaultTargetDid: string;
  protocolUrls: string[];
  agents: { name: string; baseUrl: string }[];
}

interface IpcFileResult {
  ok: boolean;
  data?: string;
  error?: string;
}

interface IpcUserConfigResult {
  ok: boolean;
  data?: UserAttpConfig;
  error?: string;
}

declare global {
  interface Window {
    electronAPI: {
      platform: string;
      isElectron: boolean;
      request: (url: string, options?: RequestOptions) => Promise<IpcHttpResponse>;
      wsConnect: (url: string) => Promise<IpcWsConnectResult>;
      wsSend: (id: string, data: any) => void;
      wsClose: (id: string) => Promise<{ ok: boolean }>;
      onWsMessage: (cb: (data: WsEventData) => void) => void;
      onWsOpen: (cb: (data: WsEventBasic) => void) => void;
      onWsClose: (cb: (data: WsCloseEvent) => void) => void;
      onWsError: (cb: (data: WsErrorEvent) => void) => void;
      readFile: (filepath: string) => Promise<IpcFileResult>;
      readUserConfig: () => Promise<IpcUserConfigResult>;
      saveUserConfig: (config: UserAttpConfig) => Promise<IpcFileResult>;
      getHomeDir: () => Promise<string>;
    };
  }
}

// ---- Types ----

interface RequestOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}

interface IpcHttpResponse {
  ok: boolean;
  status: number;
  data: any;
  error?: string;
}

interface IpcWsConnectResult {
  ok: boolean;
  id?: string;
  error?: string;
}

interface WsEventData {
  id: string;
  data: any;
}

interface WsEventBasic {
  id: string;
  url?: string;
}

interface WsCloseEvent {
  id: string;
  code: number;
  reason: string;
}

interface WsErrorEvent {
  id: string;
  error: string;
}

// ---- HTTP ----

export interface ApiResponse {
  ok: boolean;
  status: number;
  data: any;
  error?: string;
}

/**
 * Perform an HTTP request through Electron IPC.
 * Usage: apiFetch('http://localhost:8001/api/status')
 *        apiFetch('http://localhost:8001/api/config', { method: 'PUT', body: JSON.stringify(payload) })
 */
export async function apiFetch(url: string, options?: RequestOptions): Promise<ApiResponse> {
  const result = await window.electronAPI.request(url, options);
  if (result.error) {
    return { ok: false, status: result.status, data: null, error: result.error };
  }
  return result;
}

// ---- WebSocket ----

export interface WsConnection {
  readonly id: string;
  send: (data: any) => void;
  close: () => Promise<void>;
}

type WsMessageHandler = (data: any) => void;
type WsEventHandler = () => void;
type WsErrorHandler = (error: string) => void;

// Global listener state (registered once)
let wsListenersRegistered = false;
const wsMessageHandlers = new Map<string, Set<WsMessageHandler>>();
const wsOpenHandlers = new Map<string, Set<WsEventHandler>>();
const wsCloseHandlers = new Map<string, Set<WsEventHandler>>();
const wsErrorHandlers = new Map<string, Set<WsErrorHandler>>();

function ensureWsListeners() {
  if (wsListenersRegistered) return;
  wsListenersRegistered = true;

  window.electronAPI.onWsMessage((event: WsEventData) => {
    const handlers = wsMessageHandlers.get(event.id);
    if (handlers) handlers.forEach(cb => cb(event.data));
  });

  window.electronAPI.onWsOpen((event: WsEventBasic) => {
    const handlers = wsOpenHandlers.get(event.id);
    if (handlers) handlers.forEach(cb => cb());
  });

  window.electronAPI.onWsClose((event: WsCloseEvent) => {
    const handlers = wsCloseHandlers.get(event.id);
    if (handlers) handlers.forEach(cb => cb());
    // Cleanup handlers on close
    wsMessageHandlers.delete(event.id);
    wsOpenHandlers.delete(event.id);
    wsCloseHandlers.delete(event.id);
    wsErrorHandlers.delete(event.id);
  });

  window.electronAPI.onWsError((event: WsErrorEvent) => {
    const handlers = wsErrorHandlers.get(event.id);
    if (handlers) handlers.forEach(cb => cb(event.error));
  });
}

/**
 * Create a WebSocket connection through Electron IPC.
 * Returns a WsConnection object with send/close methods and event registration.
 *
 * Usage:
 *   const conn = await createWs('ws://localhost:8001/ws');
 *   conn.onMessage(data => { ... });
 *   conn.send({ type: 'chat', content: 'hello' });
 *   await conn.close();
 */
export async function createWs(url: string): Promise<WsConnection> {
  ensureWsListeners();

  const result = await window.electronAPI.wsConnect(url);

  if (!result.ok || !result.id) {
    throw new Error(result.error || 'Failed to create WebSocket connection');
  }

  const id = result.id;

  return {
    id,
    send(data: any) {
      window.electronAPI.wsSend(id, data);
    },
    async close() {
      await window.electronAPI.wsClose(id);
      wsMessageHandlers.delete(id);
      wsOpenHandlers.delete(id);
      wsCloseHandlers.delete(id);
      wsErrorHandlers.delete(id);
    },
  };
}

/**
 * Register a message handler for a WsConnection.
 */
export function onWsMessage(conn: WsConnection, handler: WsMessageHandler) {
  if (!wsMessageHandlers.has(conn.id)) wsMessageHandlers.set(conn.id, new Set());
  wsMessageHandlers.get(conn.id)!.add(handler);
}

/**
 * Register an open handler for a WsConnection.
 */
export function onWsOpen(conn: WsConnection, handler: WsEventHandler) {
  if (!wsOpenHandlers.has(conn.id)) wsOpenHandlers.set(conn.id, new Set());
  wsOpenHandlers.get(conn.id)!.add(handler);
}

/**
 * Register a close handler for a WsConnection.
 */
export function onWsClose(conn: WsConnection, handler: WsEventHandler) {
  if (!wsCloseHandlers.has(conn.id)) wsCloseHandlers.set(conn.id, new Set());
  wsCloseHandlers.get(conn.id)!.add(handler);
}

/**
 * Register an error handler for a WsConnection.
 */
export function onWsError(conn: WsConnection, handler: WsErrorHandler) {
  if (!wsErrorHandlers.has(conn.id)) wsErrorHandlers.set(conn.id, new Set());
  wsErrorHandlers.get(conn.id)!.add(handler);
}