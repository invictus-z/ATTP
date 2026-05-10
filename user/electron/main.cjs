/**
 * Electron Main Process Entry
 * Handles app lifecycle, window creation, and IPC registration.
 */

const { app, BrowserWindow } = require('electron');
const path = require('path');
const { registerIpcHandlers, closeAllConnections } = require('./ipc');

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

app.whenReady().then(() => {
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