/**
 * IPC Handler Registry
 * Registers all IPC handlers for the main process.
 */

const { registerHttpHandlers } = require('./http');
const { registerWsHandlers, closeAllConnections } = require('./websocket');

/**
 * Register all IPC handlers for the given BrowserWindow.
 * @param {import('electron').BrowserWindow} mainWindow
 */
function registerIpcHandlers(mainWindow) {
  registerHttpHandlers();
  registerWsHandlers(mainWindow);
}

module.exports = { registerIpcHandlers, closeAllConnections };