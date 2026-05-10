/**
 * WebSocket Proxy IPC Handler (ESM)
 */

import { ipcMain } from 'electron';
import WebSocket from 'ws';

const connections = new Map();
let nextId = 1;

export function registerWsHandlers(mainWindow) {
  ipcMain.handle('ws-create', (event, url) => {
    return new Promise((resolve) => {
      const id = String(nextId++);
      let resolved = false;

      try {
        const ws = new WebSocket(url);

        ws.on('open', () => {
          resolved = true;
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-open', { id, url });
          }
          resolve({ ok: true, id });
        });

        ws.on('message', (rawData) => {
          if (!mainWindow.isDestroyed()) {
            let payload;
            try {
              const str = typeof rawData === 'string' ? rawData : rawData.toString();
              payload = JSON.parse(str);
            } catch {
              payload = typeof rawData === 'string' ? rawData : rawData.toString();
            }
            mainWindow.webContents.send('ws-message', { id, data: payload });
          }
        });

        ws.on('close', (code, reason) => {
          if (!resolved) {
            resolved = true;
            resolve({ ok: false, error: `Connection closed before open (code: ${code})` });
          }
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
          if (!resolved) {
            resolved = true;
            resolve({ ok: false, error: err.message || 'WebSocket connection error' });
          }
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-error', { id, error: err.message });
          }
          connections.delete(id);
        });

        connections.set(id, { ws, url });
      } catch (e) {
        if (!resolved) {
          resolved = true;
          resolve({ ok: false, error: e.message || String(e) });
        }
      }
    });
  });

  ipcMain.on('ws-send', (_, { id, data }) => {
    const conn = connections.get(id);
    if (conn && conn.ws.readyState === WebSocket.OPEN) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      conn.ws.send(payload);
    }
  });

  ipcMain.handle('ws-close', (_, id) => {
    const conn = connections.get(id);
    if (conn) {
      conn.ws.close();
      connections.delete(id);
    }
    return { ok: true };
  });
}

export function closeAllConnections() {
  for (const [id, conn] of connections) {
    try { conn.ws.close(); } catch {}
    connections.delete(id);
  }
}