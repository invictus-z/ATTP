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

  // ---- File Operations ----
  readFile: (filepath) => ipcRenderer.invoke('read-file', filepath),
  saveUserConfig: (config) => ipcRenderer.invoke('save-user-config', config),
  getHomeDir: () => ipcRenderer.invoke('get-home-dir'),

  // ---- 应用运行态 / 模式切换 / LLM / 后端编排 ----
  readAppState: () => ipcRenderer.invoke('read-app-state'),
  setAppMode: (mode) => ipcRenderer.invoke('set-app-mode', mode),
  saveLlm: (llm) => ipcRenderer.invoke('save-llm', llm),
  dockerCompose: (action, env) => ipcRenderer.invoke('docker-compose', action, env),
  loadImagesTarball: () => ipcRenderer.invoke('load-images-tarball'),
  onDockerComposeOutput: (callback) => {
    const handler = (_, data) => callback(data);
    ipcRenderer.on('docker-compose-output', handler);
    return () => ipcRenderer.removeListener('docker-compose-output', handler);
  },
});
