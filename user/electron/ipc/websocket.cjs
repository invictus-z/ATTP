/**
 * WebSocket Proxy IPC Handler
 * Manages WebSocket connections from the renderer process via IPC.
 * The main process holds the actual WebSocket instances and relays
 * messages back to the renderer through webContents.send().
 */

const { ipcMain } = require('electron');
const WebSocket = require('ws');

// Active WebSocket connections: id -> { ws, url }
const connections = new Map();
let nextId = 1;

function registerWsHandlers(mainWindow) {
  // --- Create a new WebSocket connection ---
  ipcMain.handle('ws-create', (event, url) => {
    return new Promise((resolve) => {
      const id = String(nextId++);

      try {
        const ws = new WebSocket(url);

        ws.on('open', () => {
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-open', { id, url });
          }
          resolve({ ok: true, id });
        });

        ws.on('message', (data) => {
          if (!mainWindow.isDestroyed()) {
            let payload;
            if (typeof data === 'string') {
              try { payload = JSON.parse(data); } catch { payload = data; }
            } else {
              payload = data.toString();
            }
            mainWindow.webContents.send('ws-message', { id, data: payload });
          }
        });

        ws.on('close', (code, reason) => {
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-close-event', {
              id,
              code,
              reason: reason.toString(),
            });
          }
          connections.delete(id);
        });

        ws.on('error', (err) => {
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-error', { id, error: err.message });
          }
          connections.delete(id);
        });

        connections.set(id, { ws, url });
      } catch (e) {
        resolve({ ok: false, error: e.message || String(e) });
      }
    });
  });

  // --- Send data through a WebSocket connection ---
  ipcMain.on('ws-send', (_, { id, data }) => {
    const conn = connections.get(id);
    if (conn && conn.ws.readyState === WebSocket.OPEN) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      conn.ws.send(payload);
    }
  });

  // --- Close a WebSocket connection ---
  ipcMain.handle('ws-close', (_, id) => {
    const conn = connections.get(id);
    if (conn) {
      conn.ws.close();
      connections.delete(id);
    }
    return { ok: true };
  });
}

/**
 * Close all active WebSocket connections (e.g. on window close).
 */
function closeAllConnections() {
  for (const [id, conn] of connections) {
    try { conn.ws.close(); } catch {}
    connections.delete(id);
  }
}

module.exports = { registerWsHandlers, closeAllConnections };