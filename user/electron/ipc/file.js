/**
 * File Operations IPC Handler (ESM)
 * Handles reading/writing user ATTP config and key files.
 */

import { ipcMain, app, dialog } from 'electron';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const ATTP_DIR = path.join(os.homedir(), '.attp');
const USER_CONFIG_DIR = path.join(ATTP_DIR, 'user');
const USER_CONFIG_PATH = path.join(USER_CONFIG_DIR, 'config.json');
const APP_STATE_PATH = path.join(ATTP_DIR, 'app-state.json');

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * 解析打包/开发态下的演示资源路径。
 * 打包后资源在 process.resourcesPath；开发态回退到仓库 examples/。
 */
function resolveResource(rel) {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, rel);
  }
  // user/electron/ipc/ -> user/electron/ -> user/ -> 仓库根
  return path.join(__dirname, '..', '..', '..', rel);
}

const DEMO_USER_DIR = () => resolveResource(
  app.isPackaged ? 'demo-user' : path.join('examples', '.attp', 'user')
);
const COMPOSE_PATH = () => resolveResource(
  app.isPackaged ? 'docker-compose.yml' : 'docker-compose.yml'
);

/** 递归复制目录 */
function copyDir(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

/** 递归删除目录 */
function rmDir(target) {
  if (fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: true });
}

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

/** Default user config（自由模式空白默认；mode 由 app-state 管，不在此） */
function getDefaultConfig() {
  return {
    did: '',
    didDocPath: '~/.attp/user/did/did.json',
    didKeyPath: '~/.attp/user/did/key-1_private.pem',
    protocolNodes: [],
    toolNodes: [],
    agents: [],
  };
}

