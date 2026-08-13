/**
 * Electron Preload Script
 * Exposes a safe IPC bridge API to the renderer process via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,

  // ---- HTTP Proxy ----
  request: (url, options) => ipcRenderer.invoke('http-request', { url, options }),

  // ---- WebSocket Proxy ----
  wsConnect: (url) => ipcRenderer.invoke('ws-create', url),
  wsSend: (id, data) => ipcRenderer.send('ws-send', { id, data }),
  wsClose: (id) => ipcRenderer.invoke('ws-close', id),

  // ---- WebSocket Event Listeners ----
  onWsMessage: (callback) => {
    ipcRenderer.on('ws-message', (_, data) => callback(data));
  },
  onWsOpen: (callback) => {
    ipcRenderer.on('ws-open', (_, data) => callback(data));
  },
  onWsClose: (callback) => {
    ipcRenderer.on('ws-close-event', (_, data) => callback(data));
  },
  onWsError: (callback) => {
    ipcRenderer.on('ws-error', (_, data) => callback(data));
  },

  // ---- SSE Proxy ----
  sseConnect: (url) => ipcRenderer.invoke('sse-create', url),
  sseClose: (id) => ipcRenderer.invoke('sse-close', id),

  // ---- SSE Event Listeners ----
  onSseEvent: (callback) => {
    ipcRenderer.on('sse-event', (_, data) => callback(data));
  },
  onSseOpen: (callback) => {
    ipcRenderer.on('sse-open', (_, data) => callback(data));
  },
  onSseClose: (callback) => {
    ipcRenderer.on('sse-close-event', (_, data) => callback(data));
  },

  // ---- File Operations ----
  readFile: (filepath) => ipcRenderer.invoke('read-file', filepath),
  readUserConfig: () => ipcRenderer.invoke('read-user-config'),
  saveUserConfig: (config) => ipcRenderer.invoke('save-user-config', config),
  getHomeDir: () => ipcRenderer.invoke('get-home-dir'),
});
