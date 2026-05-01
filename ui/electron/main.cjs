const { app, BrowserWindow } = require('electron');
const path = require('path');

// 判断是否为开发模式
const isDev = !app.isPackaged;

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'Nanobot Agent Workspace',
    icon: path.join(__dirname, '../public/icon.png'), // 可选：添加应用图标
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true,
    },
  });

  if (isDev) {
    // 开发模式：加载 Vite dev server（代理 /api -> localhost:8001）
    mainWindow.loadURL('http://localhost:5173');
  } else {
    // 生产模式：直接加载 Python 后端 serve 的 Web UI
    // 需要先启动 Python 后端（uvicorn），它会 serve 静态文件
    mainWindow.loadURL('http://localhost:8001');
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
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
  if (process.platform !== 'darwin') {
    app.quit();
  }
});