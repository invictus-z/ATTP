/**
 * HTTP Proxy IPC Handler (ESM)
 */

import { ipcMain } from 'electron';

export function registerHttpHandlers() {
  ipcMain.handle('http-request', async (_event, { url, options }) => {
    const method = (options?.method || 'GET').toUpperCase();
    const headers = options?.headers || {};
    const body = options?.body;

    try {
      const fetchOptions = { method, headers };
      if (body && method !== 'GET' && method !== 'HEAD') {
        fetchOptions.body = body;
      }

      const res = await fetch(url, fetchOptions);

      let data;
      const contentType = res.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = await res.text();
      }

      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      return { ok: false, status: 0, data: null, error: e.message || String(e) };
    }
  });
}