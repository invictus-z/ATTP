/**
 * HTTP Proxy IPC Handler
 * Handles all HTTP requests from the renderer process via IPC.
 */

const { ipcMain } = require('electron');

function registerHttpHandlers() {
  ipcMain.handle('http-request', async (_, { url, options }) => {
    try {
      const fetchOptions = {
        method: options?.method || 'GET',
        headers: options?.headers || {},
      };

      if (options?.body) {
        fetchOptions.body = options.body;
      }

      const res = await fetch(url, fetchOptions);

      let data;
      const contentType = res.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = await res.text();
      }

      return {
        ok: res.ok,
        status: res.status,
        data: data,
      };
    } catch (e) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: e.message || String(e),
      };
    }
  });
}

module.exports = { registerHttpHandlers };