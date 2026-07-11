/**
 * SSE (Server-Sent Events) Proxy IPC Handler (ESM)
 *
 * 镜像 websocket.js：向协议节点 /api/events 发起长连接 HTTP 流，
 * 解析 SSE 帧并把事件转发给渲染进程。使用 Node 22 全局 fetch + ReadableStream，
 * 无需额外 npm 依赖。
 */

import { ipcMain } from 'electron';

const connections = new Map();  // id -> { controller, url }
let nextId = 1;

export function registerSseHandlers(mainWindow) {
  ipcMain.handle('sse-create', async (_event, url) => {
    const id = String(nextId++);
    const controller = new AbortController();
    console.log(`[DEBUG-CONN][SSE] >>> Creating SSE #${id} → ${url}`);

    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { Accept: 'text/event-stream' },
      });
      if (!response.ok || !response.body) {
        const err = `HTTP ${response.status}`;
        console.error(`[DEBUG-CONN][SSE] ✗ Failed #${id} → ${url}: ${err}`);
        return { ok: false, error: err };
      }

      connections.set(id, { controller, url });
      if (!mainWindow.isDestroyed()) {
        mainWindow.webContents.send('sse-open', { id, url });
      }
      console.log(`[DEBUG-CONN][SSE] ✓ Opened #${id} → ${url}`);

      // 后台读取循环：解析帧并转发
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      (async () => {
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            // 帧以空行分隔
            let idx;
            while ((idx = buffer.indexOf('\n\n')) >= 0) {
              const frame = buffer.slice(0, idx);
              buffer = buffer.slice(idx + 2);
              const parsed = parseSseFrame(frame);
              if (parsed && !mainWindow.isDestroyed()) {
                mainWindow.webContents.send('sse-event', { id, ...parsed });
              }
            }
          }
        } catch (e) {
          if (e.name !== 'AbortError') {
            console.error(`[DEBUG-CONN][SSE] !!! Read error #${id}: ${e.message}`);
          }
        } finally {
          if (!mainWindow.isDestroyed()) {
            mainWindow.webContents.send('sse-close-event', { id });
          }
          connections.delete(id);
        }
      })();

      return { ok: true, id };
    } catch (e) {
      console.error(`[DEBUG-CONN][SSE] !!! Create error #${id} → ${url}: ${e.message}`);
      connections.delete(id);
      return { ok: false, error: e.message || String(e) };
    }
  });

  ipcMain.handle('sse-close', (_, id) => {
    const conn = connections.get(id);
    if (conn) {
      console.log(`[DEBUG-CONN][SSE] Closing #${id} → ${conn.url}`);
      try { conn.controller.abort(); } catch {}
      connections.delete(id);
    }
    return { ok: true };
  });
}

/**
 * 解析单个 SSE 帧（不含尾部空行）。
 * 返回 { eventId, event, data } 或 null（注释/空帧）。
 */
function parseSseFrame(frame) {
  let id = null;
  let event = null;
  const dataLines = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue;  // 注释 / 心跳
    if (line.startsWith('id:')) {
      id = line.slice(3).trim();
    } else if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      // SSE 规范：data: 后可选单个前导空格
      dataLines.push(line.slice(5).replace(/^ /, ''));
    }
  }
  if (id === null && event === null && dataLines.length === 0) return null;
  let data = dataLines.length > 0 ? dataLines.join('\n') : null;
  if (data) {
    try { data = JSON.parse(data); } catch { /* 保留字符串 */ }
  }
  return { eventId: id, event, data };
}

export function closeAllSseConnections() {
  for (const [id, conn] of connections) {
    try { conn.controller.abort(); } catch {}
    connections.delete(id);
  }
}
