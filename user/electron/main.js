/**
 * Electron Main Process Entry (ESM)
 * Handles app lifecycle, window creation, and IPC registration.
 */

import { app, BrowserWindow, Menu, session } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import { registerIpcHandlers, closeAllConnections } from './ipc/index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'Nanobot Agent Workspace',
    icon: path.join(__dirname, '../public/icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // Dev mode: load from Vite dev server; Prod: load built files
  const isDev = process.argv.includes('--dev') || process.env.NODE_ENV === 'development';
  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    closeAllConnections();
    mainWindow = null;
  });

  // Register all IPC handlers (HTTP proxy, WebSocket proxy)
  registerIpcHandlers(mainWindow);
}

// CSP 经响应头下发：frame-ancestors 等指令无法经 <meta> 生效，必须走 header（Electron 官方推荐）
const CSP = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none';";

app.whenReady().then(() => {
  // 去除顶部默认菜单栏
  Menu.setApplicationMenu(null);

  // 仅对顶层文档注入 CSP（非文档响应上的 CSP 头会被浏览器忽略，过滤掉避免无谓开销）
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    if (details.responseHeaders && details.resourceType === 'mainFrame') {
      callback({
        responseHeaders: { ...details.responseHeaders, 'Content-Security-Policy': [CSP] },
      });
    } else {
      callback({});
    }
  });

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  closeAllConnections();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});