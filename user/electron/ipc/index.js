/**
 * IPC Handler Registry (ESM)
 */

import { registerHttpHandlers } from './http.js';
import { registerWsHandlers, closeAllConnections } from './websocket.js';

export function registerIpcHandlers(mainWindow) {
  registerHttpHandlers();
  registerWsHandlers(mainWindow);
}

export { closeAllConnections };