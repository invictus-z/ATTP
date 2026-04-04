# 前后端通信接口文档

## 项目概述

本文档描述了 Nanobot v3 UI 前端项目与后端系统的通信接口。前端基于 TypeScript + Vite 开发，与后端通过 WebSocket 和 HTTP REST API 进行通信。

## 基础信息

- **后端服务地址**: `localhost:8001`
- **通信协议**: WebSocket + HTTP
- **数据格式**: JSON

---

## 一、WebSocket 接口

### 1. 连接建立

**端点**: `ws://localhost:8001/ws`

**描述**: 建立 WebSocket 连接，用于实时双向通信

**连接时机**: 应用启动时自动连接

```typescript
const ws = new WebSocket('ws://localhost:8001/ws');
```

---

### 2. 客户端发送消息

**方向**: 客户端 → 服务端

**消息格式**:

```json
{
  "type": "chat",
  "content": "消息内容",
  "session_id": "sess_xxxxxxxxxx"
}
```

**字段说明**:

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| type | string | 是 | 消息类型，目前固定为 `"chat"` |
| content | string | 是 | 消息内容，支持普通聊天或指令 |
| session_id | string | 是 | 会话ID，格式为 `sess_` 开头的时间戳 |

**使用场景**:

1. **普通聊天消息**: 用户发送的自然语言消息
2. **节点消息转发**: 通过 Local Agent 向指定节点发送消息

**示例 - 发送普通聊天**:
```javascript
ws.send(JSON.stringify({ 
  type: 'chat', 
  content: '你好，请帮我分析一下',
  session_id: 'sess_1679400000000'
}));
```

**示例 - 发送节点消息**:
```javascript
const instructionText = `请使用 send_message_tool 将以下内容发送给节点 did:example:node123:\n\n消息内容`;
ws.send(JSON.stringify({ 
  type: 'chat', 
  content: instructionText,
  session_id: 'sess_1679400000000'
}));
```

---

### 3. 服务端推送消息

**方向**: 服务端 → 客户端

**消息格式**:

```json
{
  "type": "chat",
  "content": "回复内容",
  "session_id": "sess_xxxxxxxxxx",
  "sender": "发送者名称",
  "metadata": {
    "latency": "45",
    "is_node_message": false,
    "direction": "in"
  }
}
```

**字段说明**:

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| type | string | 是 | 消息类型，固定为 `"chat"` |
| content | string | 是 | 消息内容 |
| session_id | string | 否 | 会话ID，可选 |
| sender | string | 否 | 发送者名称 |
| metadata | object | 否 | 元数据对象 |
| metadata.latency | string | 否 | 延迟时间（毫秒） |
| metadata.is_node_message | boolean | 否 | 是否为节点消息 |
| metadata.direction | string | 否 | 消息方向：`in`（接收）或 `out`（发送） |
| target_node | string | 否 | 目标节点DID |

**消息类型**:

#### 3.1 普通助手回复
```json
{
  "type": "chat",
  "content": "这是助手的回复内容",
  "session_id": "sess_1679400000000",
  "sender": "Local Agent",
  "metadata": {
    "latency": "45"
  }
}
```

#### 3.2 节点消息 - 接收方向
```json
{
  "type": "chat",
  "content": "节点返回的数据",
  "session_id": "LocalBroker:did:example:node123",
  "metadata": {
    "is_node_message": true,
    "direction": "in"
  },
  "target_node": "did:example:node123"
}
```

#### 3.3 节点消息 - 发送方向
```json
{
  "type": "chat",
  "content": "发送给节点的请求",
  "session_id": "LocalBroker:did:example:node123",
  "metadata": {
    "is_node_message": true,
    "direction": "out"
  },
  "target_node": "did:example:node123"
}
```

**客户端处理逻辑**:

1. 根据 `session_id` 匹配对应会话
2. 根据 `metadata.is_node_message` 判断消息类型
3. 根据 `metadata.direction` 确定消息方向（入站/出站）
4. 更新实时日志（RT Logs）显示
5. 根据消息类型渲染到不同区域（聊天区或节点区）

---

## 二、HTTP REST API 接口

### 2.1 获取节点列表

