# ATTP 工具节点扩展方案

## 1. 概述

ATTP 原有架构中，只有 Agent 作为网络节点，通过渠道插件接入 ATTP 协议。本次扩展将**工具（Tool）也视为网络节点**，使工具服务成为 ATTP 网络中的一等公民，具备独立的 DID 身份、溯源链签名和行为追踪能力。

### 设计目标

- **工具即节点**：工具服务拥有独立的 DID，可被 Agent 发现、调用和溯源
- **MCP 兼容**：适配 MCP（Model Context Protocol）协议，保持与现有 Agent MCP Client 的兼容
- **完整溯源**：新增 `T2A`（Tool → Agent）行为类型，实现工具调用全链路追踪
- **零侵入 SDK**：工具开发者只需使用 `attp.sdk.tools` 即可将现有 MCP 工具包装为 ATTP 工具节点

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent (nanobot)                          │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │               MCP Client (内置)                          │ │
│  └────────────────────────┬────────────────────────────────┘ │
│                           │ MCP SSE                          │
│  ┌────────────────────────▼────────────────────────────────┐ │
│  │                MCPToolBridge                            │ │
│  │  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐ │ │
│  │  │send_msg  │  │call_tool_node│  │list_tool_nodes    │ │ │
│  │  │(原有)    │  │(新增)        │  │(新增)             │ │ │
│  │  └──────────┘  └──────┬───────┘  └───────────────────┘ │ │
│  │                        │ ATTP tool_request               │ │
│  └────────────────────────┼────────────────────────────────┘ │
│                           │                                   │
│  ┌────────────────────────┴────────────────────────────────┐ │
│  │              ATTP Client / Tracer                        │ │
│  │  (溯源链签名 + A2T 行为记录)                              │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │ HTTP
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   ATTPToolNode (工具节点)                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              FastAPI (ATTP 端点)                         │ │
│  │  POST /attp     → tool_request / record                 │ │
│  │  GET  /attp/ad.json                                     │ │
│  │  GET  /attp/health                                      │ │
│  └────────────────────────┬────────────────────────────────┘ │
│                           │                                   │
│  ┌────────────────────────▼────────────────────────────────┐ │
│  │            ToolHandler 路由 + 执行                       │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐              │ │
│  │  │search    │  │translate │  │analyze   │  ...          │ │
│  │  └──────────┘  └──────────┘  └──────────┘              │ │
│  └────────────────────────┬────────────────────────────────┘ │
│                           │                                   │
│  ┌────────────────────────▼────────────────────────────────┐ │
│  │              ATTP Tracer                                 │ │
│  │  (溯源链验签 + T2A 行为记录 + ad.json 生成)               │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块划分

```
python/attp/
├── app/                          # Agent 侧应用层
│   └── tools/
│       ├── mcp_tool_bridge.py    # 🆕 MCP Server + ATTP Tool Client 桥接器
│       └── send_message_tool.py  # 原有消息转发工具
├── sdk/                          # 工具开发者 SDK
│   └── tools/
│       ├── tool_node.py          # 🆕 Mode 0: ATTPToolNode 原生工具节点
│       ├── mcp_adapter.py        # 🆕 Mode 1: MCPToATTPAdapter 包装已有 MCP Server
│       ├── mcp_proxy.py          # 🆕 Mode 2: MCPProxyToolNode MCP Config 代理
│       ├── handler.py            # 🆕 ToolHandler 处理器抽象
│       ├── tool_ad.py            # 🆕 ad.json 构建器
│       └── __init__.py           # 🆕 包导出
└── core/                         # 核心协议层（未改动）
    ├── authentication/           # 身份认证
    ├── provenance/               # 溯源链
    ├── sessions/                 # 会话管理
    │   └── node_message.py       # 行为类型已更新
    ├── storage/                  # 持久化
    └── tracer.py                 # 门面类
```

---

## 3. 行为类型体系

### 3.1 类型重构

原有的单字符类型（`a`/`b`/`c`/`d`）已重构为语义化命名：

| 旧值 | 新值 | 方向 | 含义 |
|------|------|------|------|
| `"a"` | `"A2T"` | Agent → Tool | Agent 调用工具 |
| `"b"` | `"A2U"` | Agent → User | Agent 向用户发送回复 |
| `"c"` | `"U2A"` | User → Agent | 用户向 Agent 发送消息 |
| `"d"` | `"A2A"` | Agent → Agent | Agent 之间互发消息 |
| *(预留)* | `"T2A"` | Tool → Agent | 工具返回结果 |

### 3.2 新增 T2A 行为类型

`T2A`（Tool → Agent）是本次扩展的核心新增类型，用于记录工具节点向 Agent 返回结果的完整行为：

```
Agent 调用工具 (A2T) → 工具执行并返回 (T2A) → Agent 收到结果
```

### 3.3 改动文件

