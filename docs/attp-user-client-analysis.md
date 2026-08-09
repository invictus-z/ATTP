# ATTP 用户端（User Client / 谛听工作区）代码与功能分析

> 本文档对 `user/` 目录下的所有模块进行全面的代码结构与功能分析，内容对齐 `dev` 分支当前代码（UI 标注版本 `v0.2.0-alpha.2`，包版本 `0.2.0-alpha.1.demo`）。
>
> 协议全称：**Agent Trust and Traceability Protocol（ATTP）**；产品名：**谛听（Diting）**——融合大模型意图追踪的可溯源智能体互联协议。本文档不再使用旧称 "Agent Trust Trace Protocol"。

## 目录

- [1. 概述](#1-概述)
- [2. 模块架构总览](#2-模块架构总览)
- [3. Electron 主进程层](#3-electron-主进程层)
- [4. 传输层 — transport.ts](#4-传输层--transportts)
- [5. ATTP 协议层](#5-attp-协议层)
- [6. Composables 业务逻辑层](#6-composables-业务逻辑层)
- [7. Agent 管理器 — agent_manager.ts](#7-agent-管理器--agent_managerts)
- [8. 视图层](#8-视图层)
- [9. SSE 事件订阅与分析流程（v0.3.0 逐跳模型）](#9-sse-事件订阅与分析流程v030-逐跳模型)
- [10. 核心数据流](#10-核心数据流)
- [11. 设计模式与总结](#11-设计模式与总结)

---

## 1. 概述

谛听用户端是 ATTP 网络中**用户侧**的桌面客户端应用，基于 **Vue 3 + Electron** 构建。它为用户提供了与 ATTP 网络中多个 Agent 交互的统一界面，完整实现了 ATTP 协议的消息签名、溯源链回传，并对接协议节点的**逐跳（per-hop）意图追踪与横向累积分析**能力，以 SSE 实时推送分析进度。

> 分支说明：`dev` 分支**未**实现端到端加密 / 统一传输安全层（E2EE/TLS）。本文档不把它们描述为已实现特性。

### 核心能力

| 能力 | 说明 |
|------|------|
| **多 Agent 管理** | 同时连接多个 Agent 后端，独立会话上下文，WS 连接按 URL 去重复用 |
| **ATTP 协议通信** | U2A/A2U 消息签名 + 双轮回传（BackMessage → Protocol Node `/record`） |
| **多曲线密钥支持** | RSA / ECDSA P-256/384/521 / secp256k1 / Ed25519 五类曲线 |
| **SSE 实时事件** | 三路 SSE 常驻/按需订阅：全局告警、分析进度、行为链生长 |
| **逐跳意图追踪** | 纵向（session 级）逐跳评分 + 意图流；横向（DID 级）F 累积 + 确认裁决 |
| **十字锁定综合视图** | 一跳纵轴评分 × 各 DID 横轴 F 累积的全景聚合 |
| **恶意节点档案** | 跨来源（协议审查 / 纵 / 横分析）的档案与违规明细 |
| **工具节点管理** | 工具节点 CRUD、探活检测、ad.json 服务描述查询 |
| **Electron 桌面应用** | HTTP/WS/SSE IPC 代理绕过 CORS、本地文件读写、跨平台打包 |

### 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | ^3.5 | 前端 UI 框架 |
| Vue Router 4 | ^4.6 | 客户端路由（Hash 模式） |
| Electron | ^35.2 | 桌面应用壳 |
| Vite | ^5.0 | 构建工具 |
| TypeScript | ^5.2 | 类型系统 |
| Tailwind CSS | ^3.4 | 样式框架 |
| @noble/curves | ^2.2 | 多曲线密码学（secp256k1, Ed25519） |
| @noble/secp256k1 | ^3.1 | secp256k1 签名 |
| @noble/hashes | ^2.2 | 哈希工具 |
| ws | ^8.18 | 主进程 WebSocket（代理实现） |
| marked + highlight.js | ^18 / ^11 | Markdown 渲染 + 代码高亮 |
| DOMPurify | ^3.4 | HTML 安全过滤 |
| lucide-vue-next | ^1.0 | 图标库 |
| electron-store | ^11 | 打包期辅助（构建配置） |

> 注：SSE 代理不依赖任何 npm 包——直接使用 Node 22 全局 `fetch` + `ReadableStream` 解析 SSE 帧。

---

## 2. 模块架构总览

### 2.1 目录结构

```
user/
├── package.json              # 项目配置与依赖（name: attp-user）
├── index.html                # Vite 入口 HTML
├── vite.config.ts            # Vite 构建配置
├── tsconfig.json             # TypeScript 配置
├── tailwind.config.js        # Tailwind CSS 配置
├── postcss.config.js         # PostCSS 配置
├── electron/                 # Electron 主进程（ESM）
│   ├── main.js               # 应用入口、窗口创建、生命周期
│   ├── preload.cjs           # 安全桥接（contextBridge：HTTP/WS/SSE/File）
│   └── ipc/
│       ├── index.js          # IPC 注册中心（聚合 HTTP/WS/SSE/File）
│       ├── http.js           # HTTP 请求代理（fetch）
│       ├── websocket.js      # WebSocket 代理（ws 库 + 连接池）
│       ├── sse.js            # SSE 代理（fetch 流 + 帧解析）【新增】
│       └── file.js           # 文件 I/O（配置/密钥读写）
└── src/
    ├── main.ts               # Vue 应用入口
    ├── App.vue               # 根组件（侧边栏 + 路由视图 + 全局告警 toast）
    ├── router.ts             # 路由定义（Hash 模式，trace 子路由铺平）
    ├── style.css             # 全局样式
    ├── markdown.ts           # Markdown 渲染工具
    ├── transport.ts          # 统一通信层（HTTP + WS + SSE via IPC）
    ├── agent_manager.ts      # 多 Agent 注册/切换/状态管理
    ├── attp/
    │   ├── key_helper.ts     # PEM 密钥导入（多曲线）
    │   └── protocol.ts       # ATTP 消息构造、签名、回传
    ├── composables/
    │   ├── useAttpProtocol.ts # ATTP 协议核心逻辑（身份/密钥/收发）
    │   ├── useChat.ts         # 聊天会话 + WS 管理
    │   ├── useNodes.ts        # Agent 发现的对端节点列表
    │   ├── useSettings.ts     # 活跃 Agent 配置 CRUD
    │   ├── useProtocolNodes.ts # 协议节点共享单例（CRUD + 选中态）【新增】
    │   ├── useAnalysisFlow.ts # 引导式分析流程状态机（SSE 推送）【新增】
    │   ├── nodeEvents.ts      # 全局告警常驻 SSE（record/malicious）【新增】
    │   ├── useTraceFormat.ts  # 溯源徽章/格式化/链路转换工具【新增】
    │   └── useToast.ts        # 轻量 toast 状态（悬停暂停）【新增】
    ├── components/
    │   ├── FlowDiagram.vue   # 流程图组件
    │   └── TraceModal.vue    # 溯源弹窗组件
    ├── views/
    │   ├── HomeView.vue      # 对话主页（溯源节点绑定）
    │   ├── SessionsView.vue  # 会话历史列表
    │   ├── SettingsView.vue  # 活跃 Agent 配置编辑器
    │   ├── ToolView.vue      # 工具节点管理
    │   ├── NodeView.vue      # 对端节点详情（消息收发）
    │   ├── UserConfigView.vue # 用户 ATTP 身份配置
    │   └── trace/            # 溯源模块（拆分为多个子视图）【重构】
    │       ├── types.ts                  # 共享类型（逐跳改版）
    │       ├── NodeManageView.vue        # 协议节点 CRUD + 探活
    │       ├── TraceQueryView.vue        # 纵/横向溯源查询（主视图）
    │       ├── MaliciousView.vue         # 恶意节点档案 + 违规明细
    │       ├── CrossLockView.vue         # 十字锁定综合视图【新增】
    │       └── components/
    │           ├── NodeSelector.vue       # 协议节点下拉选择器（共享单例）
    │           ├── BehaviorChain.vue      # 行为溯源链路（按 hop/节点分组）
    │           ├── AnalysisReportCard.vue # 横向分析报告卡片
    │           ├── AnalysisStatusBar.vue  # 分析状态条（触发/刷新/状态文案）
    │           ├── HopScoreCard.vue       # 单跳评分卡片（4 维 + severity）
    │           ├── FProgress.vue          # 横向 F 累积进度（Σ s² vs R_S）
    │           └── DimRadar.vue           # 4 维峰值雷达图
    └── env.d.ts / shims-vue.d.ts          # 类型声明
```

### 2.2 分层架构

```
┌────────────────────────────────────────────────────────────────┐
│                     Electron 主进程层                          │
│  main.js · preload.cjs · ipc/{http,websocket,sse,file}.js     │
│  职责：窗口管理、HTTP/WS/SSE IPC 代理、文件系统访问            │
└──────────────────────────┬─────────────────────────────────────┘
                           │ contextBridge IPC
┌──────────────────────────┴─────────────────────────────────────┐
│                    传输层 (transport.ts)                       │
│  apiFetch() · createWs() · createSse()                         │
│  onWsMessage/Open/Close/Error · onSseEvent/Open/Close          │
│  职责：统一 HTTP/WS/SSE 通信 API，封装 IPC 调用细节            │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────┴─────────────────────────────────────┐
│                   ATTP 协议层 (attp/)                          │
│  key_helper.ts · protocol.ts                                   │
│  职责：密钥导入/签名、NodeMessage 构建、BackMessage 回传       │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────┴─────────────────────────────────────┐
│                Composables 业务逻辑层                          │
│  useAttpProtocol · useChat · useNodes · useSettings            │
│  useProtocolNodes · useAnalysisFlow · nodeEvents               │
│  useTraceFormat · useToast                                     │
│  职责：协议会话、聊天、节点、配置、SSE 事件、分析状态机        │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────┴─────────────────────────────────────┐
│                Agent 管理器 (agent_manager.ts)                 │
│  职责：多 Agent 注册表、活跃切换、连接状态、持久化             │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────┴─────────────────────────────────────┐
│                  视图层 (views/*.vue)                          │
│  对话 · 会话历史 · 配置 · 溯源(4 子视图) · 工具 · 用户配置     │
│  职责：UI 展示、用户交互、页面路由                              │
└────────────────────────────────────────────────────────────────┘
```

### 2.3 路由结构

```typescript
{ path: '/',             redirect: '/home' }
{ path: '/home',          name: 'home',          component: HomeView }          // 对话主页
{ path: '/node/:index?',  name: 'node',          component: NodeView }          // 对端节点详情
{ path: '/sessions',      name: 'sessions',      component: SessionsView }      // 会话历史
{ path: '/settings',      name: 'settings',      component: SettingsView }      // Agent 配置
{ path: '/trace',         redirect: to => ({ path: '/trace/query', query: to.query }) }
{ path: '/trace/nodes',     name: 'trace-nodes',     component: NodeManageView }   // 协议节点管理
{ path: '/trace/query',     name: 'trace-query',     component: TraceQueryView }   // 溯源查询（纵/横）
{ path: '/trace/malicious', name: 'trace-malicious', component: MaliciousView }    // 恶意报告
{ path: '/trace/cross-lock', name: 'trace-cross-lock', component: CrossLockView }  // 十字锁定（不在侧栏）
{ path: '/tools',          name: 'tools',          component: ToolView }          // 工具管理
{ path: '/user-config',    name: 'user-config',    component: UserConfigView }    // 用户配置
```

`/trace` 重定向到 `/trace/query` 并保留 query 参数（来自 SessionsView 的"溯源"跳转直达查询页）。`router.afterEach` 在进入 `settings` 时派发 `load-settings` 自定义事件，触发 `SettingsView` 重新加载配置。

---

## 3. Electron 主进程层

### 3.1 应用入口 — `electron/main.js`（ESM，64 行）

负责窗口创建和生命周期管理。所有 IPC Handler 在窗口创建后注册。

#### 窗口配置

```javascript
mainWindow = new BrowserWindow({
  width: 1280, height: 800,
  minWidth: 900, minHeight: 600,
  title: 'Nanobot Agent Workspace',
  icon: path.join(__dirname, '../public/icon.png'),
  webPreferences: {
    preload: path.join(__dirname, 'preload.cjs'),
    nodeIntegration: false,       // 禁用 Node 集成
    contextIsolation: true,       // 启用上下文隔离
  },
})
```

#### 开发/生产模式切换

| 模式 | 加载方式 | 判断条件 |
|------|---------|---------|
| 开发 | `loadURL('http://localhost:5173')` + `openDevTools()` | `--dev` 参数或 `NODE_ENV=development` |
| 生产 | `loadFile('../dist/index.html')` | 默认 |

#### 生命周期

- **`whenReady`**：创建窗口 + 注册 IPC Handler
- **`activate`**（macOS）：重建窗口
- **`window-all-closed`**：`closeAllConnections()`（关闭全部 WS + SSE 连接）+ 退出应用（非 macOS）
- **窗口 `closed`**：同样调用 `closeAllConnections()` 并置 `mainWindow = null`

`closeAllConnections()` 由 `ipc/index.js` 导出，内部聚合 `closeAllWs()` + `closeAllSseConnections()`。

### 3.2 安全桥接 — `electron/preload.cjs`（54 行）

通过 `contextBridge.exposeInMainWorld` 暴露安全的 IPC API：

```javascript
window.electronAPI = {
  // 属性
  platform, isElectron,

  // HTTP 代理
  request(url, options) → ipcRenderer.invoke('http-request', { url, options }),

  // WebSocket 代理
  wsConnect(url)       → ipcRenderer.invoke('ws-create', url),
  wsSend(id, data)     → ipcRenderer.send('ws-send', { id, data }),   // 单向 send
  wsClose(id)          → ipcRenderer.invoke('ws-close', id),
  onWsMessage(cb) / onWsOpen(cb) / onWsClose(cb) / onWsError(cb)
    → ipcRenderer.on('ws-message' | 'ws-open' | 'ws-close-event' | 'ws-error', ...),

  // SSE 代理【新增】
  sseConnect(url)      → ipcRenderer.invoke('sse-create', url),
  sseClose(id)         → ipcRenderer.invoke('sse-close', id),
  onSseEvent(cb) / onSseOpen(cb) / onSseClose(cb)
    → ipcRenderer.on('sse-event' | 'sse-open' | 'sse-close-event', ...),

  // 文件操作
  readFile(filepath)       → ipcRenderer.invoke('read-file', filepath),
  readUserConfig()         → ipcRenderer.invoke('read-user-config'),
  saveUserConfig(config)   → ipcRenderer.invoke('save-user-config', config),
  getHomeDir()             → ipcRenderer.invoke('get-home-dir'),
}
```

### 3.3 HTTP 代理 — `ipc/http.js`（50 行）

渲染进程的 HTTP 请求通过 IPC 转发到主进程 `fetch`，**绕过浏览器 CORS**：

```javascript
ipcMain.handle('http-request', async (_event, { url, options }) => {
  const res = await fetch(url, { method, headers, body })
  // 按 content-type 解析 JSON 或 text
  return { ok: res.ok, status: res.status, data, error? }
})
```

所有 Agent API 调用、协议节点回传（`/record`）、溯源/分析查询均经此代理。Handler 内置 `[DEBUG-CONN][HTTP]` 级别日志，便于调试连接问题。

### 3.4 WebSocket 代理 — `ipc/websocket.js`（118 行）

主进程维护 WS 连接池，事件桥接到渲染进程。

#### 连接管理

```javascript
const connections = new Map()  // id → { ws, url }
let nextId = 1                  // 自增连接 ID
```

#### IPC 通道

| IPC 通道 | 方向 | 功能 |
|---------|------|------|
| `ws-create` | 渲染→主 | 创建 WS（返回连接 ID；连接超时/被关时 resolve `{ ok:false }`） |
| `ws-send` | 渲染→主 | 发送消息（单向 `send`，非 `invoke`） |
| `ws-close` | 渲染→主 | 关闭连接 |
| `ws-message` | 主→渲染 | 消息到达（自动 JSON 解析，失败则透传字符串） |
| `ws-open` | 主→渲染 | 连接建立 |
| `ws-close-event` | 主→渲染 | 连接关闭（含 code + reason） |
| `ws-error` | 主→渲染 | 错误（含 error.message） |

`ws-create` 以 Promise 形式等待 `open` 事件；若连接在 open 前就 close/error，则 resolve `{ ok:false, error }`，避免渲染进程无限挂起。每次操作前都会检查 `mainWindow.isDestroyed()`，防止窗口关闭后发送。

#### 连接清理

`closeAllConnections()` 遍历并关闭所有活跃 WS 连接（窗口关闭时调用）。

### 3.5 SSE 代理 — `ipc/sse.js`（122 行，新增）

镜像 `websocket.js`：对协议节点 `/api/events` 发起长连接 HTTP 流，解析 SSE 帧并转发给渲染进程。**无额外 npm 依赖**——使用 Node 22 全局 `fetch` + `response.body.getReader()`。

#### 连接管理

```javascript
const connections = new Map()  // id → { controller: AbortController, url }
let nextId = 1
```

#### IPC 通道

| IPC 通道 | 方向 | 功能 |
|---------|------|------|
| `sse-create` | 渲染→主 | 发起 SSE 流（`Accept: text/event-stream`），返回连接 ID |
| `sse-close` | 渲染→主 | `controller.abort()` 终止流 |
| `sse-event` | 主→渲染 | 单帧事件（`{ id, eventId?, event, data }`） |
| `sse-open` | 主→渲染 | 流建立 |
| `sse-close-event` | 主→渲染 | 流结束（含正常 EOF / abort） |

#### 帧解析 — `parseSseFrame(frame)`

按 SSE 规范解析单个帧（不含尾部空行分隔符）：

- `:` 开头 → 注释/心跳，跳过
- `id:` → eventId
- `event:` → event 名
- `data:` → 数据行（去掉单个可选前导空格，多行以 `\n` 拼接）

`data` 字段会尝试 `JSON.parse`，失败则保留原始字符串。帧以 `\n\n` 分隔，跨 chunk 的半帧会被缓冲到下一个 read。

### 3.6 文件 I/O — `ipc/file.js`（89 行）

提供本地文件系统访问，主要读取密钥文件和持久化用户配置。

#### 配置文件路径

```
~/.attp/user/config.json
```

#### 默认配置结构（`getDefaultConfig()`）

```json
{
  "did": "",
  "didDocPath": "~/.attp/user/did/did.json",
  "didKeyPath": "~/.attp/user/did/key-1_private.pem",
  "protocolNodes": [],
  "agents": []
}
```

> 注意：默认种子配置**不含** `toolNodes` 字段，但 `UserAttpConfig` 类型与 `ToolView` 仍支持该字段——用户在「工具管理」页添加工具节点后会写入此字段。

#### IPC 通道

| IPC 通道 | 功能 | 说明 |
|---------|------|------|
| `read-file` | 读取任意文件 | 支持 `~` 路径展开，用于读取 PEM 密钥 |
| `read-user-config` | 读取用户配置 | 文件不存在时写默认配置；读取后与默认值浅合并缺失字段 |
| `save-user-config` | 保存用户配置 | JSON 格式化写入，自动建目录 |
| `get-home-dir` | 获取 Home 目录 | 返回 `os.homedir()` |

---

## 4. 传输层 — `transport.ts`

> 文件：`src/transport.ts`（357 行）

传输层是渲染进程中的**统一通信抽象层**，将所有 HTTP / WebSocket / Server-Sent Events 通信路由通过 Electron IPC。渲染进程不直接发起网络请求。

### 4.1 类型定义

#### 用户 ATTP 配置

```typescript
interface TraceNodeEntry { name: string; url: string }

interface UserAttpConfig {
  did: string
  didDocPath: string
  didKeyPath: string
  protocolNodes: TraceNodeEntry[]    // 协议节点（溯源后端）
  toolNodes: TraceNodeEntry[]        // 工具节点
  agents: { name: string; baseUrl: string; did?: string }[]
}
```

#### WS / SSE 连接抽象

```typescript
interface WsConnection { readonly id: string; send: (data: any) => void; close: () => Promise<void> }
interface SseConnection { readonly id: string; close: () => Promise<void> }   // SSE 仅 close，无 send
```

### 4.2 HTTP 通信 — `apiFetch()`

```typescript
async function apiFetch(url: string, options?: RequestOptions): Promise<ApiResponse>
```

通过 `window.electronAPI.request()` 发起 IPC HTTP 请求，返回标准化 `{ ok, status, data, error? }`。

### 4.3 WebSocket 通信

| 函数 | 说明 |
|------|------|
| `createWs(url)` | 创建 IPC WS 连接，返回 `WsConnection`（注册全局监听器一次） |
| `onWsMessage(conn, handler)` | 注册消息处理器（`Set` 存储，支持多处理器） |
| `onWsOpen(conn, handler)` | 注册连接建立处理器 |
| `onWsClose(conn, handler)` | 注册关闭处理器（连接关闭时自动清理全部 handler） |
| `onWsError(conn, handler)` | 注册错误处理器 |

全局监听器管理：使用 `Map<id, Set<Handler>>` 结构，`wsListenersRegistered` 标志确保 `window.electronAPI.onWs*` 仅注册一次。

### 4.4 SSE 通信（新增）

| 函数 | 说明 |
|------|------|
| `createSse(url)` | 创建 IPC SSE 流，返回 `SseConnection`（注册全局监听器一次） |
| `onSseEvent(conn, handler)` | 注册事件处理器，签名为 `(event: string, data: any) => void` |
| `onSseOpen(conn, handler)` | 注册流建立处理器 |
| `onSseClose(conn, handler)` | 注册流结束处理器（自动清理） |

`SseEventData` 形如 `{ id, eventId?, event, data }`。与 WS 同构的 `Map<id, Set<Handler>>` 模式，`sseListenersRegistered` 保证仅注册一次。

---

## 5. ATTP 协议层

### 5.1 密钥导入 — `attp/key_helper.ts`（246 行）

将 PEM 私钥导入为可签名对象，支持**五类曲线**。

#### 密钥类型体系

```typescript
class Secp256k1PrivateKey { readonly keyType = 'secp256k1'; readonly rawBytes: Uint8Array }  // 32B
class Ed25519PrivateKey    { readonly keyType = 'ed25519';    readonly rawBytes: Uint8Array }  // 32B

type SignableKey = CryptoKey | Secp256k1PrivateKey | Ed25519PrivateKey
```

类型守卫 `isSecp256k1Key()` / `isEd25519Key()` 用 `instanceof` 判定。

#### 密钥导入流程 — `importPrivateKeyFromPem()`

```
PEM 字符串
    │
    ├── detectKeyType(pem)
    │   ├── 含 'RSA'                       → RSA
    │   ├── DER 含 Ed25519 OID (06 03 2B 65 70) → Ed25519
    │   └── 其他                            → EC
    │
    ├── RSA     → Web Crypto importKey('pkcs8', RSA-PSS, SHA-256)
    ├── Ed25519 → extractEd25519RawBytes()（取 PKCS#8 DER 最后 32 字节）→ Ed25519PrivateKey
    └── EC      → 依次尝试 Web Crypto 导入
        ├── P-256 → 成功 → CryptoKey
        ├── P-384 → 成功 → CryptoKey
        ├── P-521 → 成功 → CryptoKey
        └── 全部失败 → isSecp256k1() 复检（导入失败=疑似 secp256k1）
            ├── 取末 32 字节 + secp.utils.isValidSecretKey 校验 → Secp256k1PrivateKey
            └── 失败 → 抛出异常
```

> `extractSecp256k1RawBytes()` 与 `extractEd25519RawBytes()` 都用「取 DER 末 32 字节」的简单策略。`importPublicKeyFromPem()` 用于公钥验签（RSA/ECDSA，secp256k1 公钥 Web Crypto 验签暂不支持）。

#### 各曲线签名方式（见 `protocol.ts` signWithKey）

| 曲线 | 签名实现 | 输出格式 |
|------|---------|---------|
| RSA (RSA-PSS) | `@attp/core signHash()` | 原始签名字节 → Base64 |
| ECDSA (P-256/384/521) | `@attp/core signHash()` | 原始签名字节 → Base64 |
| secp256k1 | `@noble/secp256k1 signAsync()` | compact → DER 转换 → Base64 |
| Ed25519 | `@noble/curves ed25519.sign()` | 原始 64 字节 → Base64 |

### 5.2 协议消息 — `attp/protocol.ts`（221 行）

ATTP 用户端核心消息构造与发送逻辑。

#### 统一签名函数 — `signWithKey(hash, privateKey)`

按密钥类型分发：CryptoKey → `@attp/core signHash`；Secp256k1PrivateKey → SHA-256 后 `signAsync` 并转 DER；Ed25519PrivateKey → 直接对 hash 字节签名。三者均输出 Base64。

#### Phase 1：构造 NodeMessage — `buildNodeMessage()`

```
1. generateNonce()（16 字节随机十六进制）
2. 从 UserSessionManager 取并递增 hop_count
   - 初始 [0,0]（首条 U2A 必为 [0,0]）
   - 否则 session.incrementHopCount()
3. new RecordedHop({ sessionId, senderDid=userDid, targetDid, content, timestamp, hopCount })
4. recordedHop.contentHash() → signWithKey → sigContent
5. new NodeMessage({ protocolUrl, nonce, recordedHop })
6. 返回 { nodeMessage, nonce, recordedHop }
```

`hop_count` 在 session 级别由 `UserSessionManager` 维护，确保同一会话内序号连续递增。

#### Phase 2：发送 BackMessage — `sendBackMessage()`

```
1. new BackMessage({ protocolUrl, nodeDid=userDid, nonce, recordedHop })
2. identityHash(userDid, nonce) = SHA-256(sorted JSON({ node_did, nonce }))
3. signWithKey(iHash) → sigIdentity
4. apiFetch POST → {protocolUrl}/record
5. 返回协议节点是否确认（result.ok）
```

#### 消息解析 — `parseIncomingNodeMessage(data)`

直接 `NodeMessage.fromDict(data)`，失败返回 `null`。旧格式（`type:'chat'`）的兼容在 `useChat` 的 message handler 中处理，不在本函数。

---

## 6. Composables 业务逻辑层

### 6.1 useAttpProtocol — ATTP 协议核心

> 文件：`src/composables/useAttpProtocol.ts`（396 行）

管理用户身份、密钥、协议消息的完整生命周期。

#### 单例状态（模块级）

```typescript
const userConfig = reactive<UserAttpConfig>({ ... })
let cachedPrivateKey: SignableKey | null = null
let cachedKeyPath = ''
const attpSessionManager = new UserSessionManager()   // @attp/core
attpSessionManager.loadFromStorage()
export const protocolBindingsVersion = ref(0)         // 绑定变更版本号（驱动响应式）
```

#### ATTP 会话管理器与绑定

`UserSessionManager` 在 localStorage 持久化每个 session 的 `protocolNodeAddress` / `currentHopCount` / `userDid`。

| 函数 | 功能 |
|------|------|
| `bindSessionProtocolUrl(sessionId, url)` | 绑定 + `protocolBindingsVersion++` |
| `getSessionProtocolUrl(sessionId)` | 读绑定（仅 session 级） |
| `clearSessionProtocolUrl(sessionId)` | 清除 + 版本号自增 |

`protocolBindingsVersion` 用于让 `App.vue` 中基于 `getSessionProtocolUrl` 的 `computed` 在绑定变更后重新求值（`attpSessionManager` 本身非响应式）。

#### 配置 I/O

| 函数 | 存储位置 |
|------|---------|
| `loadUserConfig()` | `~/.attp/user/config.json`（via IPC）；密钥路径变更时清缓存 |
| `saveUserConfig()` | 同上（深拷贝剥离 Vue reactive proxy） |

#### 密钥管理 — `loadPrivateKey()`

从 `didKeyPath` 读 PEM（via IPC `read-file`）→ `importPrivateKeyFromPem` → 缓存（路径不变时复用）。

#### U2A 发送 — `sendMessageWithAttp(content, sessionId, targetDid)`

```
1. 校验：User DID、protocolUrl（session 绑定）、私钥
2. buildNodeMessage() → NodeMessage + nonce + recordedHop
3. ===== 时序规则：先回传协议节点 =====
4. sendBackMessage() → POST {protocolUrl}/record
5. 协议节点确认后，返回 { success:true, nodeMessageDict }
   （由调用方 conn.send(JSON.stringify(nodeMessageDict)) 发给 Agent）
```

#### A2U 接收 — `handleReceivedNodeMessage(incomingData)`

```
1. parseIncomingNodeMessage() → 解析 WS 收到的 NodeMessage
2. session.setHopCount(recordedHop.hopCount) 更新游标
3. 校验 User DID + 私钥
4. sendBackMessage() → 异步回传（fire-and-forget，不阻塞渲染）
```

#### 节点/Agent 管理

| 函数 | 管理对象 |
|------|---------|
| `addProtocolNode / updateProtocolNode / removeProtocolNode / saveProtocolNodes` | 协议节点（持久化到 user config） |
| `saveToolNodes` | 工具节点 |
| `addAgent / removeAgent` | Agent（同时写回 user config） |

### 6.2 useProtocolNodes — 协议节点共享单例（新增）

> 文件：`src/composables/useProtocolNodes.ts`（137 行）

三个溯源子视图（NodeManage / TraceQuery / Malicious / CrossLock）共享同一份节点列表与选中态，避免各自维护。

```typescript
interface TraceNode { id: string; name: string; url: string; status: 'online' | 'offline' | 'checking' }

const traceNodes = ref<TraceNode[]>([])         // 模块级单例
const selectedNodeId = ref<string | null>(null)
const selectedNode = computed(() => traceNodes.value.find(n => n.id === selectedNodeId.value) || null)
```

| 函数 | 说明 |
|------|------|
| `loadNodes(force?)` | 从 `userConfig.protocolNodes` 幂等加载 |
| `addNode / updateNode / removeNode` | CRUD（变更后 `persist()` 写回配置） |
| `checkNodeStatus(node)` | 请求 `{url}/api/status` 判定 online/offline |
| `checkAllNodes()` | 批量探活 |
| `ensureSelection()` | 无选中时默认选首个在线节点 |
| `buildUrl(path)` | 基于 selectedNode.url 拼接完整 URL（未选中返回空串） |

`id` 由 `makeId(url)` 生成（`node_` + URL 字符化），保证跨视图一致。

### 6.3 nodeEvents — 全局告警常驻 SSE（新增）

> 文件：`src/composables/nodeEvents.ts`（58 行）

模块级单例 SSE 连接，订阅 `topics=record,malicious`。无论用户在哪个页面，以下两类「全局告警」都送达：

| 事件 | 触发 | UI 反应 |
|------|------|--------|
| `record.error` | 回传消息处理失败（验证失败/异常） | App.vue 顶部 toast（错误） |
| `malicious.detected` | 协议节点检出恶意节点 | App.vue 顶部 toast + MaliciousView 列表刷新 |

```typescript
export function onRecordError(cb): () => void        // 返回 unsubscribe
export function onMaliciousDetected(cb): () => void
export async function connectNodeEvents(url): Promise<void>   // 先断旧连再开新连；空 url 仅断开
export async function disconnectNodeEvents(): Promise<void>    // 断开但保留已注册 handler
```

> 分析进度（`analysis.*`）与行为链生长（`trace.recorded`）**不在此处**，由各视图按需订阅（见 §9）。

### 6.4 useAnalysisFlow — 引导式分析流程状态机（新增，核心）

> 文件：`src/composables/useAnalysisFlow.ts`（167 行）

通过 SSE 订阅 analysis 事件流，实时反映 LLM 分析进度。纵轴（`axis:'v'`，session 级）与横轴（`axis:'h'`，DID 级）共用，仅过滤字段不同。

#### 状态与回调

```typescript
const status = ref<AnalysisStatus | null>(null)    // { status, session_id?, did?, phase?, triggered?, reason?, queue_depth? }
const triggerLoading = ref(false)
const running = computed(() => status.value?.status === 'running')
const completedHooks: Array<(id) => void> = []     // report 完成时拉最新 state + report
const stateChangeHooks: Array<(id) => void> = []   // hop.scored / horizontal.* 时刷中间态
```

#### 核心方法

| 方法 | 行为 |
|------|------|
| `trigger(id)` | `POST /api/analysis/{axis}/trigger/{id}`；`result.data.triggered===true` → 标记 `running{phase:'starting'}` + `subscribe(id)` + `startPolling(id)` |
| `subscribe(id)` | `GET /api/events?topics=analysis&{session_id\|did}={id}` SSE；解析见下 |
| `unsubscribe()` | 关闭 SSE + 停止轮询（`onScopeDispose` 自动调用） |
| `pollLlmStatus(id)` | `GET /api/analysis/{axis}/llm-status/{id}`；running 期间每 1500ms 轮询，补 SSE 未带的 `queue_depth`/`phase` |
| `onCompletedHook(cb)` | 追加完成回调 |
| `onStateChange(cb)` | 追加中间态变更回调 |

#### SSE 事件处理（subscribe 内）

| 事件 | 行为 |
|------|------|
| `analysis.progress` | 标记 `running{phase}` + `startPolling(id)` |
| `analysis.report` | `stopPolling` + 标记 `completed{triggered, reason}` + 触发 `completedHooks`；**不自动 unsubscribe**（保持连接以接收后续事件） |
| 纵轴 `hop.scored` | 触发 `stateChangeHooks`（刷新逐跳评分报告） |
| 横轴 `horizontal.triggered` | 触发 `stateChangeHooks`（F 超 R_S，确认被触发） |
| 横轴 `horizontal.accumulated` | 触发 `stateChangeHooks`（F/volume 累加） |

> 任务状态词汇：`running | completed | not_found | already_running ...`（见 `views/trace/types.ts` 的 `AnalysisStatus`）。

### 6.5 useChat — 聊天会话管理

> 文件：`src/composables/useChat.ts`（805 行）

最复杂的 Composable，管理多 Agent 聊天、WS 连接池、会话持久化。

#### 多 Agent 状态管理（模块级 Map）

```typescript
const agentSessionsMap      = new Map<string, ChatSession[]>()      // agentId → sessions
const agentCurrentSessionMap = new Map<string, string | null>()     // agentId → currentSessionId
const agentWsMap            = new Map<string, WsConnection>()       // agentId → WS 连接
const agentWsConnectedMap   = new Map<string, boolean>()            // agentId → 连接状态
const connectingAgents      = new Set<string>()                     // 连接中去重
const wsUrlToAgentId        = new Map<string, string>()             // WS URL → agentId 去重
export const needsProtocolBinding = ref(false)                      // 标记需绑定协议节点
```

#### 会话数据结构

```typescript
interface ChatSession {
  id: string; title: string; messages: ChatMessage[]
  rtLogs?: { senderName: string; text: string }[]
  nodeHistories?: { [targetNode: string]: { role; text; timeStr }[] }
  updatedAt: number
  isPinned?: boolean; isUnread?: boolean; unreadCount?: number; senderName?: string
}
```

#### 会话持久化

- 每个 Agent 的会话独立存储在 `localStorage`，key 为 `attp_sessions_{agentId}`
- Agent 切换：`flushActiveSessions()` → `loadActiveSessions()`
- 后台 Agent 收到消息：直接操作其 session 数组 + `saveSessionsForAgent` + 标记未读

#### WebSocket 连接管理

`connectAllAgents()` 按 WS URL 分组：

```
按 wsUrlForAgent(agent, '/ws') 分组
    │
每个唯一 URL：
    ├── agentIds[0] → connectAgentWs() 实际 createWs() + 注册 open/close/error/message
    └── agentIds[1..] → 复用 primaryConn + 各自注册 onWsMessage(createMessageHandler(aid))
```

`connectAgentWs` 内部还有 `wsUrlToAgentId` 去重：若已有 Agent 连到相同 URL 且在线，直接复用其 `WsConnection`。

#### 消息处理 — `createMessageHandler(agentId)`

```
WS 收到消息
    │
    ├── JSON 解析
    ├── NodeMessage.fromDict(data) 解析
    │   ├── 成功 → 提取 RecordedHop（content, sessionId, senderDid）
    │   │         → addMessageToAgentSession(agentId, sessionId, 'agent', content)
    │   │         → rtLog 记录（活跃/后台分别落 reactive 或独立数组）
    │   │         → handleReceivedNodeMessage(data)  // 异步回传
    │   └── 失败 → 兼容旧格式（type:'chat' + content + session_id）
    │
    └── 后台 Agent 时递增 unreadCount
```

#### 发送消息 — `sendMessage()`

```
用户输入 → sendMessage()
    │
    ├── 校验 session 绑定 protocol（getSessionProtocolUrl 非空），否则 needsProtocolBinding=true 并 return
    ├── addMessageToSession('user', text)
    ├── 校验 ATTP 已初始化 + WS 已连接
    ├── sendMessageWithAttp() → 构造签名 NodeMessage + 回传协议节点
    │   ├── 失败 → 阻止发送（ATTP-only 模式）
    │   └── 成功 → 返回 nodeMessageDict
    └── conn.send(JSON.stringify(nodeMessageDict))
```

#### 会话操作

创建 `createSession(title, protocolUrl?)`（不传 protocolUrl 则置 `needsProtocolBinding=true`）；加载 `loadSession`；删除 `deleteSessionRecord`；置顶 `pinSessionRecord`；批量 `batchDeleteSessions / batchPinSessions / batchUnpinSessions`。

### 6.6 useNodes — 对端节点发现

> 文件：`src/composables/useNodes.ts`（35 行）

从活跃 Agent 的 `/api/nodes` 获取其已知对端节点列表：

```typescript
interface AgentNode {
  name: string; did: string; ad_url: string
  description: string; capabilities: string[]; online: boolean
}
```

节点图标按 `capabilities` 映射：`data_storage` → Database，`security_check` → ShieldCheck，其他 → Server。

### 6.7 useSettings — 活跃 Agent 配置管理

> 文件：`src/composables/useSettings.ts`（237 行）

管理**活跃 Agent** 的 ATTP 网络配置（Agent 端配置，非 User 端）。

#### 配置结构（7 组）

```typescript
interface AttpConfig {
  did: string
  attpClient: { didDocPath, didKeyPath, nodeAds[] }
  attpServer: { name, prefix, description, serverHost, serverPort, privateKeyPath, publicKeyPath }
  webApp: { host, port }
  tool: { host, port, toolNodeAds[] }
  heartbeat: { interval, timeout, maxFail }
  protocolNode: { enabled, configPath }
}
```

#### 配置操作

| 操作 | API 端点 | 说明 |
|------|---------|------|
| 加载 | `GET /api/config` | 从 Agent 读当前配置（`data.config`） |
| 保存 | `PUT /api/config` | 保存到磁盘（不立即生效） |
| 刷新 | `GET /api/config?refresh=true` | 从磁盘重读 |
| 重载 | `POST /api/config/reload` | 保存 + 热重载生效；webApp host/port 变更时弹 warning |

`SettingsView` 进入时 `loadConfig()`，并监听 `window` 的 `load-settings` 自定义事件（路由 `afterEach` 派发）。

### 6.8 useTraceFormat — 徽章/格式化工具（新增）

> 文件：`src/composables/useTraceFormat.ts`（146 行）

纯函数 + 常量，跨溯源视图复用。

- **fieldType 配色**：`A2T` 蓝 / `A2U` 紫 / `U2A` 绿 / `A2A` 橙 / `T2A` 青（与 `types.ts` 的 `fieldTypes` 一致）
- **徽章函数**：`verificationBadge`（已验证/未验证/已篡改）、`verdictBadge`（clean/suspicious/malicious）、`severityBadgeCls`（none/low/medium/high/critical 五档）、`severityLevelBadge`（clean/warning/dangerous/banned 四档）、`sourceBadge`（协议审查/纵向分析/横向分析）、`riskLevelBadge`
- **格式化**：`formatTime(ts)`（数字按 unix 秒转 ms）、`formatDid(did)`（取最后一段）
- **链路转换**：`transformChainToNodes(chain)` 把扁平 `BehaviorChainEntry[]` 按 `(hop_count, sender_did)` 分组成 `HopNode[]`，并按 `hop_count` 二元组排序

### 6.9 useToast — 轻量 toast（新增）

> 文件：`src/composables/useToast.ts`（61 行）

每次调用独立实例。`success` 默认 2.5s，`error` 默认 6s；支持 `dismissToast` / `pauseToast`（悬停暂停，保留剩余时间）/ `resumeToast`。`showToast` 可显式传 `duration` 覆盖默认值。

---

## 7. Agent 管理器 — `agent_manager.ts`

> 文件：`src/agent_manager.ts`（222 行）

管理用户连接的多个 Agent 后端。

### 7.1 数据结构

```typescript
interface AgentEntry {
  id: string                    // 'agent_' + timestamp(base36) + '_' + random
  name: string
  baseUrl: string               // 如 "http://192.168.1.50:8001"
  did?: string                  // Agent 的 DID（如 did:wba:host:agent-name）
  status: 'active' | 'offline' | 'connecting'
}

const agents = ref<AgentEntry[]>([])
const activeAgentId = ref<string | null>(null)
let onAgentSwitchCallbacks: Array<() => void> = []
```

### 7.2 核心功能

| 功能 | 函数 | 说明 |
|------|------|------|
| 获取列表 | `getAgents()` | 返回所有 Agent |
| 获取活跃 | `getActiveAgent()` / `getActiveAgentId()` / `getActiveAgentUrl()` | 当前活跃 Agent |
| 切换活跃 | `setActiveAgent(id)` | 切换 + 写 localStorage + 触发 `onAgentSwitch` 回调 |
| 添加 | `addAgent(name, baseUrl, did?)` | 注册 + 持久化；首个自动激活；异步 `testAgentConnection` |
| 删除 | `removeAgent(id)` | 删除 + 自动切到下一个 + 持久化 |
| 重命名 | `renameAgent(id, newName)` | 仅改 name（baseUrl 改动需重连，UI 暂不支持） |
| 状态更新 | `updateAgentStatus(id, status)` | 更新 + 持久化 |
| 探活 | `testAgentConnection(baseUrl)` | `GET {baseUrl}/api/status` |

### 7.3 URL 构建

```typescript
apiUrl(path)              // 活跃 agent.baseUrl + path
wsUrl(path)               // 活跃 agent，http→ws 协议替换 + path
wsUrlForAgent(agent, path) // 指定 agent
```

### 7.4 持久化与加载

Agent 列表存储在 `~/.attp/user/config.json` 的 `agents` 字段：

```
addAgent/removeAgent/renameAgent/updateAgentStatus → persist()
persist() → readUserConfig + 改 agents + saveUserConfig（JSON 深拷贝剥离 reactive proxy）
```

`loadAgents()` 从配置恢复：为每个 Agent 生成稳定 ID `agent_{index}_{baseUrl去字符化}`，默认激活第一个，并发 `testAgentConnection` 刷新状态。活跃 Agent ID 另存于 `localStorage` key `attp_active_agent`。

---

## 8. 视图层

### 8.1 App.vue — 根布局与全局告警

> 文件：`src/App.vue`（494 行）

左侧 260px 侧边栏 + 主内容区（`router-view`）+ 全局 toast。侧边栏分组：

| 区域 | 项 |
|------|----|
| 顶部 | 品牌头「谛听 / 基于 ATTP 的多智能体工作区」+ 智能体切换器（浮层下拉，支持 ⋯ 右键菜单：编辑/移除） |
| 当前智能体导航（无 agent 时灰禁） | 对话 / 会话历史 / 配置 / **对端节点**（agent 发现的，可折叠子组） |
| 底部钉住区 | **溯源**：节点管理 / 溯源查询 / 恶意报告（铺平子项）；**工具管理**；**用户配置** |
| 版本号 | `v0.2.0-alpha.2`（硬编码） |

> **十字锁定视图**（`/trace/cross-lock`）不在侧栏，仅能从 TraceQueryView 的「十字锁定综合视图」按钮进入。

#### 全局告警常驻 SSE（onMounted 后 watch）

```typescript
const activeProtocolUrl = computed(() => {
  protocolBindingsVersion.value        // 绑定变更时重算
  const sid = currentSessionId.value
  if (sid) { const u = getSessionProtocolUrl(sid); if (u) return u }
  return selectedNode.value?.url || ''  // 回退到 useProtocolNodes 选择器
})
watch(activeProtocolUrl, async url => {
  url ? await connectNodeEvents(`${url}/api/events?topics=record,malicious`)
      : await disconnectNodeEvents()
}, { immediate: true })
```

`onRecordError` / `onMaliciousDetected` 注册全局 handler，分别弹错误 toast。`onScopeDispose` 断开 SSE。

#### 启动流程（onMounted）

```
loadUserConfig() → loadAgents() → initAgentContext() → connectAllAgents() → fetchNodes()
onAgentSwitch(() => fetchNodes())   // 切 Agent 后刷新对端节点
```

### 8.2 HomeView — 对话主页

> 文件：`src/views/HomeView.vue`

聊天主页：消息按日期分组 + Markdown 渲染；右侧实时网络面板（rtLogs，按会话维护）。

#### 协议节点绑定流程

```
handleNewChat()
    │
    ├── protocolNodes.length === 0 → 按钮 disabled
    ├── protocolNodes.length === 1 → 直接 createSession('New Chat', url)
    └── 多个 → 弹选择弹窗
        ├── isCreateMode = true  → createSession + 绑定
        └── isCreateMode = false → bindSessionProtocolUrl(当前 session, url)

needsProtocolBinding watch：true 且有可用节点 → 自动弹弹窗（补选模式）
```

输入区显示绑定状态：已绑定（绿色锁 + 节点名 + 「会话期间锁定」）/ 未绑定（琥珀色提示 + 选择按钮）/ 无节点（灰提示）。

### 8.3 SessionsView — 会话历史

> 文件：`src/views/SessionsView.vue`

会话历史列表，分区展示（置顶 + 最近）、搜索、批量管理（全选/置顶/取消置顶/删除）、未读气泡。

**溯源跳转**（关键变更）：

```typescript
handleTrace(id) → router.push(`/trace/query?sessionId=${id}&protocolNodeUrl=${url}`)
// 未绑定 protocolUrl 的会话拦截并提示
```

跳转目标从旧版的 `/trace` 改为 `/trace/query`，并直达查询页（路由把 `/trace` 重定向到 `/trace/query`）。

### 8.4 SettingsView — 活跃 Agent 配置

> 文件：`src/views/SettingsView.vue`（253 行）

7 个配置组（DID Identity / ATTP Client / ATTP Server / Web App / Tool / Heartbeat / Protocol Node）。操作按钮：**Refresh**（`?refresh=true` 从磁盘重读）、**Save Changes**（PUT，不生效）、**Reload**（POST `/api/config/reload` 热重载）。`onMounted` 加载配置 + 监听 `load-settings` 事件。

### 8.5 ToolView — 工具节点管理

> 文件：`src/views/ToolView.vue`

管理用户已知的工具节点（持久化到 user config 的 `toolNodes` 字段）：

| 功能 | 说明 |
|------|------|
| 工具节点 CRUD | 从 `userConfig.toolNodes` 加载，变更后 `configSaveToolNodes` |
| 探活检测 | 请求 `{url}/health` |
| ad.json 查询 | 请求 `{url}/ad.json`，展示 `mcp_tools` 列表 |

### 8.6 UserConfigView — 用户身份配置

> 文件：`src/views/UserConfigView.vue`

管理**用户端自身**的 ATTP 身份：User DID / DID Document Path / Private Key Path / 协议节点列表（name + url）/ Known Agents（name + did + baseUrl）。

与 SettingsView 的区别：

| 维度 | UserConfigView | SettingsView |
|------|---------------|-------------|
| 配置对象 | 用户自身（User） | 活跃 Agent |
| 存储位置 | `~/.attp/user/config.json` | Agent 端 `config.json` |
| 读写方式 | IPC 直接读写文件 | HTTP API 调用 Agent |
| 功能 | DID/密钥/协议节点/Agent 管理 | Agent 网络配置 |

### 8.7 NodeView — 对端节点详情

> 文件：`src/views/NodeView.vue`

展示活跃 Agent 发现的某个对端节点（`route.params.index`）。通过 `useNodes.fetchNodes()` 获取节点列表，显示该节点在当前会话的 `nodeHistories` 消息。发送通过 `window.dispatchEvent('send-node-message', { detail: { text, targetDid } })`。

### 8.8 溯源模块子视图（重构）

旧版单一 `TraceView.vue` 已拆分为 `views/trace/` 目录下 4 个子视图 + 共享 `types.ts` + 7 个组件。

#### 8.8.1 共享类型 — `views/trace/types.ts`

逐跳改版的核心数据模型（量纲：taint_score / score ∈ [0,10]，0.5 步进；severity 五档；`overall_verdict` 由代码推导 clean/suspicious/malicious）：

| 类型 | 说明 |
|------|------|
| `DimensionScore = [number,number,number,number]` | 4 维评分：意图对齐 / 能力越权 / 注入操纵 / 外泄篡改（`DIMENSION_LABELS`） |
| `BehaviorChainEntry` / `HopNode` | 行为链扁平记录 / 按 hop+sender 聚合 |
| `HopScore` | 单跳评分（纵轴 V-Reasoner 输出） |
| `IntentRevision` / `IntentRevisionSource` | 意图增量 Δ（发起者 U2A 抽取） |
| `VerticalState` / `VerticalReport` | 纵向状态 / 报告 |
| `HorizontalState` / `ConfirmationVerdict` / `HorizontalReportBlob` / `AnalysisReport` | 横向累积状态 / 单 DID 裁决 / 报告 blob / 外层包装 |
| `MaliciousReport` / `MaliciousDossier` | 恶意事件 / 节点档案（severity_level 四档：clean/warning/dangerous/banned） |
| `AnalysisStatus` | 分析任务状态（running/completed/idle/not_found，含 phase / triggered / reason / queue_depth） |

#### 8.8.2 NodeManageView — 协议节点管理

> 文件：`views/trace/NodeManageView.vue`

协议节点 CRUD + 在线检测（`useProtocolNodes`）。卡片网格展示，状态徽章（Online/Offline/检测中），「检测全部」批量探活。`onMounted` 强制重载节点 + `checkAllNodes()`。

#### 8.8.3 TraceQueryView — 溯源查询（主视图）

> 文件：`views/trace/TraceQueryView.vue`（580 行）

双模式：**纵向**（session 级）/ **横向**（DID 级），顶部 NodeSelector + 模式切换。

**纵向**（queryMode='vertical'）：
- 累计状态卡（意图增量数 / 打分游标 / 隐状态）+ 总体裁决 banner（overall_verdict + max_score + total_hops）
- 分析状态条 `AnalysisStatusBar`（触发/刷新/状态文案）
- 意图流（Intent Stream，`intent_revisions`，report 优先回退 state）
- 十字锁定入口按钮
- 三 Tab：行为溯源（`BehaviorChain`）/ 逐跳评分（`HopScoreCard` 列表）/ 告警（R_T 单点，`source=vertical_analysis`）

**横向**（queryMode='horizontal'）：
- 累计状态卡（节点类型 / 确认批次 / 累计跳数 volume / 确认游标 last_trace_id）
- F 累积进度（`FProgress`：Σ s² vs R_S，默认 R_S=25）
- 分析状态条
- 横向分析报告列表（`AnalysisReportCard`，axis='h'）

#### 8.8.4 MaliciousView — 恶意报告

> 文件：`views/trace/MaliciousView.vue`

全局恶意节点档案（`GET /api/malicious/dossiers?source=&severity=&limit=200`），支持来源 / 等级筛选；点击档案展开抽屉看违规明细（`GET /api/malicious/dossier/{did}`）。订阅全局 `onMaliciousDetected`，收到事件时刷新档案列表。

#### 8.8.5 CrossLockView — 十字锁定综合视图（新增）

> 文件：`views/trace/CrossLockView.vue`

一次聚出纵 + 横全景：

```
GET /api/analysis/cross-lock/{session_id}?protocol_node_address=
  → vertical   { hop_scores, overall_verdict, total_hops, alerts }
    horizontal { tracked_dids: [{ did, f_value, volume, batch_index, last_horizontal_analysis }] }
```

纵轴：各维度跨跳最大值雷达图（`DimRadar`）+ 逐跳评分卡片。横轴：各 DID F 累积进度行（`FProgress`）+ 最后一次横向分析裁决（确认恶意 / 判为良性 + overall_verdict）。

#### 8.8.6 组件 props

| 组件 | props / 作用 |
|------|------|
| `NodeSelector.vue` | 绑定 `useProtocolNodes.selectedNodeId`（v-model），无 props |
| `BehaviorChain.vue` | `nodes: HopNode[]` |
| `AnalysisReportCard.vue` | `report: AnalysisReport; axis?: 'v'\|'h'`；emit `view-dossier(did)` |
| `AnalysisStatusBar.vue` | `status / statusKind / polling / triggerLoading / refreshDisabled / triggerDisabled`；emit `refresh / trigger` |
| `HopScoreCard.vue` | `hop: HopScore` |
| `FProgress.vue` | `fValue: number; rS?: number = 25` |
| `DimRadar.vue` | `dimensions: number[]\|[number,number,number,number]; size?: number = 120` |

---

## 9. SSE 事件订阅与分析流程（v0.3.0 逐跳模型）

v0.3.0 将分析模型改为**逐跳 / 状态化**。用户端通过 SSE 实时接收协议节点推送的事件。

### 9.1 事件词汇（对齐 `python/attp/core/sse/schema.py`）

```
Topic:      trace | analysis | malicious | record
EventType:
  trace.recorded             ← topic=trace
  analysis.progress          ┐
  analysis.report            │
  hop.scored                 ├ topic=analysis（注意：hop.* / horizontal.* 归入 analysis topic）
  horizontal.accumulated     │
  horizontal.triggered       ┘
  malicious.detected         ← topic=malicious
  record.error               ← topic=record
```

> 约定：事件 type 的前缀**不必**与 topic 一致——`hop.scored`、`horizontal.accumulated`、`horizontal.triggered` 都归入 `analysis` topic，以便 `topics=analysis` 一并接收。

### 9.2 用户端三路 SSE 订阅

| 订阅方 | URL（topics） | 生命周期 | 消费事件 |
|--------|--------------|---------|---------|
| **全局常驻**（`nodeEvents.ts` + `App.vue`） | `{protocolUrl}/api/events?topics=record,malicious` | 跟随当前会话绑定节点 / 选择器节点；切换时先断后连 | `record.error`、`malicious.detected` → 顶部 toast（错误）；MaliciousView 另注册 `onMaliciousDetected` 刷列表 |
| **分析流程**（`useAnalysisFlow.ts`，纵/横各一） | `{protocolUrl}/api/events?topics=analysis&{session_id\|did}={id}` | 触发分析后订阅，`onScopeDispose` 断开；report 后不自动断 | `analysis.progress`、`analysis.report`、`hop.scored`(v)、`horizontal.triggered`(h)、`horizontal.accumulated`(h) |
| **行为链实时**（`TraceQueryView.vue`） | `{protocolUrl}/api/events?topics=trace&session_id={sid}` | 纵向查询时订阅，切轴/卸载断开 | `trace.recorded` → 重拉 behavior + 纵向 state/report |

### 9.3 useAnalysisFlow 状态机详解

```
trigger(id)
  │ POST /api/analysis/{v|h}/trigger/{id}
  ├─ result.data.triggered === true ?
  │    是 → status = running{phase:'starting'}
  │         subscribe(id)              ← SSE 订阅
  │         startPolling(id)           ← 每 1.5s 轮询 llm-status
  │    否 → 返回 false（UI toast「触发失败」）
  │
subscribe(id) 内：
  analysis.progress   → status = running{phase} + startPolling
  analysis.report     → stopPolling + status = completed{triggered, reason}
                       + completedHooks(id)：拉 v.state / v.report / v.alerts（纵）
                                            拉 h.state / h.report（横）
                       不自动 unsubscribe（保持连接接收后续事件）
  hop.scored (纵)     → stateChangeHooks：刷逐跳评分 + 告警
  horizontal.triggered (横) → stateChangeHooks：刷横向累计状态
  horizontal.accumulated (横) → stateChangeHooks：刷横向累计状态
```

`statusKind`（TraceQueryView 推导）：

| statusKind | 条件 |
|-----------|------|
| `running` | status 为 running / already_running |
| `completed` | completed + triggered !== false |
| `uptodate` | completed + triggered===false + reason ∈ {no_unanalyzed_traces, no_new_traces}（无待分析） |
| `failed` | completed + triggered===false + 其他 reason |

触发按钮始终显示（新模型无 pending_count；后端 `triggered:false` + `no_unanalyzed_traces` 兜底「无待分析」）。

---

## 10. 核心数据流

### 10.1 应用启动流程

```
App.vue onMounted()
    │
    ├── loadUserConfig()                // 加载 ~/.attp/user/config.json
    │   ├── did, didKeyPath, protocolNodes, toolNodes, agents
    │   └── 密钥路径变更 → 清缓存
    │
    ├── loadAgents()                    // 从 config.agents 恢复
    │   ├── 生成稳定 ID（agent_{index}_{baseUrl}）
    │   ├── 默认激活第一个
    │   └── 并发 testAgentConnection 刷新状态
    │
    ├── initAgentContext()              // [useChat] 初始化聊天上下文
    │   ├── flushActiveSessions → loadActiveSessions
    │   ├── WS 已连 → active；否则 checkAgentStatus + connectAgentWs
    │   └── 检查当前 session 协议节点绑定（决定 needsProtocolBinding）
    │
    ├── connectAllAgents()              // 按 WS URL 分组去重建立 WS
    │
    ├── fetchNodes()                    // 获取活跃 Agent 的对端节点
    │
    └── watch(activeProtocolUrl)        // 建立全局告警 SSE（record,malicious）

onAgentSwitch(() => fetchNodes())       // 切 Agent 后刷新对端节点
```

### 10.2 U2A 消息发送完整流程

```
用户输入文本 → handleSend() → sendMessage() [useChat]
    │
    ├── 校验 session 绑定 protocol（非空） + ATTP 已初始化 + WS 已连接
    ├── addMessageToSession('user', text)
    └── sendMessageWithAttp() [useAttpProtocol]
        │
        ├── loadPrivateKey()
        ├── buildNodeMessage() [protocol.ts]
        │   ├── generateNonce()
        │   ├── SessionManager 取/递增 hop_count
        │   ├── new RecordedHop + contentHash + signWithKey → sigContent
        │   └── new NodeMessage
        │
        ├── ===== 时序规则：先回传协议节点 =====
        ├── sendBackMessage() [protocol.ts]
        │   ├── new BackMessage
        │   ├── identityHash(userDid, nonce) + signWithKey → sigIdentity
        │   └── apiFetch POST → {protocolUrl}/record
        │       └── IPC → Electron HTTP 代理
        │
        └── 返回 nodeMessageDict → conn.send(JSON.stringify(...)) → IPC WS → Agent
```

### 10.3 A2U 消息接收完整流程

```
Agent → WS → Electron WS 代理 → IPC → 渲染进程
    │
    └── createMessageHandler(agentId)
        ├── JSON 解析 + NodeMessage.fromDict(data)
        │   ├── 提取 content / sessionId / senderDid
        │   ├── addMessageToAgentSession('agent', content)
        │   └── rtLog 落会话
        │
        └── handleReceivedNodeMessage() [异步，不阻塞渲染]
            ├── parseIncomingNodeMessage()
            ├── session.setHopCount(recordedHop.hopCount)
            ├── loadPrivateKey()
            └── sendBackMessage() → POST 协议节点 /record
```

### 10.4 会话-溯源节点绑定机制

```
创建新会话
    │
    ├── handleNewChat() [HomeView]
    │   ├── 1 个节点 → 自动绑定
    │   └── 多个 → 弹窗
    │       ├── isCreateMode → createSession('New Chat', url)
    │       └── 补选模式 → bindSessionProtocolUrl(sessionId, url)
    │           └── attpSessionManager.save() + saveToStorage() + protocolBindingsVersion++
    │
    ├── 发送校验
    │   └── getSessionProtocolUrl(sessionId) 必须非空，否则 needsProtocolBinding=true
    │
    ├── 全局 SSE 跟随
    │   └── App.vue watch(activeProtocolUrl) 重新连/断 nodeEvents SSE
    │
    └── 溯源查询跳转
        └── SessionsView → /trace/query?sessionId=...&protocolNodeUrl=...
```

### 10.5 多 Agent 并发连接架构

```
connectAllAgents()
    │
    ├── 按 wsUrlForAgent(agent, '/ws') 分组
    │   Agent A (ws://host:8001/ws) ─┐
    │   Agent B (ws://host:8001/ws) ─┤ 同 URL
    │   Agent C (ws://host:8002/ws) ─┘ 不同 URL
    │
    ├── URL Group 1: ws://host:8001/ws
    │   ├── Agent A: connectAgentWs() → createWs() → 注册 handler
    │   └── Agent B: 复用 primaryConn → 各自 onWsMessage(createMessageHandler(b))
    │
    └── URL Group 2: ws://host:8002/ws
        └── Agent C: connectAgentWs() → createWs() → 注册 handler
```

### 10.6 溯源查询 + 实时分析流程（纵轴示例）

```
TraceQueryView.doQuery(sessionId)
    │
    ├── 并发拉取：fetchBehavior / fetchVerticalState / fetchVerticalReport / fetchVerticalAlerts
    ├── vFlow.subscribe(sessionId)        ← SSE topics=analysis&session_id=...
    └── subscribeTrace(sessionId)         ← SSE topics=trace&session_id=...

用户点「触发纵向分析」→ vFlow.trigger(sessionId)
    │ POST /api/analysis/v/trigger/{id}
    ├─ running → 状态条显示运行中
    │   ├─ analysis.progress  → 更新 phase
    │   ├─ hop.scored         → onStateChange → 刷 report + alerts
    │   └─ analysis.report    → onCompleted → 刷 state + report + alerts
    │                          （SSE 不自动断，保持接收后续 hop.scored）
    │
    └── 同时：trace.recorded（来自 trace SSE）→ 刷 behavior + state + report
```

---

## 11. 设计模式与总结

### 11.1 设计模式应用

| 设计模式 | 应用位置 | 说明 |
|---------|---------|------|
| **Composable** | `useAttpProtocol` / `useChat` / `useNodes` / `useSettings` / `useProtocolNodes` / `useAnalysisFlow` | Vue 3 组合式 API，封装复用逻辑 |
| **模块级单例** | 模块级 `reactive` / `Map` / `ref`（含 `traceNodes`、`nodeEvents` 的 SSE conn） | 跨视图共享同一份状态/连接 |
| **IPC 代理** | Electron preload + ipcMain（HTTP/WS/SSE/File） | 绕过浏览器限制，统一通信方式 |
| **策略模式** | `SignableKey` + `signWithKey()` | 多曲线签名统一抽象 |
| **连接池** | `agentWsMap` + URL 去重 + SSE 单例 | 多 Agent 共享 WS；全局告警共享一条 SSE |
| **观察者模式** | `onAgentSwitch()` / `onRecordError` / `onMaliciousDetected` / `onCompletedHook` / `onStateChange` | 状态变更通知订阅者 |
| **模板方法** | `createMessageHandler(agentId)` | 闭包捕获 agentId，统一消息处理流程 |
| **状态机** | `useAnalysisFlow`（idle→running→completed/uptodate/failed） | SSE 驱动 + 轮询补充 |

### 11.2 安全机制

| 安全能力 | 实现方式 |
|---------|---------|
| **DID 身份标识** | 用户持有唯一 DID，配置在 `~/.attp/user/config.json` |
| **多曲线内容签名** | 对 `RecordedHop.contentHash()` 签名，支持 5 类曲线 |
| **身份签名** | 对 `identityHash(userDid, nonce)` 签名，证明消息来源 |
| **双轮回传** | 发送和接收消息后都回传 BackMessage 到协议节点 `/record` |
| **私钥缓存** | 内存中缓存已导入的私钥，路径不变时复用 |
| **HTML 安全过滤** | DOMPurify 过滤 Markdown 渲染结果 |
| **Electron 安全** | `nodeIntegration:false` + `contextIsolation:true` + `contextBridge` |
| **溯源绑定锁定** | 会话创建时绑定协议节点，会话期间不可更改；发送前校验 |
| **ATTP-only 模式** | 所有消息必须签名 + 回传，无绕过路径；回传失败阻止发送 |

> 注：`dev` 分支**未**实现 E2EE / TLS 统一传输安全层。当前 U2A/A2U 链路在签名/溯源层面保证可追溯，传输层本身不加密。

### 11.3 分层架构优势

1. **关注点分离**：Electron Shell（网络/文件） → 传输层（IPC 抽象，含 SSE） → 协议层（签名/消息） → 业务层（会话/配置/SSE 事件） → 视图层（UI）
2. **浏览器兼容**：所有网络请求（含 SSE 长连接）通过 IPC 代理，无 CORS 问题
3. **多曲线支持**：统一 `SignableKey` 接口，运行时自动检测密钥类型
4. **多 Agent 并发**：独立会话上下文 + WS 连接复用
5. **实时性**：SSE 推送分析进度/行为链生长/全局告警，UI 即时反映

### 11.4 配置文件汇总

| 配置文件 | 路径 | 管理者 |
|---------|------|--------|
| 用户 ATTP 配置 | `~/.attp/user/config.json` | Electron IPC + `useAttpProtocol`（默认种子无 `toolNodes`，运行时由 `ToolView` 写入） |
| Agent 网络配置 | Agent 端 `config.json` | `useSettings`（via Agent HTTP API） |
| 会话历史 | `localStorage` (`attp_sessions_{agentId}`) | `useChat` |
| ATTP 会话数据 | `localStorage` | `UserSessionManager`（protocolNodeAddress / hopCount / userDid） |
| 活跃 Agent ID | `localStorage` (`attp_active_agent`) | `agent_manager` |

### 11.5 扩展性

- **新增加密曲线**：在 `key_helper.ts` 加新包装类 + 导入分支，在 `protocol.ts` `signWithKey()` 加签名分支
- **新增溯源子视图**：在 `views/trace/` 加组件，在 `router.ts` 注册 `/trace/...` 路由，复用 `useProtocolNodes` + `useAnalysisFlow`
- **新增 SSE 事件类型**：协议端在 `python/attp/core/sse/schema.py` 加常量；用户端在 `nodeEvents.ts`（全局）或 `useAnalysisFlow` / 视图内（按需）加 handler 分支
- **新增 IPC 能力**：在 `electron/ipc/` 加处理器（并在 `ipc/index.js` 注册），在 `preload.cjs` 暴露 API，在 `transport.ts` 声明类型
- **新增 Composable**：遵循组合式 API + 模块级单例状态模式