**接口**: `GET /api/nodes`

**端点**: `http://localhost:8001/api/nodes`

**描述**: 获取所有可用的代理节点信息

**请求参数**: 无

**响应示例**:

```json
{
  "agents": [
    {
      "name": "数据存储节点",
      "did": "did:example:storage-node-1",
      "ad_url": "http://192.168.1.100:8081/anp",
      "description": "提供数据存储和检索功能",
      "capabilities": [
        "data_storage",
        "data_retrieval"
      ]
    },
    {
      "name": "安全检查节点",
      "did": "did:example:security-node-1",
      "ad_url": "http://192.168.1.101:8081/anp",
      "description": "提供安全审计和合规检查",
      "capabilities": [
        "security_check",
        "compliance_audit"
      ]
    },
    {
      "name": "计算节点",
      "did": "did:example:compute-node-1",
      "ad_url": "http://192.168.1.102:8081/anp",
      "description": "提供计算服务",
      "capabilities": [
        "compute"
      ]
    }
  ]
}
```

**响应字段说明**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| agents | array | 节点列表 |
| agents[].name | string | 节点名称 |
| agents[].did | string | 节点去中心化标识符（DID） |
| agents[].ad_url | string | 节点广告服务端点URL |
| agents[].description | string | 节点描述 |
| agents[].capabilities | array | 节点能力列表 |

**能力类型（capabilities）**:

- `data_storage` - 数据存储
- `data_retrieval` - 数据检索
- `security_check` - 安全检查
- `compliance_audit` - 合规审计
- `compute` - 计算服务

**前端使用**:
- 用于渲染侧边栏的节点列表
- 根据节点能力显示对应图标（数据库、盾牌、服务器等）
- 点击节点后切换到节点视图

**调用时机**:
- 应用启动后自动调用（延迟 500ms）
- 刷新节点列表时调用

---

### 2.2 获取会话追踪路径

**接口**: `GET /api/traces/{sessionId}`

**端点**: `http://localhost:8001/api/traces/{sessionId}`

**描述**: 获取指定会话的完整通讯追踪路径（Trace Timeline）

**路径参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| sessionId | string | 是 | 会话ID |

**示例**: `http://localhost:8001/api/traces/sess_1679400000000`

**响应示例**:

```json
{
  "Path": [
    {
      "Log": {
        "Timestamp": "2024-03-20T10:30:45.123Z",
        "node_did": "did:example:local-broker",
        "Entry_Hash": "0xabc123...",
        "Genesis_Hash": "0xdef456...",
        "Prev_Hash": "Genesis",
        "Signature": "sig_xyz789...",
        "Content_Snapshot": {
          "Action": "initialize_session"
        }
      }
    },
    {
      "Log": {
        "Timestamp": "2024-03-20T10:30:45.456Z",
        "node_did": "did:example:storage-node-1",
        "Entry_Hash": "0xghi789...",
        "Genesis_Hash": "0xdef456...",
        "Prev_Hash": "0xabc123...",
        "Signature": "sig_abc123...",
        "Content_Snapshot": "User request: 请存储以下数据"
      }
    },
    {
      "Log": {
        "Timestamp": "2024-03-20T10:30:45.789Z",
        "node_did": "did:example:storage-node-1",
        "Entry_Hash": "0xjkl012...",
        "Genesis_Hash": "0xdef456...",
        "Prev_Hash": "0xghi789...",
        "Signature": "sig_def456...",
        "Content_Snapshot": {
          "Action": "store_data",
          "result": "success"
        }
      }
    }
  ]
}
```

**响应字段说明**:

| 字段名 | 类型 | 说明 |
|--------|------|------|
| Path | array | 追踪路径，按时间顺序排列 |
| Path[].Log | object | 单条日志记录 |
| Log.Timestamp | string | ISO 8601 格式的时间戳 |
| Log.node_did | string | 节点DID |
| Log.Entry_Hash | string | 条目哈希值 |
| Log.Genesis_Hash | string | 创世哈希值（会话标识） |
| Log.Prev_Hash | string | 前一条记录的哈希值 |
| Log.Signature | string | 数字签名 |
| Log.Content_Snapshot | object/string | 内容快照 |