| 文件 | 改动内容 |
|------|----------|
| `core/sessions/node_message.py` | 文档注释和 field_type 注释更新 |
| `app/client.py` | `"a"` → `"A2T"`, `"d"` → `"A2A"` |
| `app/web/app.py` | `"b"` → `"A2U"`, `"c"` → `"U2A"` |
| `app/web/api/trace.py` | API 响应键名从 a/b/c/d 改为 A2T/A2U/U2A/A2A/T2A |
| `docs/sum.md` | 全面更新 |
| `docs/core-analysis.md` | 全面更新 |

---

## 4. MCPToolBridge — Agent 侧桥接器

**文件**：`python/attp/app/tools/mcp_tool_bridge.py`

### 4.1 定位

MCPToolBridge 在 Agent 侧同时充当两个角色：

| 角色 | 说明 |
|------|------|
| **MCP SSE Server** | 暴露 MCP 工具给 nanobot（Agent 内置 MCP Client）连接 |
| **ATTP Tool Client** | 将工具调用通过 ATTP 协议发送到远程工具节点 |

### 4.2 MCP 工具注册方式

MCPToolBridge 采用**动态注册**机制：

- **静态工具**：`send_message_tool`（原有消息转发功能）
- **动态工具**：通过 `discover_tool_node()` / `register_tool_node()` 发现远程工具节点后，
  自动将节点的每个工具注册为独立 MCP 工具，工具的 `name` 和 `description` 完整传入 LLM 上下文

动态注册的 MCP 工具名格式：`{original_tool_name}@{node_name}`，避免不同节点间的同名工具冲突。

例如，发现一个名为 `search-service` 的工具节点提供 `search` 工具后，LLM 上下文中会出现：

```
search@search-service: [远程工具 | 节点: search-service (did:wba:...)]
搜索知识库

参数说明：
- query: string (必填) — 搜索关键词
- limit: integer — 返回数量
- chat_id: 当前会话ID
```

### 4.3 核心流程：call_tool_node

```
1. 记录 A2T 行为（Agent → Tool）到 NodeMessage + SQLite
2. 构建 ATTP 元数据（Session_ID, Tool_Name, Arguments）
3. 追加溯源跳（hop_hash + 签名）
4. HTTP POST tool_request 到工具节点的 ATTP 端点
5. 接收 tool_response（含 T2A 溯源）
6. 返回结果给 Agent
```

### 4.4 工具节点发现

支持两种方式注册远程工具节点：

| 方式 | API |
|------|-----|
| 手动注册 | `bridge.register_tool_node(ToolNodeInfo(...))` |
| ad.json 发现 | `await bridge.discover_tool_node(ad_url)` |

---

## 5. ATTP Tool SDK — 三种包装模式

**目录**：`python/attp/sdk/tools/`

SDK 提供三种包装模式，覆盖不同场景：

| 模式 | 类名 | 场景 | 签名方 |
|------|------|------|--------|
| 原生 ATTP | `ATTPToolNode` | 从零开发工具 | 工具侧 |
| MCP Server 包装 | `MCPToATTPAdapter` | 已有 FastMCP 实例 | 工具侧（同进程） |
| MCP Config 代理 | `MCPProxyToolNode` | 外部 MCP 服务配置 | 本地代理 |

### 5.1 Mode 0: ATTPToolNode — 原生 ATTP

从零开发，用 `@node.tool()` 装饰器逐个注册工具。

```python
from attp.sdk.tools import ATTPToolNode

node = ATTPToolNode(
    did="did:wba:tool.local:search-service",
    name="search-service",
    private_key_path="key.pem",
    port=9000,
)

@node.tool("search", "搜索知识库", {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索关键词"},
        "limit": {"type": "integer", "description": "返回数量", "default": 10},
    },
    "required": ["query"],
})
async def search(query: str, limit: int = 10):
    return {"results": [f"result for '{query}' #{i}" for i in range(limit)]}

import asyncio
asyncio.run(node.start())
```

### 5.2 Mode 1: MCPToATTPAdapter — 包装已有 MCP Server

已有 MCP Server（FastMCP 实例），直接暴露为 ATTP 工具节点。
自动提取 FastMCP 中注册的工具列表，无需重写。

```python
from mcp.server.fastmcp import FastMCP
from attp.sdk.tools import MCPToATTPAdapter

# 已有的 MCP Server
my_mcp = FastMCP("my-service")

@my_mcp.tool()
async def search(query: str) -> str:
    return "results..."

@my_mcp.tool()
async def translate(text: str, target_lang: str = "en") -> str:
    return "translated..."

# 包装为 ATTP 工具节点
adapter = MCPToATTPAdapter(
    did="did:wba:tool.local:my-service",
    name="my-service",
    mcp_server=my_mcp,
    private_key_path="key.pem",
    port=9000,
)

import asyncio
asyncio.run(adapter.start())
```

