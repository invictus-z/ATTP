# 前后端交互接口文档

> Frontend (`ui/`) ↔ Backend (`python/attp/app/web/app.py` + `api/`)

---

## 1. WebSocket — `/ws`

双向持久连接，承载所有实时聊天与节点通信消息。

### Client → Server

```jsonc
{
  "type": "chat",
  "content": "用户输入文本",
  "session_id": "sess_xxx"        // 前端使用小写
}
```

| 字段 | 说明 |
|------|------|
| `type` | 固定 `"chat"` |
| `content` | 用户消息文本 |
| `session_id` | 当前会话 ID（前端发送时小写，后端兼容 `session_id` / `Session_ID`） |

### Server → Client

```jsonc
{
  "type": "chat",
  "sender": "Local Agent",
  "content": "回复内容",
  "Session_ID": "sess_xxx",
  "metadata": {
    "is_node_message": false,     // 是否为节点间通信消息
    "other_did": "did:wba:...",   // 对端节点 DID
    "direction": "in" | "out",    // 消息方向
    "latency": 120,               // 延迟 (ms)
    "Session_ID": "sess_xxx"      // 路由用会话 ID
  }
}
```

| 场景 | `metadata.is_node_message` | 前端处理 |
|------|---|---|
| Agent 直接回复用户 | `false` / 缺省 | 添加到 Home 聊天区 |
| 节点间通信通知 | `true` | 添加到 RT Log 区 + Node View 区 |

---

## 2. REST API

### 2.1 状态查询

| | |
|---|---|
| **Endpoint** | `GET /api/status` |
| **来源** | `app.py` 内联定义 |
| **用途** | 前端初始化时探测 Agent 是否在线 |

**Response:**

```json
{ "status": "active", "ws_clients": 1 }
```

---

### 2.2 节点列表

| | |
|---|---|
| **Endpoint** | `GET /api/nodes` |
| **来源** | `api/node_status.py` |
| **用途** | 侧边栏动态渲染已注册 Agent 节点 |

**Response:**

```json
{
  "agents": [
    {
      "did": "did:wba:...",
      "name": "Agent Name",
      "description": "...",
      "ad_url": "http://host/agent/ad.json",
      "capabilities": ["data_storage", "security_check"],
      "online": true
    }
  ]
}
```

---

### 2.3 配置管理

| | |
|---|---|
| **来源** | `api/config_setting.py` |

#### 获取配置 `GET /api/config`

| 参数 | 类型 | 说明 |
|------|------|------|
| `refresh` | `bool` (query) | 是否从磁盘重新读取 |

**Response:**

```json
{
  "config": {
    "did": "did:wba:...",
    "attpClient": { "didDocPath": "", "didKeyPath": "", "nodeAds": [] },
    "attpServer": { "name": "", "prefix": "", "description": "", "serverHost": "", "serverPort": 0, "privateKeyPath": "", "publicKeyPath": "" },
    "webApp": { "host": "127.0.0.1", "port": 8001 },
    "tool": { "host": "127.0.0.1", "port": 8002 },
    "heartbeat": { "interval": 30, "timeout": 90, "maxFail": 3 }
  }
}
```

#### 保存配置 `PUT /api/config`

仅写入磁盘，不触发热加载。

**Request Body:** 上述 config 的子集（partial update）。

**Response:**

```json
{ "success": true, "config": { ... } }
```

#### 重载配置 `POST /api/config/reload`

从磁盘重新读取并触发所有组件热重载。

**Response:**

```json
{ "success": true, "config": { ... } }
```

---

### 2.4 行为溯源

| | |
|---|---|
| **来源** | `api/trace.py` |

#### `GET /api/behavior/{session_id}`

查询指定会话的完整行为溯源链。

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | path | 会话 ID |
| `origin_did` | query (可选) | 起源节点 DID |

**Response:**

```json
{
  "session_id": "sess_xxx",
  "origin_did": "did:wba:...",
  "nodes": [
    {
      "hop_count": 0,
      "node_did": "did:wba:...",
      "a": [{ "content": "", "target": "", "timestamp": 0 }],
      "b": [{ "content": "", "target": "", "timestamp": 0 }],
      "c": [{ "content": "", "target": "", "timestamp": 0 }],
      "d": [{ "content": "", "target": "", "timestamp": 0 }]
    }
  ]
}
```

> **field type 语义**: `a`=系统指令, `b`=Agent→User, `c`=User→Agent, `d`=Agent→Agent

---

## 3. 静态资源 (SPA)

| 路由 | 说明 |
|------|------|
| `GET /assets/*` | 前端编译产物（JS/CSS/图片） |
| `GET /{path}` | SPA fallback → `index.html` |

静态文件目录: `python/attp/app/web/static/`

---

## 4. 前端调用汇总

| 触发时机 | 方法 | 端点 | 代码位置 |
|----------|------|------|----------|
| 页面加载 | `GET` | `/api/status` | `chat_logic.ts:32` |
| 页面加载 | `GET` | `/api/nodes` | `logic.ts:471` |
| Settings 页面加载 | `GET` | `/api/config` | `logic.ts:700` |
| 点击 Refresh | `GET` | `/api/config?refresh=true` | `logic.ts:760` |
| 点击 Save | `PUT` | `/api/config` | `logic.ts:844` |
| 点击 Reload | `POST` | `/api/config/reload` | `logic.ts:883` |
| 查看溯源时间线 | `GET` | `/api/traces/{sessionId}` | `logic.ts:183` |
| 发送聊天消息 | WS send | `/ws` | `chat_logic.ts:693` |
| 接收回复/通知 | WS onmessage | `/ws` | `chat_logic.ts:587` |

> ⚠️ `/api/traces/{sessionId}` 在前端 `logic.ts:183` 被调用，但当前后端未注册对应路由，预期返回 `404` 或由 SPA fallback 捕获。