/**
 * IPC Handler Registry (ESM)
 */

import { registerHttpHandlers } from './http.js';
import { registerWsHandlers, closeAllConnections as closeAllWs } from './websocket.js';
import { registerSseHandlers, closeAllSseConnections } from './sse.js';
import { registerFileHandlers } from './file.js';

export function registerIpcHandlers(mainWindow) {
  registerHttpHandlers();
  registerWsHandlers(mainWindow);
  registerSseHandlers(mainWindow);
  registerFileHandlers();
}

export function closeAllConnections() {
  closeAllWs();
  closeAllSseConnections();
}