### 5.3 Mode 2: MCPProxyToolNode — MCP Config 代理

外部 MCP 服务（如 web-reader、code-interpreter），
通过 JSON 配置文件接入，作为本地代理网关。
**签名方为本地代理**，远程服务完全无感知。

```python
from attp.sdk.tools import MCPProxyToolNode

proxy = MCPProxyToolNode(
    did="did:wba:proxy.local:web-reader",
    name="web-reader-proxy",
    private_key_path="key.pem",
    config={
        "mcpServers": {
            "web-reader": {
                "type": "streamableHttp",
                "url": "https://open.bigmodel.cn/api/mcp/web_reader/mcp",
                "headers": {"Authorization": "Bearer xxx"}
            }
        }
    },
    port=9001,
)

import asyncio
asyncio.run(proxy.start())
# 自动发现远程工具，暴露为 ATTP 端点
```

代理流程：
```
Agent → ATTP tool_request → MCPProxyToolNode（本地代理）
                                ↓ 本地签名
                                ↓ MCP JSON-RPC (tools/call)
                          远程 MCP Server (web-reader)
                                ↓ 返回结果
                          MCPProxyToolNode
                                ↓ 追加溯源跳 + 签名
                          → ATTP tool_response → Agent
```

### 5.4 ToolHandler

单个工具的处理器描述（Mode 0 使用）：

| 字段 | 说明 |
|------|------|
| `name` | 工具名称 |
| `description` | 工具描述 |
| `input_schema` | JSON Schema 格式的参数定义 |
| `handler` | 异步处理函数 |

### 5.5 ToolAd — ad.json 描述文件

所有模式共享的描述文件格式：

```json
{
  "type": "attp-tool-node",
  "version": "0.1.0",
  "identifier": "did:wba:tool.local:search-service",
  "name": "search-service",
  "description": "搜索知识库工具服务",
  "attp_endpoint": "http://localhost:9000/attp",
  "public_key_endpoint": "",
  "mcp_tools": [
    {
      "name": "search",
      "description": "搜索知识库",
      "inputSchema": {"type": "object", "properties": {...}, "required": [...]}
    }
  ]
}
```

### 5.6 ATTP 端点（所有模式统一）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/attp` | 处理 tool_request / record |
| GET | `/attp/ad.json` | 返回工具节点描述 |
| GET | `/attp/health` | 健康检查 |

---

## 6. 完整交互流程

### 6.1 工具调用全链路

```
1. nanobot (Agent) 通过 MCP SSE 连接到 MCPToolBridge
2. nanobot 调用 call_tool_node(tool_did, tool_name, args, chat_id)
3. MCPToolBridge:
   a. 记录 A2T 行为到 NodeMessage + SQLite
   b. 追加溯源跳（hop_hash + 签名）
   c. HTTP POST → ATTPToolNode
4. ATTPToolNode:
   a. 验证溯源链
   b. 路由到对应 ToolHandler 执行
   c. 记录 T2A 行为到 SQLite
   d. 追加溯源跳（工具节点签名）
   e. 返回 tool_response
5. MCPToolBridge 返回结果给 nanobot
```

### 6.2 溯源链示例

```
hop 0: Agent A → Tool Node T  (A2T, Agent A 签名)
hop 1: Tool Node T → Agent A  (T2A, Tool Node T 签名)
```

每次跳都包含 `hop_hash`（SHA-256）和 `Signature`（RSA/ECDSA），确保不可抵赖和不可篡改。

---

## 7. 关键代码索引

### 新增文件

| 文件 | 核心内容 |
|------|----------|
| `app/tools/mcp_tool_bridge.py` | `MCPToolBridge` + `ToolNodeInfo`（动态注册工具） |
| `sdk/tools/tool_node.py` | `ATTPToolNode`（Mode 0: 原生 ATTP） |
| `sdk/tools/mcp_adapter.py` | `MCPToATTPAdapter`（Mode 1: 包装已有 MCP Server） |
| `sdk/tools/mcp_proxy.py` | `MCPProxyToolNode`（Mode 2: MCP Config 代理） |
| `sdk/tools/handler.py` | `ToolHandler` |
| `sdk/tools/tool_ad.py` | `ToolAd` |
| `sdk/tools/__init__.py` | 包导出 |
| `scripts/tool_ad_creator.py` | ad.json 命令行生成脚本 |

### 修改文件

| 文件 | 改动内容 |
|------|----------|
| `app/tools/__init__.py` | 新增 `MCPToolBridge`, `ToolNodeInfo` 导出 |
| `core/sessions/node_message.py` | 行为类型注释更新 |
| `app/client.py` | field_type 值更新 |
| `app/web/app.py` | field_type 值更新 |
| `app/web/api/trace.py` | API 响应键名更新 |