**Content_Snapshot 格式**:

1. **对象格式**（带操作类型）:
```json
{
  "Action": "store_data",
  "result": "success"
}
```

2. **字符串格式**（普通消息）:
```json
"User request: 请存储以下数据"
```

**前端使用**:
- 在模态框中展示通讯日志的时间线
- 显示每条记录的时间戳、发送者、接收者、操作类型
- 展示哈希链（Entry_Hash、Prev_Hash、Signature）
- 计算并显示总延迟时间（最后一条 - 第一条时间戳）
- 支持分页显示（每页2条记录）

**调用时机**:
- 用户点击会话菜单中的"查看通讯日志"时调用
- 追踪模态框打开时自动调用

**错误处理**:
- 空路径：显示 "No traces available for this session."
- 请求失败：显示 "Failed to load trace."

---

### 2.3 获取 ANP 配置

**接口**: `GET /api/config`

**端点**: `http://localhost:8001/api/config`

**描述**: 获取当前 ANP 配置（anp_config.json 的内容）

**请求参数**: 无

**响应示例**:

```json
{
  "config": {
    "did": "did:wba:did-server.test:hqy",
    "anpClient": {
      "didDocPath": "~/.nanobot/anp/did.json",
      "didKeyPath": "~/.nanobot/anp/key-1_private.pem",
      "nodeAds": [
        "http://10.8.0.1:6777/agent/ad.json",
        "http://10.8.0.4:8000/agent/ad.json"
      ]
    },
    "anpServer": {
      "name": "Huqy",
      "prefix": "/agent",
      "description": "hqy's personal agent",
      "serverPort": 8000,
      "privateKeyPath": "~/.nanobot/anp/server_private.pem",
      "publicKeyPath": "~/.nanobot/anp/server_public.pem"
    }
  }
}
```

**错误响应（ANP 未启用）**:

```json
{
  "error": "ANP is not enabled",
  "config": null
}
```

**前端使用**:
- Settings 页面加载时调用，填充配置表单

---

### 2.4 更新 ANP 配置

**接口**: `PUT /api/config`

**端点**: `http://localhost:8001/api/config`

**描述**: 部分更新 ANP 配置并保存到文件

**请求体**: 与 anp_config.json 结构相同的 JSON（支持部分更新，deep merge）

```json
{
  "did": "did:wba:did-server.test:newname",
  "anpServer": {
    "name": "New Name",
    "serverPort": 9000
  }
}
```

**响应示例（成功）**:

```json
{
  "success": true,
  "config": { /* 更新后的完整配置 */ }
}
```

**响应示例（失败）**:

```json
{
  "success": false,
  "error": "Validation error: ..."
}
```

**前端使用**:
- Settings 页面点击 "Save Changes" 时调用
- 保存成功后重新加载配置以获取服务端验证后的值

---

## 三、数据流程

### 3.1 聊天会话流程

```
用户输入消息
    ↓
前端创建/更新会话（localStorage）
    ↓
通过 WebSocket 发送消息到后端
    ↓
后端处理（可能调用多个节点）
    ↓
后端通过 WebSocket 推送回复
    ↓
前端更新UI并保存到会话历史
```

### 3.2 节点通讯流程

```
用户在节点视图发送消息
    ↓
前端构造指令（通过 send_message_tool）
    ↓
通过 WebSocket 发送给 Local Agent
    ↓
Local Agent 转发到目标节点
    ↓
后端推送节点消息（metadata.is_node_message = true）
    ↓
前端识别为节点消息并显示在节点视图
    ↓
同时记录到会话的 nodeHistories
```

### 3.3 追踪路径查询流程

```
用户点击"查看通讯日志"
    ↓
打开追踪模态框
    ↓
前端调用 GET /api/traces/{sessionId}
    ↓
后端返回完整的哈希链路径
    ↓
前端渲染时间线UI
    ↓
显示每个跳步的详细信息
```

---

## 四、数据存储

### 前端本地存储

**存储键**: `nanobot_sessions`

**存储位置**: localStorage

**数据结构**:

