# ATTP 用户端（User Client）代码与功能分析

> 本文档对 `user/` 目录下的所有模块进行全面的代码结构与功能分析。

## 目录

- [1. 概述](#1-概述)
- [2. 模块架构总览](#2-模块架构总览)
- [3. Electron 主进程层](#3-electron-主进程层)
- [4. 传输层 — transport.ts](#4-传输层--transportts)
- [5. ATTP 协议层](#5-attp-协议层)
- [6. Composables 业务逻辑层](#6-composables-业务逻辑层)
- [7. Agent 管理器 — agent_manager.ts](#7-agent-管理器--agent_managerts)
- [8. 视图层](#8-视图层)
- [9. 核心数据流](#9-核心数据流)
- [10. 设计模式与总结](#10-设计模式与总结)

---

## 1. 概述

ATTP 用户端是 ATTP（Agent Trust Trace Protocol）网络中**用户侧**的桌面客户端应用，基于 **Vue 3 + Electron** 构建。它为用户提供了与 ATTP 网络中多个 Agent 交互的统一界面，并完整实现了 ATTP 协议的消息签名、溯源链回传和行为溯源查询能力。

### 核心能力

| 能力 | 说明 |
|------|------|
| **多 Agent 管理** | 同时连接多个 Agent 后端，独立会话上下文，WS 连接复用 |
| **ATTP 协议通信** | U2A/A2U 消息签名 + 双轮回传（BackMessage → Protocol Node） |
| **多曲线密钥支持** | RSA / ECDSA P-256/384/521 / secp256k1 / Ed25519 五种曲线 |
| **行为溯源查询** | 综合视图、行为链路、分析报告、告警四维度溯源展示 |
| **工具节点管理** | 工具节点 CRUD、探活检测、ad.json 服务描述查询 |
| **Electron 桌面应用** | HTTP/WS IPC 代理绕过 CORS、本地文件读写、跨平台打包 |

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
| marked + highlight.js | — | Markdown 渲染 + 代码高亮 |
| DOMPurify | ^3.4 | HTML 安全过滤 |
| lucide-vue-next | ^1.0 | 图标库 |

---

## 2. 模块架构总览

### 2.1 目录结构

```
user/
├── package.json              # 项目配置与依赖
├── index.html                # Vite 入口 HTML
├── vite.config.ts            # Vite 构建配置
├── tsconfig.json             # TypeScript 配置
├── tailwind.config.js        # Tailwind CSS 配置
├── postcss.config.js         # PostCSS 配置
├── electron/                 # Electron 主进程
│   ├── main.js               # 应用入口、窗口创建、生命周期
│   ├── preload.cjs           # 安全桥接（contextBridge）
│   └── ipc/
│       ├── index.js          # IPC 注册中心
│       ├── http.js           # HTTP 请求代理
│       ├── websocket.js      # WebSocket 代理（ws 库）
│       └── file.js           # 文件 I/O（配置/密钥读写）
└── src/
    ├── main.ts               # Vue 应用入口
    ├── App.vue               # 根组件（侧边栏 + 路由视图）
    ├── router.ts             # 路由定义
    ├── style.css             # 全局样式
    ├── markdown.ts           # Markdown 渲染工具
    ├── transport.ts          # 统一通信层（HTTP + WS via IPC）
    ├── agent_manager.ts      # 多 Agent 注册/切换/状态管理
    ├── attp/
    │   ├── key_helper.ts     # PEM 密钥导入（多曲线）
    │   └── protocol.ts       # ATTP 消息构造、签名、回传
    ├── composables/
    │   ├── useAttpProtocol.ts # ATTP 协议核心逻辑
    │   ├── useChat.ts        # 聊天会话 + WS 管理
    │   ├── useNodes.ts       # Agent 网络节点发现
    │   └── useSettings.ts    # Agent 配置 CRUD
    ├── components/
    │   ├── FlowDiagram.vue   # 流程图组件
    │   └── TraceModal.vue    # 溯源弹窗组件
    └── views/
        ├── HomeView.vue      # 聊天主页（溯源节点绑定）
        ├── SessionsView.vue  # 会话历史列表
        ├── SettingsView.vue  # Agent 配置编辑器
        ├── TraceView.vue     # 行为溯源模块
        ├── ToolView.vue      # 工具节点管理
        ├── NodeView.vue      # 网络节点详情
        └── UserConfigView.vue # 用户 ATTP 身份配置
```

### 2.2 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│                     Electron 主进程层                         │
│  main.js · preload.cjs · ipc/{http,websocket,file}.js       │
│  职责：窗口管理、HTTP/WS IPC 代理、文件系统访问                  │
└────────────────────────┬─────────────────────────────────────┘
                         │ contextBridge IPC
┌────────────────────────┴─────────────────────────────────────┐
│                       传输层 (transport.ts)                   │
│  apiFetch() · createWs() · onWsMessage/Open/Close/Error      │
│  职责：统一 HTTP/WS 通信 API，封装 IPC 调用细节                 │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────────┐
│                     ATTP 协议层 (attp/)                       │
│  key_helper.ts · protocol.ts                                 │
│  职责：密钥导入/签名、NodeMessage 构建、BackMessage 回传        │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────────┐
│                 Composables 业务逻辑层                        │
│  useAttpProtocol · useChat · useNodes · useSettings          │
│  职责：ATTP 会话管理、聊天逻辑、节点发现、配置管理               │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────────┐
│               Agent 管理器 (agent_manager.ts)                 │
│  职责：多 Agent 注册表、活跃切换、连接状态、持久化               │
└────────────────────────┬─────────────────────────────────────┘
                         │
┌────────────────────────┴─────────────────────────────────────┐
│                    视图层 (views/*.vue)                        │
│  Home · Sessions · Settings · Trace · Tools · UserConfig     │
│  职责：UI 展示、用户交互、页面路由                              │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 路由结构

```typescript
{ path: '/',          redirect: '/home' }
{ path: '/home',       name: 'home',        component: HomeView }       // 聊天主页
{ path: '/node/:index?', name: 'node',      component: NodeView }       // 网络节点详情
{ path: '/sessions',   name: 'sessions',    component: SessionsView }   // 会话历史
{ path: '/settings',   name: 'settings',    component: SettingsView }   // Agent 配置
{ path: '/trace',      name: 'trace',       component: TraceView }      // 溯源模块
{ path: '/tools',      name: 'tools',       component: ToolView }       // 工具管理
{ path: '/user-config', name: 'user-config', component: UserConfigView } // 用户配置
```

---

## 3. Electron 主进程层

### 3.1 应用入口 — `main.js`（64 行）

Electron 应用的主进程入口，负责窗口创建和生命周期管理。

#### 窗口配置

```javascript
new BrowserWindow({
  width: 1280, height: 800,
  minWidth: 900, minHeight: 600,
  title: 'Nanobot Agent Workspace',
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
| 开发 | `mainWindow.loadURL('http://localhost:5173')` | `--dev` 参数或 `NODE_ENV=development` |
| 生产 | `mainWindow.loadFile('dist/index.html')` | 默认 |

#### 生命周期

- **`whenReady`**：创建窗口 + 注册 IPC Handler
- **`activate`**（macOS）：重建窗口
- **`window-all-closed`**：关闭所有 WS 连接 + 退出应用（非 macOS）

### 3.2 安全桥接 — `preload.cjs`（39 行）

通过 `contextBridge.exposeInMainWorld` 将安全的 IPC API 暴露给渲染进程：

```javascript
window.electronAPI = {
  // 属性
  platform, isElectron,

  // HTTP 代理
  request(url, options) → ipcRenderer.invoke('http-request', ...),

  // WebSocket 代理
  wsConnect(url)       → ipcRenderer.invoke('ws-create', url),
  wsSend(id, data)     → ipcRenderer.send('ws-send', {id, data}),
  wsClose(id)          → ipcRenderer.invoke('ws-close', id),

  // WS 事件监听
  onWsMessage(cb)      → ipcRenderer.on('ws-message', ...),
  onWsOpen(cb)         → ipcRenderer.on('ws-open', ...),
  onWsClose(cb)        → ipcRenderer.on('ws-close-event', ...),
  onWsError(cb)        → ipcRenderer.on('ws-error', ...),

  // 文件操作
  readFile(filepath)       → ipcRenderer.invoke('read-file', filepath),
  readUserConfig()         → ipcRenderer.invoke('read-user-config'),
  saveUserConfig(config)   → ipcRenderer.invoke('save-user-config', config),
  getHomeDir()             → ipcRenderer.invoke('get-home-dir'),
}
```

### 3.3 HTTP 代理 — `ipc/http.js`（50 行）

渲染进程发起的 HTTP 请求通过 IPC 转发到主进程执行，**绕过浏览器 CORS 限制**：

```javascript
ipcMain.handle('http-request', async (_event, { url, options }) => {
  const res = await fetch(url, { method, headers, body })
  // JSON 或 text 解析
  return { ok: res.ok, status: res.status, data }
})
```

**关键设计**：所有 Agent API 调用和协议节点回传都通过此代理执行，使客户端能够访问任意远程服务。

### 3.4 WebSocket 代理 — `ipc/websocket.js`（118 行）

在主进程中维护 WebSocket 连接池，通过 IPC 事件桥接到渲染进程：

#### 连接管理

```javascript
const connections = new Map()  // id → { ws, url }
let nextId = 1                  // 自增连接 ID
```

#### IPC 通道

| IPC 通道 | 方向 | 功能 |
|---------|------|------|
| `ws-create` | 渲染→主 | 创建 WS 连接（返回连接 ID） |
| `ws-send` | 渲染→主 | 发送消息（单向 send，非 invoke） |
| `ws-close` | 渲染→主 | 关闭连接 |
| `ws-message` | 主→渲染 | 消息到达通知（自动 JSON 解析） |
| `ws-open` | 主→渲染 | 连接建立通知 |
| `ws-close-event` | 主→渲染 | 连接关闭通知（含 code + reason） |
| `ws-error` | 主→渲染 | 错误通知 |

#### 消息解析

主进程自动将 WS 消息解析为 JSON 对象后转发给渲染进程：

```javascript
ws.on('message', (rawData) => {
  const str = rawData.toString()
  const payload = JSON.parse(str)  // 自动解析
  mainWindow.webContents.send('ws-message', { id, data: payload })
})
```

#### 连接清理

`closeAllConnections()` 在窗口关闭时调用，遍历并关闭所有活跃 WS 连接。

### 3.5 文件 I/O — `ipc/file.js`（89 行）

提供本地文件系统访问能力，主要用于读取密钥文件和持久化用户配置。

#### 配置文件路径

```
~/.attp/user/config.json
```

#### 默认配置结构

```json
{
  "did": "",
  "didDocPath": "~/.attp/user/did/did.json",
  "didKeyPath": "~/.attp/user/did/key-1_private.pem",
  "protocolNodes": [],
  "toolNodes": [],
  "agents": []
}
```

#### IPC 通道

| IPC 通道 | 功能 | 说明 |
|---------|------|------|
| `read-file` | 读取任意文件 | 支持 `~` 路径展开，用于读取 PEM 密钥 |
| `read-user-config` | 读取用户配置 | 文件不存在时自动创建默认配置，合并缺失字段 |
| `save-user-config` | 保存用户配置 | JSON 格式化写入，自动创建目录 |
| `get-home-dir` | 获取 Home 目录 | 返回 `os.homedir()` |

---

## 4. 传输层 — `transport.ts`

> 文件：`src/transport.ts`（249 行）

传输层是渲染进程中的**统一通信抽象层**，将所有 HTTP 和 WebSocket 通信路由通过 Electron IPC，使渲染进程无需直接处理网络请求。

### 4.1 类型定义

#### 用户 ATTP 配置

```typescript
interface UserAttpConfig {
  did: string
  didDocPath: string
  didKeyPath: string
  protocolNodes: TraceNodeEntry[]    // 协议节点（溯源节点）
  toolNodes: TraceNodeEntry[]        // 工具节点
  agents: { name: string; baseUrl: string; did?: string }[]
}
```

#### WS 连接抽象

```typescript
interface WsConnection {
  readonly id: string
  send: (data: any) => void
  close: () => Promise<void>
}
```

### 4.2 HTTP 通信 — `apiFetch()`

```typescript
async function apiFetch(url: string, options?: RequestOptions): Promise<ApiResponse>
```

通过 `window.electronAPI.request()` 发起 IPC HTTP 请求。所有 Agent API 调用和协议节点回传都通过此函数执行。

### 4.3 WebSocket 通信

#### 创建连接 — `createWs()`

```typescript
async function createWs(url: string): Promise<WsConnection>
```

1. 调用 `window.electronAPI.wsConnect(url)` 创建 IPC WS 连接
2. 返回 `WsConnection` 对象（包含 send/close 方法和连接 ID）
3. 注册全局 WS 事件监听器（仅注册一次）

#### 事件注册

| 函数 | 说明 |
|------|------|
| `onWsMessage(conn, handler)` | 注册消息处理器（Set 存储，支持多处理器） |
| `onWsOpen(conn, handler)` | 注册连接建立处理器 |
| `onWsClose(conn, handler)` | 注册连接关闭处理器（自动清理所有 handler） |
| `onWsError(conn, handler)` | 注册错误处理器 |

#### 全局监听器管理

使用 `Map<string, Set<Handler>>` 结构管理每个连接的事件处理器，确保：
- 一个连接可以有多个处理器
- 连接关闭时自动清理所有处理器
- 全局监听器仅注册一次（`wsListenersRegistered` 标志）

---

## 5. ATTP 协议层

### 5.1 密钥导入 — `key_helper.ts`（246 行）

提供 PEM 格式私钥导入为可签名对象的能力，支持**五种密码学曲线**：

#### 密钥类型体系

```typescript
// secp256k1 私钥包装（Web Crypto API 不原生支持）
class Secp256k1PrivateKey {
  readonly keyType = 'secp256k1'
  readonly rawBytes: Uint8Array  // 32 字节原始私钥
}

// Ed25519 私钥包装
class Ed25519PrivateKey {
  readonly keyType = 'ed25519'
  readonly rawBytes: Uint8Array  // 32 字节原始私钥
}

// 联合类型
type SignableKey = CryptoKey | Secp256k1PrivateKey | Ed25519PrivateKey
```

#### 密钥导入流程 — `importPrivateKeyFromPem()`

```
PEM 字符串
    │
    ├── detectKeyType(pem)
    │   ├── 包含 'RSA' → RSA
    │   ├── DER 含 Ed25519 OID (06 03 2B 65 70) → Ed25519
    │   └── 其他 → EC
    │
    ├── RSA → Web Crypto API importKey('pkcs8', RSA-PSS, SHA-256)
    │
    ├── Ed25519 → extractEd25519RawBytes() → Ed25519PrivateKey
    │              （取 PKCS#8 DER 最后 32 字节）
    │
    └── EC → 依次尝试 Web Crypto API 导入
        ├── P-256 → 成功 → CryptoKey
        ├── P-384 → 成功 → CryptoKey
        ├── P-521 → 成功 → CryptoKey
        └── 全部失败 → isSecp256k1() 检测
            ├── 确认 → extractSecp256k1RawBytes() → Secp256k1PrivateKey
            └── 失败 → 抛出异常
```

#### 各曲线签名方式

| 曲线 | 签名实现 | 输出格式 |
|------|---------|---------|
| RSA (RSA-PSS) | Web Crypto API `sign()` | 原始签名字节 → Base64 |
| ECDSA (P-256/384/521) | `@attp/core signHash()` | 原始签名字节 → Base64 |
| secp256k1 | `@noble/secp256k1 signAsync()` | compact → DER 转换 → Base64 |
| Ed25519 | `@noble/ed25519 sign()` | 原始 64 字节 → Base64 |

### 5.2 协议消息 — `protocol.ts`（220 行）

实现了 ATTP 协议用户端的核心消息构造和发送逻辑。

#### 统一签名函数 — `signWithKey()`

```typescript
async function signWithKey(hash: string, privateKey: SignableKey): Promise<string>
```

根据密钥类型分发到不同的签名实现：

- **CryptoKey**（RSA/ECDSA）：使用 `@attp/core signHash()`
- **Secp256k1PrivateKey**：使用 `@noble/secp256k1`，SHA-256 哈希后签名，输出 DER 格式
- **Ed25519PrivateKey**：使用 `@noble/ed25519`，直接对哈希字符串字节签名

#### Phase 1：构造 NodeMessage — `buildNodeMessage()`

```typescript
async function buildNodeMessage(params: BuildNodeMessageParams): Promise<BuildNodeMessageResult>
```

**流程**：

```
1. 生成 nonce（16 字节随机十六进制字符串）
2. 从 UserSessionManager 获取并递增 hop_count
   - 初始状态 [0,0]：第一条 U2A 消息
   - 后续消息：incrementHopCount()
3. 创建 RecordedHop（sessionId, senderDid, targetDid, content, timestamp, hopCount）
4. 计算 contentHash() 并签名 → sigContent
5. 组装 NodeMessage（protocolUrl + nonce + recordedHop）
6. 返回 { nodeMessage, nonce, recordedHop }
```

**hop_count 机制**：通过 `UserSessionManager` 在 session 级别维护，确保同一会话内消息序号连续递增。

#### Phase 2：发送 BackMessage — `sendBackMessage()`

```typescript
async function sendBackMessage(params: SendBackMessageParams): Promise<boolean>
```

**流程**：

```
1. 创建 BackMessage（protocolUrl, nodeDid=userDid, nonce, recordedHop）
2. 计算 identityHash(userDid, nonce)
   - SHA-256(sorted JSON({"node_did": ..., "nonce": ...}))
3. 签名 identityHash → sigIdentity
4. HTTP POST 到 {protocolUrl}/record
   - 通过 apiFetch()（即 IPC HTTP 代理）
5. 返回协议节点是否确认
```

#### 消息解析 — `parseIncomingNodeMessage()`

```typescript
function parseIncomingNodeMessage(data: any): NodeMessage | null
```

直接调用 `NodeMessage.fromDict(data)` 解析 WS 收到的消息。兼容旧格式（`type: 'chat'`）。

---

## 6. Composables 业务逻辑层

### 6.1 useAttpProtocol — ATTP 协议核心

> 文件：`src/composables/useAttpProtocol.ts`（386 行）

这是 ATTP 用户端最核心的 Composable，管理用户身份、密钥、协议消息的完整生命周期。

#### 单例状态

```typescript
const userConfig = reactive<UserAttpConfig>({ ... })  // 用户配置
let cachedPrivateKey: SignableKey | null = null        // 缓存私钥
const attpSessionManager = new UserSessionManager()    // ATTP 会话管理器
```

所有状态为模块级单例，确保整个应用共享同一份状态。

#### ATTP 会话管理器

`UserSessionManager`（来自 `@attp/core`）在 localStorage 中持久化每个 session 的：
- `protocolNodeAddress`：绑定的溯源节点 URL
- `currentHopCount`：当前 hop_count 值
- `userDid`：用户 DID

#### 配置 I/O

| 函数 | 功能 | 存储位置 |
|------|------|---------|
| `loadUserConfig()` | 加载配置 | `~/.attp/user/config.json`（via IPC） |
| `saveUserConfig()` | 保存配置 | 同上（深拷贝剥离 Vue reactive proxy） |

#### 密钥管理 — `loadPrivateKey()`

```typescript
async function loadPrivateKey(): Promise<SignableKey | null>
```

- 从 `didKeyPath` 读取 PEM 文件（via IPC）
- 调用 `importPrivateKeyFromPem()` 导入
- **缓存机制**：路径不变时复用已导入的密钥

#### U2A 发送流程 — `sendMessageWithAttp()`

```typescript
async function sendMessageWithAttp(
  content: string, sessionId: string, targetDid: string
): Promise<SendMessageResult>
```

**完整流程**：

```
1. 校验：User DID 已配置
2. 获取 protocolUrl（session 绑定优先）
3. 加载私钥
4. buildNodeMessage() → 构造签名后的 NodeMessage
5. ========== 时序规则：先回传协议节点 ==========
6. sendBackMessage() → HTTP POST 到协议节点 /record
7. 等待协议节点确认
8. 确认后返回 NodeMessage dict（由调用方通过 WS 发送给 Agent）
```

#### A2U 接收处理 — `handleReceivedNodeMessage()`

```typescript
async function handleReceivedNodeMessage(incomingData: any): Promise<boolean>
```

**完整流程**：

```
1. parseIncomingNodeMessage() → 解析 WS 收到的 NodeMessage
2. 从 RecordedHop 提取 hop_count 并更新到 SessionManager
3. 校验：User DID 已配置 + 私钥可加载
4. sendBackMessage() → 异步回传协议节点（fire-and-forget）
```

#### 会话-溯源节点绑定

| 函数 | 功能 |
|------|------|
| `bindSessionProtocolUrl(sessionId, protocolUrl)` | 绑定 session 到指定溯源节点 |
| `getSessionProtocolUrl(sessionId)` | 获取 session 绑定的溯源节点 URL |
| `clearSessionProtocolUrl(sessionId)` | 清除绑定 |

#### 节点管理

| 函数 | 管理对象 |
|------|---------|
| `addProtocolNode / updateProtocolNode / removeProtocolNode / saveProtocolNodes` | 协议节点（溯源节点） |
| `saveToolNodes` | 工具节点 |
| `addAgent / removeAgent` | Agent |

### 6.2 useChat — 聊天会话管理

> 文件：`src/composables/useChat.ts`（805 行）

这是最复杂的 Composable，管理多 Agent 聊天、WebSocket 连接、会话持久化等全部聊天相关逻辑。

#### 多 Agent 状态管理

```typescript
const agentSessionsMap = new Map<string, ChatSession[]>()      // agentId → sessions
const agentCurrentSessionMap = new Map<string, string | null>() // agentId → currentSessionId
const agentWsMap = new Map<string, WsConnection>()              // agentId → WS连接
const agentWsConnectedMap = new Map<string, boolean>()           // agentId → 连接状态
const connectingAgents = new Set<string>()                       // 正在连接的 agent
const wsUrlToAgentId = new Map<string, string>()                 // WS URL → agentId 去重
```

#### 会话数据结构

```typescript
interface ChatSession {
  id: string
  title: string
  messages: ChatMessage[]
  rtLogs?: { senderName: string; text: string }[]
  nodeHistories?: { [targetNode: string]: { role; text; timeStr }[] }
  updatedAt: number
  isPinned?: boolean
  isUnread?: boolean
  unreadCount?: number
  senderName?: string
}
```

#### 会话持久化

- 每个 Agent 的会话独立存储在 `localStorage`，key 为 `attp_sessions_{agentId}`
- Agent 切换时：flush 当前 Agent 会话 → 加载目标 Agent 会话
- 后台 Agent 收到消息时：直接操作其对应的会话数组并持久化

#### WebSocket 连接管理

##### 连接策略

```
connectAllAgents()
    │
    ├── 按 WS URL 分组（URL 去重）
    │   同一 URL 的多个 Agent 共享一条 WS 连接
    │
    ├── 第一个 Agent：实际创建 WS 连接
    │   connectAgentWs(agentId)
    │   → createWs(wsUrlForAgent(agent, '/ws'))
    │   → 注册 open/close/error/message 处理器
    │
    └── 其余 Agent：复用已有连接
        共享 WsConnection 对象
        各自注册独立的 message handler
```

##### 消息处理 — `createMessageHandler(agentId)`

```
WS 收到消息
    │
    ├── JSON 解析
    ├── 尝试 NodeMessage.fromDict(data) 解析
    │   ├── 成功 → 提取 RecordedHop（content, sessionId, senderDid）
    │   │         → addMessageToAgentSession()
    │   │         → rtLog 记录
    │   │         → handleReceivedNodeMessage(data)  // 异步回传
    │   └── 失败 → 兼容旧格式（type: 'chat'）
    │
    ├── 区分活跃/后台 Agent
    │   ├── 活跃 Agent → 操作 reactive sessions
    │   └── 后台 Agent → 操作独立 session 数组 + 标记未读
    │
    └── 未读计数
        后台 Agent 收到消息时递增 unreadCount
```

##### 发送消息 — `sendMessage()`

```
用户输入 → sendMessage()
    │
    ├── 校验：当前 session 已绑定溯源节点
    ├── addMessageToSession() → 添加用户消息到会话
    ├── sendMessageWithAttp() → 构造签名 NodeMessage + 回传协议节点
    │   ├── 失败 → 阻止发送（ATTP-only 模式）
    │   └── 成功 → 返回 nodeMessageDict
    └── conn.send(JSON.stringify(nodeMessageDict)) → 通过 WS 发送给 Agent
```

#### 会话操作

| 操作 | 函数 | 说明 |
|------|------|------|
| 创建会话 | `createSession(title, protocolUrl?)` | 可选绑定溯源节点 |
| 加载会话 | `loadSession(id)` | 切换当前会话，清除未读 |
| 删除会话 | `deleteSessionRecord(id)` | 删除并自动切换 |
| 置顶 | `pinSessionRecord(id)` | 切换置顶状态 |
| 批量删除 | `batchDeleteSessions()` | 批量操作 |
| 批量置顶/取消 | `batchPinSessions() / batchUnpinSessions()` | 批量操作 |

### 6.3 useNodes — 网络节点发现

> 文件：`src/composables/useNodes.ts`（35 行）

从活跃 Agent 的 `/api/nodes` 端点获取其已知的网络节点列表：

```typescript
interface AgentNode {
  name: string
  did: string
  ad_url: string
  description: string
  capabilities: string[]   // 如 'data_storage', 'security_check'
  online: boolean
}
```

节点图标根据 `capabilities` 映射：
- `data_storage` → Database 图标
- `security_check` → ShieldCheck 图标
- 其他 → Server 图标

### 6.4 useSettings — Agent 配置管理

> 文件：`src/composables/useSettings.ts`（237 行）

管理**活跃 Agent** 的 ATTP 网络配置（注意：这是 Agent 端配置，不是 User 端配置）。

#### 配置结构

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
| 加载 | `GET /api/config` | 从 Agent 读取当前配置 |
| 保存 | `PUT /api/config` | 保存到磁盘（不立即生效） |
| 刷新 | `GET /api/config?refresh=true` | 从磁盘重新读取 |
| 重载 | `POST /api/config/reload` | 保存 + 热重载生效 |

---

## 7. Agent 管理器 — `agent_manager.ts`

> 文件：`src/agent_manager.ts`（221 行）

管理用户连接的多个 Agent 后端，每个 Agent 有独立的 baseUrl、DID、WebSocket 连接和会话上下文。

### 7.1 数据结构

```typescript
interface AgentEntry {
  id: string                   // 'agent_' + timestamp + random
  name: string                 // 显示名称
  baseUrl: string              // 如 "http://192.168.1.50:8001"
  did?: string                 // Agent 的 DID 身份
  status: 'active' | 'offline' | 'connecting'
}
```

### 7.2 核心功能

| 功能 | 函数 | 说明 |
|------|------|------|
| 获取列表 | `getAgents()` | 返回所有已注册 Agent |
| 获取活跃 | `getActiveAgent()` | 返回当前活跃 Agent |
| 切换活跃 | `setActiveAgent(id)` | 切换 + 触发回调通知 |
| 添加 Agent | `addAgent(name, baseUrl, did?)` | 注册 + 自动激活（首个）+ 测试连接 |
| 删除 Agent | `removeAgent(id)` | 删除 + 自动切换到下一个 |
| 重命名 | `renameAgent(id, newName)` | 更新显示名称 |
| 状态更新 | `updateAgentStatus(id, status)` | 更新连接状态 |

### 7.3 URL 构建

```typescript
apiUrl(path)         // → agent.baseUrl + path（如 /api/status）
wsUrlForAgent(agent, path)  // → http → ws 协议替换 + path
```

### 7.4 持久化

Agent 列表存储在 `~/.attp/user/config.json` 的 `agents` 字段中：

```
addAgent/removeAgent/renameAgent
    → persist()
    → readUserConfig() + 修改 agents + saveUserConfig()
```

### 7.5 Agent 加载流程

```typescript
async function loadAgents(): Promise<void>
```

1. 从 `readUserConfig()` 读取 agents 列表
2. 为每个 Agent 生成稳定 ID（`agent_{index}_{baseUrl_hash}`）
3. 恢复活跃 Agent（默认第一个）
4. 并发测试所有 Agent 连接状态

---

## 8. 视图层

### 8.1 HomeView — 聊天主页

> 文件：`src/views/HomeView.vue`（357 行）

聊天主页是用户与 Agent 交互的主界面，包含聊天区域和溯源节点绑定机制。

#### 核心功能

| 功能 | 说明 |
|------|------|
| 聊天消息展示 | 按日期分组，Markdown 渲染 Agent 回复 |
| New Chat | 创建新会话并选择溯源节点（单节点自动绑定） |
| 溯源节点绑定 | 创建会话时必须选择溯源节点，会话期间锁定 |
| 实时网络面板 | 右侧面板显示实时日志（rtLogs） |
| 协议节点选择弹窗 | 支持新建会话选择和补选两种模式 |

#### 溯源节点绑定流程

```
handleNewChat()
    │
    ├── 只有 1 个节点 → 直接创建并绑定
    └── 多个节点 → 弹出选择弹窗
        │
        ├── isCreateMode = true  → 创建新会话 + 绑定
        └── isCreateMode = false → 绑定到当前会话

needsProtocolBinding watch:
    当 needsProtocolBinding = true 且有可用节点时
    → 自动弹出选择弹窗（补选模式）
```

#### 消息发送拦截

发送消息前必须满足：
1. 当前 session 已绑定溯源节点（`getSessionProtocolUrl` 非空）
2. ATTP 协议已初始化
3. WebSocket 已连接

### 8.2 SessionsView — 会话历史

> 文件：`src/views/SessionsView.vue`（276 行）

会话历史列表，支持搜索、置顶、删除和溯源跳转。

#### 核心功能

| 功能 | 说明 |
|------|------|
| 分区展示 | 置顶会话 + 最近历史 |
| 搜索 | 按标题过滤 |
| 批量管理 | 全选/置顶/取消置顶/删除 |
| 溯源跳转 | 跳转到溯源模块并携带 sessionId + protocolUrl 参数 |
| 未读标记 | 红色气泡显示未读消息数 |

#### 溯源跳转

```typescript
handleTrace(id) → router.push(`/trace?sessionId=${id}&protocolNodeUrl=${url}`)
```

### 8.3 SettingsView — Agent 配置

> 文件：`src/views/SettingsView.vue`（253 行）

管理**活跃 Agent** 的完整 ATTP 网络配置，包含 7 个配置组：

| 配置组 | 字段 | 说明 |
|--------|------|------|
| DID Identity | did | Agent 的 DID 标识 |
| ATTP Client | didDocPath, didKeyPath, nodeAds[] | 客户端连接配置 |
| ATTP Server | name, prefix, host, port, keys | 服务端配置 |
| Web App | host, port | Web 界面配置 |
| Tool | host, port, toolNodeAds[] | 工具服务配置 |
| Heartbeat | interval, timeout, maxFail | 心跳检测配置 |
| Protocol Node | enabled, configPath | 协议节点配置 |

#### 操作按钮

- **Refresh**：从磁盘重读配置文件
- **Save Changes**：保存到磁盘（不立即生效）
- **Reload**：保存 + 热重载应用

### 8.4 TraceView — 溯源模块

> 文件：`src/views/TraceView.vue`（1079 行）

这是功能最复杂的视图，提供完整的**行为溯源查询、意图追踪和告警**展示。

#### 核心功能

| 功能 | 说明 |
|------|------|
| 溯源节点管理 | CRUD + 探活检测（复用 User Config 的 protocolNodes） |
| 综合视图 | 统计卡片 + 意图信息 + 行为链路概览 + 告警摘要 |
| 行为溯源 | 按 hop 分组的详细行为记录（A2T/A2U/U2A/A2A/T2A） |
| 分析报告 | 分批分析结果 + 节点裁决（verdict + taint_score） |
| 告警 | 可疑行为告警 + 可疑节点详情 |
| 意图追踪触发 | 手动触发协议节点的意图追踪 |

#### 数据结构

```typescript
// 行为链路条目（API 返回的扁平格式）
interface BehaviorChainEntry {
  hop_count: number[]      // [a2a_count, intra_count]
  field_type: string       // A2T | A2U | U2A | A2A | T2A
  sender_type: string
  sender_did: string
  target_did: string
  content: string
  timestamp: string | null
}

// 按节点分组后的结构
interface HopNode {
  hop_count: number[]
  node_did: string
  A2T: BehaviorEntry[]   // Agent → Tool
  A2U: BehaviorEntry[]   // Agent → User
  U2A: BehaviorEntry[]   // User → Agent
  A2A: BehaviorEntry[]   // Agent → Agent
  T2A: BehaviorEntry[]   // Tool → Agent
}
```

#### 数据转换 — `transformChainToNodes()`

将 API 返回的扁平 chain 按 `(hop_count, sender_did)` 分组，转换为按节点组织的结构，并按 hop_count 排序。

#### 查询参数自动填充

从路由 query 参数自动填充 `sessionId` 和 `protocolNodeUrl`（来自 SessionsView 的"溯源"按钮跳转），延迟 2 秒后自动执行查询（等待节点探活完成）。

#### 消息类型配色

| 类型 | 标签 | 颜色 |
|------|------|------|
| A2T | Agent→Tool | 蓝色 |
| A2U | Agent→User | 紫色 |
| U2A | User→Agent | 绿色 |
| A2A | Agent→Agent | 橙色 |
| T2A | Tool→Agent | 青色 |

### 8.5 ToolView — 工具节点管理

> 文件：`src/views/ToolView.vue`（461 行）

管理用户已知的工具节点，支持探活检测和服务描述查询。

#### 核心功能

| 功能 | 说明 |
|------|------|
| 工具节点 CRUD | 添加/编辑/删除，持久化到 User Config |
| 探活检测 | 请求 `{url}/health` 判断在线状态 |
| ad.json 查询 | 请求 `{url}/ad.json` 或 `{url}/attp/ad.json` |
| 工具列表展示 | 显示 ad.json 中的 mcp_tools 列表 |

#### 存储位置

工具节点列表存储在 `~/.attp/user/config.json` 的 `toolNodes` 字段。

### 8.6 UserConfigView — 用户身份配置

> 文件：`src/views/UserConfigView.vue`（179 行）

管理**用户端自身**的 ATTP 身份配置。

#### 配置项

| 配置项 | 字段 | 说明 |
|--------|------|------|
| User DID | `did` | 用户的 DID 标识 |
| DID Document Path | `didDocPath` | DID 文档文件路径 |
| Private Key Path | `didKeyPath` | PEM 私钥文件路径 |
| 协议节点 | `protocolNodes[]` | 溯源节点列表（name + url） |
| Known Agents | `agents[]` | 已知 Agent 列表（name + did + baseUrl） |

#### 与 SettingsView 的区别

| 维度 | UserConfigView | SettingsView |
|------|---------------|-------------|
| 配置对象 | 用户自身（User） | 活跃 Agent |
| 存储位置 | `~/.attp/user/config.json` | Agent 端 `config.json` |
| 读写方式 | IPC 直接读写文件 | HTTP API 调用 Agent |
| 功能 | DID/密钥/节点/Agent 管理 | Agent 网络配置 |

### 8.7 NodeView — 网络节点详情

> 文件：`src/views/NodeView.vue`

展示活跃 Agent 已知的网络节点详情，通过 `useNodes` composable 获取节点列表。

---

## 9. 核心数据流

### 9.1 应用启动流程

```
App.vue onMounted()
    │
    ├── loadUserConfig()                     // 加载 ~/.attp/user/config.json
    │   ├── did, didKeyPath, protocolNodes, agents
    │   └── 缓存清除（如密钥路径变更）
    │
    ├── loadAgents()                         // 从 config.agents 恢复 Agent 列表
    │   ├── 生成稳定 Agent ID
    │   ├── 设置活跃 Agent（第一个）
    │   └── 并发测试所有 Agent 连接状态
    │
    ├── initAgentContext()                    // 初始化聊天上下文
    │   ├── flush 前一个 Agent 的会话
    │   ├── 加载活跃 Agent 的会话
    │   ├── 检查/建立 WS 连接
    │   └── 检查溯源节点绑定
    │
    ├── connectAllAgents()                   // 建立 WS 连接
    │   ├── 按 WS URL 分组去重
    │   ├── 每个 URL 创建一条连接
    │   └── 多 Agent 共享同 URL 连接
    │
    └── fetchNodes()                         // 获取网络节点列表
```

### 9.2 U2A 消息发送完整流程

```
用户输入文本 → handleSend()
    │
    ├── sendMessage() [useChat]
    │   ├── 校验 session 绑定了溯源节点
    │   ├── addMessageToSession() → 添加用户消息
    │   └── sendMessageWithAttp() [useAttpProtocol]
    │       │
    │       ├── 校验 User DID + protocolUrl
    │       ├── loadPrivateKey() → 从 PEM 导入可签名密钥
    │       │
    │       ├── buildNodeMessage() [protocol.ts]
    │       │   ├── 生成 nonce
    │       │   ├── 从 SessionManager 获取 hop_count
    │       │   ├── 创建 RecordedHop
    │       │   ├── 计算 contentHash() + 签名 → sigContent
    │       │   └── 组装 NodeMessage
    │       │
    │       ├── ===== 时序规则：先回传协议节点 =====
    │       │
    │       ├── sendBackMessage() [protocol.ts]
    │       │   ├── 创建 BackMessage
    │       │   ├── 计算 identityHash(userDid, nonce) + 签名
    │       │   └── HTTP POST → {protocolUrl}/record
    │       │       └── apiFetch() → IPC → electron HTTP 代理
    │       │
    │       └── 返回 nodeMessageDict
    │
    └── conn.send(JSON.stringify(nodeMessageDict))
        └── IPC WS 代理 → Agent
```

### 9.3 A2U 消息接收完整流程

```
Agent → WS → Electron WS 代理 → IPC → 渲染进程
    │
    ├── createMessageHandler(agentId)
    │   ├── JSON 解析
    │   ├── NodeMessage.fromDict(data)
    │   │   ├── 提取 content, sessionId, senderDid
    │   │   ├── addMessageToAgentSession() → 更新聊天会话
    │   │   └── rtLog 记录
    │   │
    │   └── handleReceivedNodeMessage() [异步，不阻塞渲染]
    │       ├── parseIncomingNodeMessage()
    │       ├── 更新 SessionManager 的 hop_count
    │       ├── loadPrivateKey()
    │       └── sendBackMessage() → HTTP POST 到协议节点
    │
    └── UI 更新（Vue reactive）
```

### 9.4 会话-溯源节点绑定机制

```
创建新会话
    │
    ├── handleNewChat()
    │   ├── protocolNodes.length === 1 → 自动绑定唯一节点
    │   └── protocolNodes.length > 1 → 弹出选择弹窗
    │       │
    │       └── confirmNodeSelection()
    │           ├── isCreateMode → createSession('New Chat', url)
    │           └── 补选模式 → bindSessionProtocolUrl(sessionId, url)
    │               └── attpSessionManager.save() + saveToStorage()
    │
    ├── 发送消息校验
    │   └── getSessionProtocolUrl(sessionId) 必须非空
    │
    └── 溯源查询跳转
        └── SessionsView → /trace?sessionId=...&protocolNodeUrl=...
```

### 9.5 多 Agent 并发连接架构

```
connectAllAgents()
    │
    ├── 按 WS URL 分组
    │   Agent A (ws://host:8001/ws) ─┐
    │   Agent B (ws://host:8001/ws) ─┤ 同一 URL
    │   Agent C (ws://host:8002/ws) ─┘ 不同 URL
    │
    ├── URL Group 1: ws://host:8001/ws
    │   ├── Agent A: connectAgentWs() → createWs() → 注册 handler
    │   └── Agent B: 复用 Agent A 的连接 → 注册独立 handler
    │
    └── URL Group 2: ws://host:8002/ws
        └── Agent C: connectAgentWs() → createWs() → 注册 handler
```

---

## 10. 设计模式与总结

### 10.1 设计模式应用

| 设计模式 | 应用位置 | 说明 |
|---------|---------|------|
| **Composable** | `useAttpProtocol`, `useChat`, `useNodes`, `useSettings` | Vue 3 组合式 API，封装复用逻辑 |
| **单例状态** | 模块级 `reactive` / `Map` | 确保整个应用共享同一份状态 |
| **IPC 代理** | Electron preload + ipcMain | 绕过浏览器限制，统一通信方式 |
| **策略模式** | `SignableKey` + `signWithKey()` | 多曲线签名的统一抽象 |
| **连接池** | `agentWsMap` + URL 去重 | 多 Agent 共享 WS 连接 |
| **观察者模式** | `onAgentSwitch()` 回调 | Agent 切换时通知所有订阅者 |
| **模板方法** | `createMessageHandler(agentId)` | 闭包捕获 agentId，统一消息处理流程 |

### 10.2 安全机制

| 安全能力 | 实现方式 |
|---------|---------|
| **DID 身份标识** | 用户持有唯一 DID，配置在 `~/.attp/user/config.json` |
| **多曲线内容签名** | 对 `RecordedHop.contentHash()` 签名，支持 5 种曲线 |
| **身份签名** | 对 `identityHash(userDid, nonce)` 签名，证明消息来源 |
| **双轮回传** | 发送和接收消息后都回传 BackMessage 到协议节点 |
| **私钥缓存** | 内存中缓存已导入的私钥，避免重复 I/O 和解析 |
| **HTML 安全过滤** | DOMPurify 过滤 Markdown 渲染结果 |
| **Electron 安全** | nodeIntegration: false + contextIsolation: true + contextBridge |
| **溯源绑定锁定** | 会话创建时绑定溯源节点，会话期间不可更改 |

### 10.3 分层架构优势

1. **关注点分离**：Electron Shell（网络/文件） → 传输层（IPC 抽象） → 协议层（签名/消息） → 业务层（会话/配置） → 视图层（UI）
2. **浏览器兼容**：所有网络请求通过 IPC 代理，无 CORS 问题
3. **多曲线支持**：统一的 `SignableKey` 接口，运行时自动检测密钥类型
4. **多 Agent 并发**：独立会话上下文 + WS 连接复用，高效管理
5. **ATTP-only 模式**：所有消息必须通过 ATTP 协议签名和回传，无绕过路径

### 10.4 配置文件汇总

| 配置文件 | 路径 | 管理者 |
|---------|------|--------|
| 用户 ATTP 配置 | `~/.attp/user/config.json` | Electron IPC + `useAttpProtocol` |
| Agent 网络配置 | Agent 端 `config.json` | `useSettings`（via Agent HTTP API） |
| 会话历史 | `localStorage` (`attp_sessions_{agentId}`) | `useChat` |
| ATTP 会话数据 | `localStorage` | `UserSessionManager` |
| 活跃 Agent ID | `localStorage` (`attp_active_agent`) | `agent_manager` |

### 10.5 扩展性

- **新增加密曲线**：在 `key_helper.ts` 中添加新的密钥包装类和导入逻辑，在 `protocol.ts` 的 `signWithKey()` 中添加签名分支
- **新增视图/功能**：添加 Vue 组件到 `views/`，在 `router.ts` 注册路由，在 `App.vue` 侧边栏添加导航项
- **新增 IPC 能力**：在 `electron/ipc/` 添加处理器，在 `preload.cjs` 暴露 API，在 `transport.ts` 声明类型
- **新增 Composable**：遵循 Vue 3 组合式 API 模式，使用模块级单例状态