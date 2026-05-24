/**
 * IPC Handler Registry (ESM)
 */

import { registerHttpHandlers } from './http.js';
import { registerWsHandlers, closeAllConnections } from './websocket.js';
import { registerFileHandlers } from './file.js';

export function registerIpcHandlers(mainWindow) {
  registerHttpHandlers();
  registerWsHandlers(mainWindow);
  registerFileHandlers();
}

export { closeAllConnections };