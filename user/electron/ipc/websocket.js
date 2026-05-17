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

      console.log(`[DEBUG-CONN][WS] >>> Creating WebSocket #${id} → ${url}`);

      try {
        const ws = new WebSocket(url);

        ws.on('open', () => {
          console.log(`[DEBUG-CONN][WS] ✓ Opened #${id} → ${url}`);
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
            const preview = typeof payload === 'string' ? payload.slice(0, 150) : JSON.stringify(payload).slice(0, 150);
            console.log(`[DEBUG-CONN][WS] ← Message #${id}: ${preview}`);
            mainWindow.webContents.send('ws-message', { id, data: payload });
          }
        });

        ws.on('close', (code, reason) => {
          const reasonStr = reason.toString();
          console.warn(`[DEBUG-CONN][WS] ✗ Closed #${id} (code=${code}, reason="${reasonStr}") → ${connections.get(id)?.url || url}`);
          if (!resolved) {
            resolved = true;
            resolve({ ok: false, error: `Connection closed before open (code: ${code})` });
          }
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('ws-close-event', {
              id,
              code,
              reason: reasonStr,
            });
          }
          connections.delete(id);
        });

        ws.on('error', (err) => {
          console.error(`[DEBUG-CONN][WS] !!! Error #${id} → ${url}: ${err.message}`);
          console.error(`[DEBUG-CONN][WS]     Error stack:`, err.stack || 'no stack');
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
        console.log(`[DEBUG-CONN][WS]     Pending #${id} — awaiting open... (total connections: ${connections.size})`);
      } catch (e) {
        console.error(`[DEBUG-CONN][WS] !!! Sync error creating #${id} → ${url}: ${e.message || String(e)}`);
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
      const preview = payload.slice(0, 150);
      console.log(`[DEBUG-CONN][WS] → Send #${id} (${payload.length} chars): ${preview}`);
      conn.ws.send(payload);
    } else {
      console.warn(`[DEBUG-CONN][WS] ⚠ Send attempted on #${id} but readyState=${conn?.ws?.readyState} (not OPEN). Connection exists: ${!!conn}`);
    }
  });

  ipcMain.handle('ws-close', (_, id) => {
    const conn = connections.get(id);
    if (conn) {
      console.log(`[DEBUG-CONN][WS] Closing #${id} → ${conn.url}`);
      conn.ws.close();
      connections.delete(id);
    } else {
      console.warn(`[DEBUG-CONN][WS] Close attempted on unknown #${id}`);
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