```typescript
interface ChatSession {
  id: string;                    // 会话ID，格式: sess_xxxxxxxxxx
  title: string;                 // 会话标题
  messages: ChatMessage[];       // 聊天消息记录
  rtLogs?: RtLog[];              // 实时日志
  nodeHistories?: {              // 节点通讯历史
    [nodeDID: string]: NodeMessage[]
  };
  updatedAt: number;             // 最后更新时间戳
  isPinned?: boolean;            // 是否置顶
}

interface ChatMessage {
  role: 'user' | 'agent';        // 消息角色
  content: string;               // 消息内容
  senderOverride?: string;       // 发送者覆盖显示名称
}

interface RtLog {
  senderName: string;            // 发送者名称
  text: string;                  // 日志文本（前50字符）
}

interface NodeMessage {
  role: 'user' | 'agent';        // 消息角色
  text: string;                  // 消息内容
  timeStr: string;               // 时间字符串
}
```

**存储策略**:
- 每次会话更新后自动保存
- 支持会话创建、删除、置顶
- 支持会话搜索过滤

---

## 五、错误处理

### WebSocket 连接

- **连接失败**: 在控制台输出错误日志
- **连接断开**: 不自动重连，需要刷新页面
- **消息发送失败**: 当 `ws.readyState !== WebSocket.OPEN` 时输出警告

### HTTP 请求

- **网络错误**: `catch` 捕获异常并在UI显示错误提示
- **空数据**: 显示友好的空状态提示

---

## 六、安全考虑

1. **WebSocket**: 未使用认证机制，建议在生产环境添加 token 认证
2. **HTTP API**: 未使用认证，建议添加 API Key 或 JWT 认证
3. **CORS**: 后端需要配置允许前端域名的跨域请求
4. **数据传输**: 建议在生产环境使用 `wss://` 和 `https://` 协议
5. **输入验证**: 前端应验证用户输入，防止 XSS 攻击

---

## 七、扩展建议

### 7.1 认证机制

```typescript
// WebSocket 认证
const ws = new WebSocket(`ws://localhost:8001/ws?token=${authToken}`);

// HTTP 请求认证
fetch('http://localhost:8001/api/nodes', {
  headers: {
    'Authorization': `Bearer ${authToken}`
  }
});
```

### 7.2 心跳保活

```typescript
// WebSocket 心跳
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }));
  }
}, 30000);
```

### 7.3 重连机制

```typescript
// 自动重连
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;

function connectWebSocket() {
  const ws = new WebSocket('ws://localhost:8001/ws');
  
  ws.onclose = () => {
    if (reconnectAttempts < maxReconnectAttempts) {
      setTimeout(connectWebSocket, 1000 * Math.pow(2, reconnectAttempts));
      reconnectAttempts++;
    }
  };
}
```

---

## 八、附录

### 8.1 技术栈

- **前端框架**: 原生 TypeScript + Vite
- **UI 库**: Tailwind CSS
- **图标库**: Lucide Icons
- **构建工具**: Vite
- **WebSocket 浏览器API**: 标准 WebSocket API
- **HTTP 客户端**: Fetch API

### 8.2 项目结构

```
src/
├── main.ts           # 应用入口，初始化各模块
├── chat_logic.ts     # 聊天逻辑和 WebSocket 处理
├── logic.ts          # 页面逻辑和 HTTP API 调用
├── style.css         # 全局样式
├── components/       # UI 组件
│   ├── Sidebar.ts    # 侧边栏
│   └── Modals.ts     # 模态框
└── views/            # 页面视图
    ├── HomeView.ts   # 首页（聊天）
    ├── NodeView.ts   # 节点视图
    ├── SessionsView.ts# 会话列表
    └── SettingsView.ts# 设置（ANP 配置管理）
```

### 8.3 环境变量

当前项目未使用环境变量，建议在生产环境中：

```typescript
// src/config.ts
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';
export const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8001/ws';
```

---

## 更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2024-03-20 | 初始版本，记录所有接口文档 |

---

**文档生成时间**: 2024-03-20  
**文档版本**: 1.0  
**项目名称**: Nanobot v3 UI  
**前端地址**: h:\HOME\USTC\竞赛\信安作品赛\nanobot v3\ui