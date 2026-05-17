/**
 * File Operations IPC Handler (ESM)
 * Handles reading/writing user ATTP config and key files.
 */

import { ipcMain } from 'electron';
import fs from 'fs';
import path from 'path';
import os from 'os';

const USER_CONFIG_DIR = path.join(os.homedir(), '.attp', 'user');
const USER_CONFIG_PATH = path.join(USER_CONFIG_DIR, 'config.json');

/** Expand ~ to home directory */
function expandHome(filepath) {
  if (filepath.startsWith('~')) {
    return path.join(os.homedir(), filepath.slice(1));
  }
  return filepath;
}

/** Ensure user config directory exists */
function ensureConfigDir() {
  if (!fs.existsSync(USER_CONFIG_DIR)) {
    fs.mkdirSync(USER_CONFIG_DIR, { recursive: true });
  }
}

/** Default user config */
function getDefaultConfig() {
  return {
    did: '',
    didDocPath: '~/.attp/user/did/did.json',
    didKeyPath: '~/.attp/user/did/key-1_private.pem',
    defaultTargetDid: '',
    protocolUrls: [],
    agents: [],
  };
}

export function registerFileHandlers() {

  // ---- Read arbitrary file (PEM keys, DID docs, etc.) ----
  ipcMain.handle('read-file', async (_event, filepath) => {
    try {
      const resolved = expandHome(filepath);
      const content = fs.readFileSync(resolved, 'utf-8');
      return { ok: true, data: content };
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- Read user ATTP config ----
  ipcMain.handle('read-user-config', async () => {
    try {
      ensureConfigDir();
      if (!fs.existsSync(USER_CONFIG_PATH)) {
        const defaultConfig = getDefaultConfig();
        fs.writeFileSync(USER_CONFIG_PATH, JSON.stringify(defaultConfig, null, 2), 'utf-8');
        return { ok: true, data: defaultConfig };
      }
      const raw = fs.readFileSync(USER_CONFIG_PATH, 'utf-8');
      const data = JSON.parse(raw);
      // Merge with defaults for any missing fields
      const defaults = getDefaultConfig();
      const merged = { ...defaults, ...data };
      return { ok: true, data: merged };
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- Save user ATTP config ----
  ipcMain.handle('save-user-config', async (_event, config) => {
    try {
      ensureConfigDir();
      const content = JSON.stringify(config, null, 2);
      fs.writeFileSync(USER_CONFIG_PATH, content, 'utf-8');
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- Get home directory ----
  ipcMain.handle('get-home-dir', async () => {
    return os.homedir();
  });
}