/** 默认 LLM 配置（持久于 app-state.llm，两模式共用） */
function getDefaultLlm() {
  return { apiKey: '', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat' };
}

function getDefaultAppState() {
  return { mode: null, llm: getDefaultLlm() };
}

/** 读 ~/.attp/app-state.json（缺则默认） */
function readAppState() {
  try {
    if (fs.existsSync(APP_STATE_PATH)) {
      const data = JSON.parse(fs.readFileSync(APP_STATE_PATH, 'utf-8'));
      return {
        mode: data.mode ?? null,
        llm: { ...getDefaultLlm(), ...(data.llm || {}) },
      };
    }
  } catch (e) { /* fallthrough */ }
  return getDefaultAppState();
}

/** 写 ~/.attp/app-state.json */
function writeAppState(state) {
  if (!fs.existsSync(ATTP_DIR)) fs.mkdirSync(ATTP_DIR, { recursive: true });
  fs.writeFileSync(APP_STATE_PATH, JSON.stringify(state, null, 2), 'utf-8');
}

/** 演示模式：读内置 demo-user/config.json，并把 ~/.attp/user 路径改写为 demo 目录绝对路径 */
function resolveDemoUserConfig() {
  const demoDir = DEMO_USER_DIR();
  const cfgPath = path.join(demoDir, 'config.json');
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
  const rewrite = (p) => {
    if (typeof p !== 'string') return p;
    const prefix = '~/.attp/user';
    if (p.startsWith(prefix)) return path.join(demoDir, p.slice(prefix.length));
    return p;
  };
  if (cfg.didDocPath) cfg.didDocPath = rewrite(cfg.didDocPath);
  if (cfg.didKeyPath) cfg.didKeyPath = rewrite(cfg.didKeyPath);
  return cfg;
}

/** 自由模式：读 ~/.attp/user/config.json（缺则默认） */
function resolveFreeUserConfig() {
  if (fs.existsSync(USER_CONFIG_PATH)) {
    try {
      const data = JSON.parse(fs.readFileSync(USER_CONFIG_PATH, 'utf-8'));
      return { ...getDefaultConfig(), ...data };
    } catch (e) { /* fallthrough to default */ }
  }
  return getDefaultConfig();
}

/** 组装完整 app-state 响应（mode + llm + userConfig + needsInit） */
function buildStateResponse() {
  const state = readAppState();
  const needsInit = state.mode !== 'demo' && state.mode !== 'free';
  let userConfig = null;
  if (state.mode === 'demo') {
    try { userConfig = resolveDemoUserConfig(); } catch (e) { /* demo 资源缺失 */ }
  } else if (state.mode === 'free') {
    userConfig = resolveFreeUserConfig();
  }
  if (userConfig) userConfig.mode = state.mode;
  return { ok: true, mode: state.mode, llm: state.llm, userConfig, needsInit };
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

  // ---- 读应用运行态（mode + llm + 按模式分流的 userConfig）----
  ipcMain.handle('read-app-state', async () => {
    try {
      return buildStateResponse();
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- 设置模式（演示↔自由双向切换）----
  // demo：仅写 mode（直接读 resources，不复制）。
  // free：写 mode；若 ~/.attp/user/config.json 缺则建空默认。
  ipcMain.handle('set-app-mode', async (_event, mode) => {
    try {
      if (mode !== 'demo' && mode !== 'free') {
        return { ok: false, error: `未知模式: ${mode}` };
      }
      const state = readAppState();
      state.mode = mode;
      writeAppState(state);
      if (mode === 'free' && !fs.existsSync(USER_CONFIG_PATH)) {
        ensureConfigDir();
        fs.writeFileSync(USER_CONFIG_PATH, JSON.stringify(getDefaultConfig(), null, 2), 'utf-8');
      }
      return buildStateResponse();
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- 保存 LLM 配置（持久于 app-state.llm）----
  ipcMain.handle('save-llm', async (_event, llm) => {
    try {
      const state = readAppState();
      state.llm = { ...getDefaultLlm(), ...(llm || {}) };
      writeAppState(state);
      return { ok: true, data: state.llm };
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- Save user ATTP config（仅自由模式；演示模式只读拒绝）----
  ipcMain.handle('save-user-config', async (_event, config) => {
    try {
      const { mode } = readAppState();
      if (mode === 'demo') {
        return { ok: false, error: '演示模式为只读，请先切换到自由配置模式' };
      }
      ensureConfigDir();
      // mode 字段由 app-state 管，不写入 user config
      const { mode: _m, ...rest } = config || {};
      fs.writeFileSync(USER_CONFIG_PATH, JSON.stringify(rest, null, 2), 'utf-8');
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  });

  // ---- 执行 docker compose 动作（pull/up/down/logs），流式回传输出 + 注入 LLM env ----
  // env（可选）：{LLM_API_KEY, LLM_BASE_URL, LLM_MODEL}，优先于 cwd 的 .env 文件。
  ipcMain.handle('docker-compose', async (event, action, env) => {
    const composeFile = COMPOSE_PATH();
    if (!fs.existsSync(composeFile)) {
      return { ok: false, error: `docker-compose.yml 未找到: ${composeFile}` };
    }
    const composeDir = path.dirname(composeFile);
    const args = ['compose', '-f', composeFile];
    switch (action) {
      case 'pull': args.push('pull'); break;
      case 'up': args.push('up', '-d'); if (!app.isPackaged) args.push('--build'); break;
      case 'down': args.push('down'); break;
      case 'logs': args.push('logs', '--tail=200'); break;
      default: return { ok: false, error: `未知动作: ${action}` };
    }
    // 仅注入非空 env 值，否则回落 docker compose 自身对 .env 的读取
    const cleanEnv = { ...process.env };
    for (const [k, v] of Object.entries(env || {})) {
      if (v !== undefined && v !== null && String(v) !== '') cleanEnv[k] = String(v);
    }
    return new Promise((resolve) => {
      let child;
      try {
        child = spawn('docker', args, { cwd: composeDir, env: cleanEnv });
      } catch (e) {
        resolve({ ok: false, error: `无法启动 docker：${e.message || e}` });
        return;
      }
      const send = (chunk) => {
        const text = chunk.toString();
        event.sender.send('docker-compose-output', text);
      };
      child.stdout.on('data', send);
      child.stderr.on('data', send);
      child.on('error', (e) => {
        const msg = e.code === 'ENOENT'
          ? '未检测到 docker，请先安装 Docker，或使用离线镜像包（docker load）。'
          : (e.message || String(e));
        event.sender.send('docker-compose-output', `\n[错误] ${msg}\n`);
        resolve({ ok: false, error: msg });
      });
      child.on('close', (code) => {
        resolve({ ok: code === 0, code });
      });
    });
  });

  // ---- 导入离线镜像包（GitHub Release tarball）----
  ipcMain.handle('load-images-tarball', async (event) => {
    const res = await dialog.showOpenDialog({
      title: '选择 ATTP 镜像包',
      filters: [{ name: '镜像包', extensions: ['tar', 'gz'] }],
      properties: ['openFile'],
    });
    if (res.canceled || !res.filePaths.length) {
      return { ok: false, canceled: true };
    }
    const file = res.filePaths[0];
    event.sender.send('docker-compose-output', `\n▶ docker load -i ${file}\n`);
    return new Promise((resolve) => {
      let child;
      try {
        child = spawn('docker', ['load', '-i', file]);
      } catch (e) {
        resolve({ ok: false, error: `无法启动 docker：${e.message || e}` });
        return;
      }
      const send = (chunk) => event.sender.send('docker-compose-output', chunk.toString());
      child.stdout.on('data', send);
      child.stderr.on('data', send);
      child.on('error', (e) => {
        const msg = e.code === 'ENOENT'
          ? '未检测到 docker，请先安装 Docker。'
          : (e.message || String(e));
        event.sender.send('docker-compose-output', `\n[错误] ${msg}\n`);
        resolve({ ok: false, error: msg });
      });
      child.on('close', (code) => resolve({ ok: code === 0, code }));
    });
  });

  // ---- Get home directory ----
  ipcMain.handle('get-home-dir', async () => {
    return os.homedir();
  });
}