/**
 * HTTP Proxy IPC Handler (ESM)
 */

import { ipcMain } from 'electron';

export function registerHttpHandlers() {
  ipcMain.handle('http-request', async (_event, { url, options }) => {
    const method = (options?.method || 'GET').toUpperCase();
    const headers = options?.headers || {};
    const body = options?.body;

    console.log(`[DEBUG-CONN][HTTP] >>> ${method} ${url}`);
    if (Object.keys(headers).length > 0) {
      console.log(`[DEBUG-CONN][HTTP]     Headers:`, JSON.stringify(headers));
    }
    if (body) {
      const bodyPreview = typeof body === 'string' ? body.slice(0, 200) : String(body).slice(0, 200);
      console.log(`[DEBUG-CONN][HTTP]     Body (${typeof body}, ${typeof body === 'string' ? body.length : '?'} chars): ${bodyPreview}`);
    }

    try {
      const fetchOptions = { method, headers };
      if (body && method !== 'GET' && method !== 'HEAD') {
        fetchOptions.body = body;
      }

      const res = await fetch(url, fetchOptions);
      const contentType = res.headers.get('content-type') || '';

      console.log(`[DEBUG-CONN][HTTP] <<< ${method} ${url} → HTTP ${res.status} (${contentType || 'no content-type'})`);

      let data;
      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = await res.text();
      }

      const dataPreview = typeof data === 'string' ? data.slice(0, 300) : JSON.stringify(data).slice(0, 300);
      console.log(`[DEBUG-CONN][HTTP]     Data preview: ${dataPreview}`);

      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      console.error(`[DEBUG-CONN][HTTP] !!! ${method} ${url} → ERROR: ${e.message || String(e)}`);
      console.error(`[DEBUG-CONN][HTTP]     Error stack:`, e.stack || 'no stack');
      return { ok: false, status: 0, data: null, error: e.message || String(e) };
    }
  });
}
