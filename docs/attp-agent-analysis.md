# ATTP Agent 端代码与功能分析

> 本文档对 `python/attp/app/` 和 `python/attp/channels/` 目录下的所有模块进行全面的代码结构与功能分析。

## 目录

- [1. 概述](#1-概述)
- [2. 模块架构总览](#2-模块架构总览)
- [3. Channel 可插拔适配层](#3-channel-可插拔适配层)
- [4. 配置管理（Config）](#4-配置管理config)
- [5. 客户端（ATTPClient）](#5-客户端attpclient)
- [6. 服务端（ATTPServer）](#6-服务端attpserver)
- [7. 工具桥接器（MCPToolBridge）](#7-工具桥接器mcptoolbridge)
- [8. 心跳管理（Heartbeat）](#8-心跳管理heartbeat)
- [9. Web UI 通道（WebApp）](#9-web-ui-通道webapp)
- [10. 日志系统（Logging）](#10-日志系统logging)
- [11. Agent 端核心数据流](#11-agent-端核心数据流)
- [12. 设计模式与总结](#12-设计模式与总结)

---

## 1. 概述

ATTP Agent 端是 ATTP（Agents Traceability and Trust Protocol）协议在 Agent 节点上的完整运行时实现，负责：

| 能力 | 说明 |
|------|------|
| 安全通信 | 基于 DID（`did:wba`）身份的 Agent 间通信，通过 OpenANP SDK 实现互发现与消息传递 |
| 消息追踪 | 利用 Core 层的 `AgentTracer` 构建溯源链，支持 U2A / A2A / A2T / A2U 四种行为类型 |
| 双轮回溯确认 | 严格遵循"先回传协议节点，再发送消息"的时序规则 |
| 工具桥接 | 通过 MCP SSE Server 将远程 ATTP 工具节点桥接为本地 MCP 工具，供 Agent 内置 MCP Client 调用 |
| Web UI | 提供 WebSocket + REST API 前端通道，支持用户交互与配置管理 |
| 健康监测 | 可插拔的心跳检查器，监控远程 Agent 和工具节点的可达性 |

Agent 端的架构分为两层：

- **`app/`** — **框架无关的应用层**，包含所有核心组件（Client、Server、ToolBridge、Heartbeat、WebApp、Config），各组件通过依赖注入组合
- **`channels/`** — **可插拔的渠道适配层**，每个 Channel 将 `app/` 组件按特定框架的要求拼装，以插件形式接入不同框架（当前实现了 nanobot 适配器）

---

## 2. 模块架构总览

```
channels/
├── __init__.py
└── nanobot.py                   # nanobot 框架适配器（ATTPChannel）

app/
├── __init__.py
├── client.py                    # ATTPClient — Agent 间通信客户端
├── server.py                    # ATTPServer — Agent 间通信服务端
├── logging.py                   # 统一日志模块
│
├── config/
│   ├── __init__.py
│   └── config.py                # 配置管理（Pydantic 模型 + ConfigManager）
│
├── heartbeat/
│   ├── __init__.py
│   ├── heartbeat.py             # HeartbeatManager — 通用心跳调度器
│   ├── _agent.py                # AgentHealthChecker — Agent 健康检查
│   └── _tool.py                 # ToolNodeHealthChecker — 工具节点健康检查
│
├── tools/
│   ├── __init__.py
│   └── mcp_tool_bridge.py       # MCPToolBridge — MCP Server + ATTP Tool Client 桥接器
│
└── web/
    ├── __init__.py
    ├── app.py                   # WebApp — WebSocket + REST API + SPA
    └── api/
        ├── __init__.py
        ├── config_setting.py    # 配置读写 API
        └── node_status.py       # 节点状态 API
```

### 模块依赖关系

```
ATTPChannel (channels/nanobot.py)
  ├── ConfigManager (app/config/config.py)
  │     └── ATTPConfigFile
  │           ├── ATTPClientConfig
  │           ├── ATTPServerConfig
  │           ├── WebAppConfig
  │           ├── ToolConfig
  │           ├── HeartbeatConfig
  │           └── ProtocolNodeConfig
  │
  ├── AgentTracer (core/agent_tracer.py)          # 轻量级溯源门面
  │     ├── KeyStore (core/authentication/keys.py)
  │     └── ChainManager (core/provenance/chain.py)
  │
  ├── ATTPClient (app/client.py)                  # 出站通信
  │     ├── DIDWbaAuthHeader (anp)
  │     ├── RemoteAgent (anp)
  │     ├── AgentTracer
  │     └── AppSessionManager
  │
  ├── ATTPServer (app/server.py)                  # 入站通信
  │     ├── FastAPI + OpenANP Agent
  │     ├── AgentTracer
  │     └── AppSessionManager
  │
  ├── MCPToolBridge (app/tools/mcp_tool_bridge.py) # 工具桥接
  │     ├── FastMCP (MCP SSE Server)
  │     ├── ATTPClient (send_callback)
  │     ├── AgentTracer
  │     └── AppSessionManager
  │
  ├── HeartbeatManager (app/heartbeat/heartbeat.py) # 健康监测
  │     ├── AgentHealthChecker → ATTPClient
  │     └── ToolNodeHealthChecker → MCPToolBridge
  │
  ├── WebApp (app/web/app.py)                     # 前端通道
  │     ├── FastAPI + WebSocket
  │     ├── AgentTracer
  │     └── AppSessionManager
  │
  └── ProtocolNode (protocol_node/)              # 可选：内嵌协议节点
```

---

## 3. Channel 可插拔适配层

### 3.1 设计理念

`channels/` 目录是 ATTP Agent 端的**可插拔适配层**。每个 Channel 是一个独立的插件，负责：

1. **组装** `app/` 中的所有框架无关组件（Client、Server、ToolBridge、Heartbeat、WebApp）
2. **适配**特定框架的消息总线、生命周期管理、配置加载等接口
3. **桥接**框架消息与 ATTP 协议（通过 `channel_callback` 注入）

当前仅实现了 `nanobot.py`（适配 nanobot 框架），但架构上支持为其他主流框架（如 LangChain、AutoGen、CrewAI 等）创建新的 Channel 适配器。

### 3.2 ATTPChannel（`channels/nanobot.py`）

nanobot 框架适配器，继承 `nanobot.channels.base.BaseChannel`，实现 `start()/stop()/send()` 接口。

#### 3.2.1 Channel 配置

```python
class ATTPConfig(Base):
    """ATTP channel configuration."""
    enabled: bool = False
    config_path: str = "~/.attp/agent/nanobot/config.json"
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | `bool` | 是否启用 ATTP Channel |
| `config_path` | `str` | ATTP 配置文件路径（`ConfigManager` 加载） |
| `allow_from` | `list[str]` | 允许的消息来源（默认 `["*"]` 全部允许） |

#### 3.2.2 组件组装

`start()` 方法中按照依赖关系组装所有组件：

```
ATTPChannel.start()
  │
  ├── 1. ConfigManager(config_path)         → 加载配置
  ├── 2. AgentTracer()                      → 轻量级溯源（无 DB）
  ├── 3. WebApp(web_config, channel_callback=self._receive)
  ├── 4. AppSessionManager()                → 内存会话管理
  ├── 5. ATTPClient(agent_did, client_config, ...)
  ├── 6. ATTPServer(agent_did, server_config, ...)
  ├── 7. HeartbeatManager(heartbeat_config)
  │     ├── AgentHealthChecker(attp_client)
  │     └── ToolNodeHealthChecker(tool_bridge)
  ├── 8. MCPToolBridge(tool_config, attp_client, tracer, ...)
  ├── 9. ProtocolNode(config_path)          → 可选：内嵌协议节点
  │
  ├── 10. discover_all_tool_nodes()         → 自动发现工具节点
  │
  └── 11. asyncio.TaskGroup()               → 并发启动所有组件
        ├── attp_client.start()
        ├── attp_server.start()
        ├── heartbeat_manager.start()
        ├── tool_bridge.start()
        ├── web_app.start(...)
        └── protocol_node.start()           → 可选
```

**关键依赖注入关系**：

| 组件 | 注入的依赖 |
|------|----------|
| `ATTPClient` | `session_manager`, `web_callback`, `tracer` |
| `ATTPServer` | `session_manager`, `web_callback`, `attp_channel_callback`, `tracer` |
| `MCPToolBridge` | `attp_client`, `tracer`, `session_manager`, `send_callback=attp_client.send_message` |
| `AgentHealthChecker` | `attp_client` |
| `ToolNodeHealthChecker` | `tool_bridge` |
| `WebApp` | `channel_callback=self._receive` → 路由到 nanobot MessageBus |

#### 3.2.3 消息路由

```
用户 → WebApp(WS) → channel_callback → ATTPChannel._receive()
                                              ↓
                                      ATTPChannel._handle_message()
                                              ↓
                                      nanobot MessageBus → Agent LLM 处理
                                              ↓
                                      ChannelManager → ATTPChannel.send()
                                              ↓
                                      WebApp.send_message_to_user() → 用户
```

- `_receive(sender, chat_id, content, media)` — 从 WebApp/ATTPServer 接收消息，路由到 `_handle_message()`
- `send(msg: OutboundMessage)` — 从 nanobot MessageBus 接收回复，通过 `WebApp.send_message_to_user()` 发送给用户

#### 3.2.4 热重载（Hot Reload）

`reload()` 方法实现**差量热重载**——仅重新加载配置发生变化的组件：

```python
async def reload(self, old_cfg: ATTPConfigFile, new_cfg: ATTPConfigFile) -> None
```

| 变化项 | 处理策略 |
|--------|---------|
| DID 或 ATTPClient 配置 | `attp_client.reload(new_cfg.attp_client, new_cfg.did)` |
| DID 或 ATTPServer 配置 | `attp_server.reload(new_cfg.attp_server, new_cfg.did)` |
| Heartbeat 配置 | `heartbeat_manager.reload(new_cfg.heartbeat)` |
| Tool 配置（host/port） | `tool_bridge.reload(new_cfg.tool)` |
| Tool 配置（tool_node_ads） | 先注销所有旧工具节点 → 重新发现新列表 |
| ProtocolNode 配置 | `protocol_node.reload_config()` |
| WebApp 配置（host/port） | 更新属性但需手动重启（**无法热重载端口**） |

热重载通过 Web API `POST /api/config/reload` 触发：

```
POST /api/config/reload
  → config_manager.load()                    # 重新读取磁盘配置
  → reload_callback(old_cfg, new_cfg)        # 差量重载
```

#### 3.2.5 生命周期管理

```python
# 启动：并发启动所有组件（asyncio.TaskGroup）
async with asyncio.TaskGroup() as tg:
    tg.create_task(self._attp_client.start())
    tg.create_task(self._attp_server.start())
    tg.create_task(self._heartbeat_manager.start())
    tg.create_task(self._tool_bridge.start())
    tg.create_task(self._web_app.start(...))
    if self._protocol_node:
        tg.create_task(self._protocol_node.start())

# 阻塞直到 stop() 被调用
while self._running:
    await asyncio.sleep(1)

# 停止：并发停止所有组件
async with asyncio.TaskGroup() as tg:
    tg.create_task(self._heartbeat_manager.stop())
    tg.create_task(self._tool_bridge.stop())
    tg.create_task(self._attp_client.stop())
    tg.create_task(self._attp_server.stop())
    tg.create_task(self._web_app.stop())
    if self._protocol_node:
        tg.create_task(self._protocol_node.stop())
```

#### 3.2.6 扩展其他框架

要为其他框架创建新的 Channel 适配器，需要：

1. 在 `channels/` 下新建文件（如 `langchain.py`）
2. 实现 `start()` — 组装 app 组件并启动
3. 实现 `stop()` — 停止所有组件
4. 实现 `send()` — 将框架的出站消息路由到 ATTP 通道
5. 将框架的入站消息桥接到 ATTP 的消息处理链

---

## 4. 配置管理（Config）

### 4.1 配置模型层级

基于 Pydantic v2 的多层配置模型，支持 camelCase/snake_case 双格式键名：

```
ATTPConfigFile (根模型, ~/.attp/agent/nanobot/config.json)
  ├── did: str = ""                     # 本 Agent 的 DID
  ├── attp_client: ATTPClientConfig     # 客户端配置
  │     ├── did_doc_path: str           # DID 文档路径
  │     ├── did_key_path: str           # DID 私钥路径
  │     └── node_ads: list[str]         # 远程 Agent ad.json URL 列表
  │
  ├── attp_server: ATTPServerConfig     # 服务端配置
  │     ├── name: str                   # Agent 名称
  │     ├── prefix: str = "/agent"      # API 路由前缀
  │     ├── description: str            # Agent 描述
  │     ├── server_host: str            # 监听地址
  │     ├── server_port: int = 8000     # 监听端口
  │     ├── private_key_path: str       # 私钥路径（签名用）
  │     └── public_key_path: str        # 公钥路径
  │
  ├── web_app: WebAppConfig             # Web UI 配置
  │     ├── host: str = "127.0.0.1"
  │     └── port: int = 8001
  │
  ├── tool: ToolConfig                  # 工具桥接配置
  │     ├── host: str = "127.0.0.1"
  │     ├── port: int = 8002
  │     └── tool_node_ads: list[str]    # 工具节点 ad.json URL 列表
  │
  ├── heartbeat: HeartbeatConfig        # 心跳配置
  │     ├── interval: int = 30          # 心跳间隔（秒）
  │     ├── timeout: int = 90           # 单次超时（秒）
  │     └── max_fail: int = 3           # 连续失败阈值
  │
  └── protocol_node: ProtocolNodeConfig # 协议节点配置
        ├── enabled: bool = False       # 是否启用内嵌协议节点
        └── config_path: str            # 外部配置文件路径
```

### 4.2 ATTPBase — 配置基类

```python
class ATTPBase(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def changed_fields(self, other: ATTPBase) -> set[str]:
        """返回与 other 值不同的字段名集合（用于差量热重载判断）。"""
```

特性：
- **双格式键名**：通过 `alias_generator=to_camel` + `populate_by_name=True`，同时接受 camelCase（JSON 前端）和 snake_case（Python 后端）
- **变更检测**：`changed_fields()` 用于热重载时判断哪些配置项发生了变化

### 4.3 ConfigManager

```python
class ConfigManager:
    def __init__(self, attp_config_path: str | Path)
    
    def load(self) -> None                    # 从磁盘加载配置
    def update(self, partial: dict) -> ATTPConfigFile  # 部分更新（合并 + 验证 + 写盘）
```

#### update() — 部分更新

支持嵌套的部分更新，使用 `_deep_merge()` 策略：

```python
# 请求体只需包含要更新的字段
PUT /api/config
{
    "attpClient": {
        "nodeAds": ["http://new-agent/ad.json"]
    }
}
```

#### _deep_merge() — 深度合并

```python
def _deep_merge(base: dict, override: dict, list_strategy: str = "extend") -> dict
```

| 数据类型 | 合并策略 |
|---------|---------|
| `dict` | 递归深度合并 |
| `list` | `extend` — 去重合并（默认）；`replace` — 完全替换 |
| 其他 | 直接覆盖 |

---

## 5. 客户端（ATTPClient）

ATTPClient 是 Agent 间通信的**出站客户端**，负责发现远程 Agent、维护连接缓存、发送 ATTP 消息。

### 5.1 初始化

```python
class ATTPClient:
    def __init__(
        self,
        agent_did: str,                    # 本 Agent DID
        client_config: ATTPClientConfig,   # 客户端配置
        session_manager: AppSessionManager | None = None,
        web_callback = None,               # UI 通知回调
        tracer: AgentTracer = None,        # 溯源追踪器
    )
```

**内部状态**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `auth` | `DIDWbaAuthHeader` | DID WBA 认证头生成器（用于 OpenANP 通信） |
| `registry` | `list[str]` | 远程 Agent ad.json URL 列表（来自配置） |
| `remote_agents` | `dict[str, RemoteAgent]` | 已连接的远程 Agent 缓存（DID → RemoteAgent） |
| `registered_agents` | `dict[str, dict]` | 已注册 Agent 的元信息（DID → {did, name, description, ad_url, capabilities}） |
| `failed_urls` | `set[str]` | 连接失败的 URL（用于心跳重连） |

### 5.2 Agent 发现与缓存

#### initialize()

启动时从 `registry` 加载所有 ad.json，通过 OpenANP SDK 发现远程 Agent：

```
initialize()
  for ad_path in registry:
    remote = RemoteAgent.discover(ad_path, auth)  # OpenANP 发现
    → HTTP GET ad_path → 提取 identifier
    → remote_agents[identifier] = remote
    → registered_agents[identifier] = {元信息}
    → 失败 → failed_urls.add(ad_path)
```

#### _get_remote_agent()

单 Agent 发现流程：

```
1. RemoteAgent.discover(target_ad, auth)    # 通过 OpenANP SDK 发现
2. HTTP GET target_ad                        # 获取 ad.json
3. 提取 identifier                           # 作为缓存 key
4. 缓存到 remote_agents + registered_agents
```

### 5.3 统一消息发送

#### send_message() — 统一入口

```python
async def send_message(self, target: str, content: str, chat_id: str) -> str
```

路由规则：

| target 格式 | 路由目标 |
|-------------|---------|
| `did:wba:...` | Agent 间通信（A2A） |
| 其他 | 返回错误 |

#### send_to_agent() — Agent 间发送

完整的 A2A 消息发送流程，严格遵循 ATTP 时序规则：

```
send_to_agent(target_did, sender_did, content, message_type, metadata)
  │
  ├── 1. 查找/重连 RemoteAgent
  │     remote = remote_agents.get(target_did)
  │     if not remote → retry_failed_urls(target_did)
  │
  ├── 2. 追加溯源跳（AgentTracer.append_hop）
  │     metadata = tracer.append_hop(metadata, content, sender_did, target_did, ...)
  │     behavior_type = "A2A"
  │
  ├── 3. 构建 NodeMessage
  │     recorded = RecordedHop.from_dict(metadata["recorded_hop"])
  │     node_msg = NodeMessage(protocol_url, nonce, recorded)
  │
  ├── 4. ★ 时序规则：先回传协议节点 ★
  │     if protocol_url and private_key_path:
  │         send_back_message(protocol_url, ...)   # BackMessage Phase 2
  │
  ├── 5. 发送 NodeMessage 给目标 Agent
  │     result = remote.receive_message(sender_did, content, message_type, metadata)
  │
  └── 6. 通知 UI（web_callback）
        await web_callback(content, {direction: "out", ...})
```

### 5.4 失败重连

```python
async def retry_failed_urls(self, target_did: str = None) -> RemoteAgent | None
```

| 调用场景 | target_did | 行为 |
|---------|-----------|------|
| Agent 不在缓存中 | 指定 DID | 遍历 failed_urls 尝试重连，找到目标即返回 |
| 心跳批量重连 | `None` | 遍历所有 failed_urls，成功则移出失败集合 |

### 5.5 生命周期

```python
async def start()           # initialize() + 设 running
async def stop()            # 清 running
async def reload(config)    # stop → 更新 auth/registry → 清缓存 → reinitialize → start
```

---

## 6. 服务端（ATTPServer）

ATTPServer 是 Agent 间通信的**入站服务端**，基于 FastAPI + OpenANP SDK 接收来自其他 Agent 的消息。

### 6.1 架构设计

```python
class ATTPServer:
    def __init__(
        self,
        agent_did: str,
        server_config: ATTPServerConfig,
        session_manager: AppSessionManager,
        web_callback = None,                 # UI 通知回调
        attp_channel_callback = None,        # Channel 消息路由回调
        tracer: AgentTracer | None = None,
    )
```

ATTPServer 通过 `_create_agent()` **动态创建** OpenANP Agent 类：

```
ATTPServer
  ├── FastAPI app
  │     └── include_router(Agent.router())   # OpenANP Agent 路由
  │
  └── Agent (动态创建)
        ├── health() → "ok"                  # 健康检查端点
        └── receive_message()                # 消息接收处理
```

### 6.2 消息接收处理

`receive_message()` 仅处理 `agent_request` 类型消息：

```
receive_message(sender_did, content, message_type="agent_request", metadata)
  │
  ├── 1. 解析 NodeMessage
  │     node_msg_data = metadata["NodeMessage"]
  │     node_msg = NodeMessage.from_dict(node_msg_data)
  │
  ├── 2. 存储 trace 到 session
  │     session = session_manager.get_or_create(session_id)
  │     session.set_trace_metadata({recorded_hop, protocol_url})
  │
  ├── 3. 路由到 Channel（attp_channel_callback）
  │     → 通知 nanobot MessageBus 处理
  │
  ├── 4. 通知 UI（web_callback）
  │     → direction: "in", other_did: sender_did
  │
  ├── 5. ★ Phase 1 回传：向发送方的协议节点确认 ★
  │     send_back_message(protocol_url, node_did, nonce, recorded_hop, private_key)
  │
  └── 6. 返回 "Message received"
```

### 6.3 Phase 1 回传回调

`_send_proof_callback` 是服务端的 Phase 1 回传实现：

```
_send_proof_callback(node_msg, agent_did, tracer, private_key_path)
  │
  ├── 检查 tracer 和 private_key_path 是否可用
  ├── 加载私钥
  └── send_back_message(protocol_url, node_did, nonce, recorded_hop, private_key)
      → POST {protocol_url}/record (BackMessage)
```

### 6.4 生命周期

```python
async def start()           # uvicorn.Server.serve() 作为 asyncio.Task
async def stop()            # should_exit + 等待/取消 serve_task
async def reload(config)    # stop → 更新配置 → 重建 Agent/app → 等端口释放 → start
```

**端口等待**：`reload()` 中使用 `_wait_for_port()` 轮询等待端口释放（最长 10 秒），避免 `Address already in use` 错误。

---

## 7. 工具桥接器（MCPToolBridge）

MCPToolBridge 是 Agent 侧的核心桥接组件，同时充当两个角色：

| 角色 | 协议 | 说明 |
|------|------|------|
| **MCP SSE Server** | MCP (Model Context Protocol) | 暴露给 nanobot（Agent 内置 MCP Client）连接 |
| **ATTP Tool Client** | ATTP | 将工具调用通过 ATTP 协议发送到远程工具节点 |

### 7.1 初始化

```python
class MCPToolBridge:
    def __init__(
        self,
        tool_config: ToolConfig,
        attp_client: ATTPClient | None = None,
        tracer: AgentTracer | None = None,
        session_manager: AppSessionManager | None = None,
        agent_did: str = "",
        send_callback: Callable = None,    # 消息发送回调（attp_client.send_message）
    )
```

**内部状态**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `_mcp` | `FastMCP` | MCP Server 实例（名称 `"attp-tools"`） |
| `_tool_nodes` | `dict[str, ToolNodeInfo]` | 已发现的远程工具节点 |
| `_node_tool_map` | `dict[str, list[str]]` | DID → MCP 工具名列表映射 |
| `_registry_lock` | `asyncio.Lock` | 工具注册/注销并发保护 |

### 7.2 核心工具 — send_message_tool

```
send_message_tool(target, content, chat_id) → str
  │
  └── _send_callback(target, content, chat_id)
      → attp_client.send_message(target, content, chat_id)
```

供 nanobot LLM 调用，支持发送消息给用户（`target="user:web_ui"`）或其他 Agent（`target="did:wba:..."`）。

### 7.3 动态工具注册/注销

#### 工具名生成规则

```python
_build_tool_mcp_name(node_name, tool_name, did)
  → "{sanitized_node_name}_{did_hash}__{tool_name}"
```

示例：`weather_service_abc12345__get_weather`

#### 注册流程

```
register_tool_node(tool_info: ToolNodeInfo)
  │
  ├── 1. 缓存 tool_nodes[did] = tool_info
  │
  └── 2. 遍历 tool_info.tools:
        ├── 生成 mcp_name
        ├── 构造描述（带节点来源标注）
        ├── 注入 chat_id 到 inputSchema（required）
        ├── 创建 PassthroughArgModel（透传参数）
        ├── 构造 MCPTool 对象（绕过函数签名内省）
        └── 注册到 _mcp._tool_manager._tools[mcp_name]
```

**PassthroughArgModel** — 透传参数模型，绕过 FastMCP 的函数签名内省限制：

```python
class PassthroughArgModel(ArgModelBase):
    model_config = ConfigDict(extra="allow")  # 接受任意字段

    def model_dump_one_level(self) -> dict[str, Any]:
        # 返回声明字段 + extra 字段（远程工具的实际参数）
```

#### 注销流程

```
unregister_tool_node(did)
  ├── 移除 _node_tool_map[did] 中所有 MCP 工具
  └── 移除 _tool_nodes[did]
```

### 7.4 工具节点发现

```
discover_tool_node(ad_url) → ToolNodeInfo | None
  │
  ├── HTTP GET ad_url → ad_data
  ├── 验证 type == "attp-tool-node"
  ├── 构建 ToolNodeInfo(did, name, description, attp_endpoint, tools, ...)
  ├── 验证必填字段（identifier, attp_endpoint）
  └── register_tool_node(tool_info)

discover_all_tool_nodes(ad_urls) → None
  └── asyncio.gather(*[discover_tool_node(url) for url in ad_urls])
```

#### ToolNodeInfo 数据结构

```python
class ToolNodeInfo:
    did: str                       # 工具节点 DID
    name: str                      # 节点名称
    description: str               # 节点描述
    attp_endpoint: str             # ATTP 消息接收端点
    tools: list[dict]              # MCP 工具定义列表 [{name, description, inputSchema}]
    public_key_endpoint: str       # 公钥获取端点
    ad_url: str                    # 来源 ad.json URL（心跳恢复用）
```

### 7.5 ATTP 工具调用 — 完整回传时序

工具调用涉及 **4 次回传**（A2T 和 T2A 各 2 次）：

```
_call_tool_node(tool_did, tool_name, arguments, chat_id) → str
  │
  ├── 1. 获取 tool_info 和私钥
  │
  ├── 2. locked_session(chat_id) 保护 read-modify-write
  │     │
  │     ├── 获取 session trace metadata
  │     ├── 生成 nonce
  │     ├── tracer.append_hop(behavior_type="A2T")  # 递增 hop_count
  │     ├── 构建 NodeMessage(A2T)
  │     │
  │     ├── === 第一跳 A2T ===
  │     │     ├── ★ BackMessage #1 (Phase 2, Agent 报告) → Protocol Node ★
  │     │     │     send_back_message(protocol_url, agent_did, nonce, recorded_hop_a2t, ...)
  │     │     │
  │     │     └── HTTP POST NodeMessage(A2T) → Tool Node
  │     │           endpoint = tool_info.attp_endpoint
  │     │           body = node_message_a2t.to_dict()
  │     │
  │     └── === 第二跳 T2A ===
  │           ├── 解析返回的 NodeMessage(T2A)
  │           ├── 提取 result
  │           │
  │           ├── ★ BackMessage #4 (Phase 1, Agent 确认 T2A) → Protocol Node ★
  │           │     send_back_message(protocol_url, agent_did, nonce_t2a, recorded_hop_t2a, ...)
  │           │
  │           └── 更新 session trace（使用 T2A 的 recorded_hop）
  │
  └── 返回 result
```

**回传时序图**：

```
  Agent (MCPToolBridge)              Tool Node              Protocol Node
       │                                │                        │
       │  === 第一跳 A2T ===            │                        │
       │                                │                        │
       │  BackMessage #1 (Phase 2)      │                        │
       │  Agent 签名 identity           │                        │
       ├────────────────────────────────┼───────────────────────→│
       │                                │                  Branch A: 暂存
       │                                │                        │
       │  NodeMessage(A2T)              │                        │
       │  (Agent 签名 content)           │                        │
       ├───────────────────────────────→│                        │
       │                                │                        │
       │                                │  BackMessage #2 (Phase 1)
       │                                │  Tool 签名 identity    │
       │                                ├───────────────────────→│
       │                                │                  Branch B: 匹配验证
       │                                │                        │
       │  === 第二跳 T2A ===            │                        │
       │                                │                        │
       │  NodeMessage(T2A)              │                        │
       │  (Tool 签名 content)            │                        │
       │←───────────────────────────────┤                        │
       │                                │                        │
       │  BackMessage #4 (Phase 1)      │                        │
       │  Agent 签名 identity           │                        │
       ├────────────────────────────────┼───────────────────────→│
       │                                │                  Branch B: 匹配验证
```

### 7.6 生命周期

```python
async def start()       # FastMCP → Starlette SSE App → uvicorn 后台启动
async def stop()        # should_exit + cancel task
async def reload(config) # stop → 更新 host/port → start
```

---

## 8. 心跳管理（Heartbeat）

心跳系统采用**策略模式**，将调度逻辑与检查逻辑分离。

### 8.1 HealthChecker 协议

```python
@runtime_checkable
class HealthChecker(Protocol):
    async def check(self) -> None: ...
```

所有健康检查器必须实现 `check()` 方法。

### 8.2 HeartbeatManager（`heartbeat.py`）

通用心跳调度器，定时调用所有已注册的 HealthChecker。

```python
class HeartbeatManager:
    def __init__(self, heartbeat_config: HeartbeatConfig)
        self._interval = heartbeat_config.interval    # 心跳间隔（秒）
        self._timeout = heartbeat_config.timeout      # 单次超时（秒）
        self._max_fail = heartbeat_config.max_fail    # 连续失败阈值
```

#### 调度循环

```python
async def _loop(self) -> None:
    while True:
        await asyncio.sleep(self._interval)
        for checker in self._checkers:
            await checker.check()    # 异常仅记录日志，不影响其他 checker
```

#### Checker 管理

```python
def add_checker(checker: HealthChecker)    # 注册
def remove_checker(checker: HealthChecker) # 移除
def checkers -> list[HealthChecker]        # 只读视图
```

### 8.3 AgentHealthChecker（`_agent.py`）

检查远程 Agent 连接状态。

#### check() 流程

```
check()
  │
  ├── 1. 重连失败的 URL
  │     attp_client.retry_failed_urls(target_did=None)
  │
  └── 2. 检查所有已连接 Agent
        for did, remote in remote_agents.items():
            _check_agent(did, remote)
              │
              ├── asyncio.wait_for(remote.health(), timeout=timeout)
              ├── 返回 "ok" → 重置失败计数
              ├── 超时/异常 → 递增失败计数
              └── 失败次数 >= max_fail → _evict(did)
                    ├── 从 remote_agents 移除
                    ├── ad_url 加回 failed_urls
                    └── 下次心跳时自动尝试重连
```

#### Evict 策略

```
agent 连续失败 >= max_fail 次
  → 从 remote_agents 移除（停止向其发送消息）
  → ad_url 加回 failed_urls（心跳自动重连）
  → 重连成功后由 retry_failed_urls 恢复到 remote_agents
```

### 8.4 ToolNodeHealthChecker（`_tool.py`）

检查远程工具节点健康状态。

#### check() 流程

```
check()
  │
  ├── 1. 检查已注册工具节点
  │     _check_tool_nodes()
  │       for did, info in tool_nodes.items():
  │           HTTP GET {info.attp_endpoint}/health
  │           ├── 200 → 重置失败计数
  │           └── 非 200 / 异常 → _record_fail(did, ad_url)
  │                 ├── 失败次数 < max_fail → 记录日志
  │                 └── 失败次数 >= max_fail → _evict(did, ad_url)
  │                       ├── tool_bridge.unregister_tool_node(did)  # 移除 MCP 工具
  │                       └── _failed_nodes[ad_url] = did            # 记录用于恢复
  │
  └── 2. 重试失败的工具节点
        _retry_failed_nodes()
          for ad_url in _failed_nodes:
              tool_bridge.discover_tool_node(ad_url)
              ├── 成功 → 移出 _failed_nodes（MCP 工具自动重新注册）
              └── 失败 → 留在 _failed_nodes，下次心跳再试
```

#### 工具节点的 Evict/Recover 生命周期

```
正常状态 → 连续失败 → Evict → 移除 MCP 工具
                                    ↓
                           心跳自动尝试 re-discover
                                    ↓
                           成功 → 重新注册 MCP 工具
                           失败 → 继续等待下次心跳
```

### 8.5 生命周期

```python
async def start()       # 创建后台 _loop Task
async def stop()        # cancel Task
async def reload(config) # stop → 更新 interval/timeout/max_fail → start（Checkers 不变）
```

---

## 9. Web UI 通道（WebApp）

WebApp 是面向用户的前端通道，提供 WebSocket 实时通信和 REST API 管理。

### 9.1 架构

```
WebApp
  ├── FastAPI app
  │     ├── CORS Middleware（allow_origins=["*"]）
  │     ├── GET /api/status           → 运行状态
  │     ├── WebSocket /ws             → 双向实时通信
  │     ├── GET /api/nodes            → Agent 节点列表
  │     ├── GET /api/config           → 配置读取
  │     ├── PUT /api/config           → 配置更新（写盘）
  │     ├── POST /api/config/reload   → 热重载
  │     └── SPA 路由（/assets + fallback index.html）
  │
  └── WebSocket 客户端管理
        _clients: list[WebSocket]
```

### 9.2 WebSocket 消息处理

#### 入站消息（User → Agent）

前端发送 `NodeMessage.to_dict()` 的 JSON：

```
WebSocket /ws 收到消息
  │
  ├── 1. 解析 JSON → NodeMessage.from_dict(message_data)
  │
  ├── 2. 提取 session_id 和 content
  │
  ├── 3. ★ U2A Phase 1 回传 ★
  │     if tracer and private_key_path and agent_did:
  │         locked_session(session_id):
  │             session.set_trace_metadata({recorded_hop, protocol_url})
  │         send_back_message(protocol_url, agent_did, nonce, recorded_hop, private_key)
  │
  └── 4. 路由到 Channel
        channel_callback(sender="user", chat_id=session_id, content=content, media=[])
```

#### 出站消息（Agent → User）

`send_message_to_user()` 构建 A2U NodeMessage 并通过 WebSocket 发送：

```
send_message_to_user(content, session_id)
  │
  ├── locked_session(session_id, create=False)
  │     │
  │     ├── 获取 trace metadata
  │     ├── 提取 protocol_url 和上一跳信息（获取 user_did）
  │     │
  │     ├── tracer.append_hop(behavior_type="A2U")
  │     │     构建新 RecordedHop（Agent → User）
  │     │
  │     ├── ★ 时序规则：先回传协议节点 ★
  │     │     send_back_message(protocol_url, agent_did, nonce, recorded, private_key)
  │     │
  │     ├── 更新 session trace
  │     │     session.set_trace_metadata({recorded_hop, protocol_url})
  │     │
  │     └── 序列化 NodeMessage → WebSocket 广播
  │           for client in _clients:
  │               client.send_text(json.dumps(node_msg.to_dict()))
  │
  └── 无 trace 时降级（消息被丢弃，记录 warning）
```

### 9.3 REST API

#### 节点状态 API（`node_status.py`）

```
GET /api/nodes → {"agents": [...]}
```

返回所有已注册 Agent 的状态：

| 字段 | 说明 |
|------|------|
| `did` | Agent DID |
| `name` | 名称 |
| `description` | 描述 |
| `ad_url` | ad.json 地址 |
| `capabilities` | 能力列表 |
| `online` | 是否在线（DID 在 `remote_agents` 中） |

#### 配置管理 API（`config_setting.py`）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/config?refresh=true` | GET | 读取配置（可选刷新） |
| `/api/config` | PUT | 部分更新配置（写盘，不热重载） |
| `/api/config/reload` | POST | 重新读盘 + 热重载 |

热重载流程：

```
POST /api/config/reload
  → old_cfg = deepcopy(current)
  → config_manager.load()          # 重新读取磁盘
  → new_cfg = current
  → reload_callback(old_cfg, new_cfg)  # ATTPChannel.reload()
```

### 9.4 SPA 托管

WebApp 自动托管前端静态文件（从 `web/static/` 目录）：

- `/assets/*` → 静态资源
- `/*` → SPA fallback（返回 `index.html`）

### 9.5 生命周期

```python
async def start(attp_client, config_manager, reload_callback, session_manager, agent_did, tracer, private_key_path)
async def stop()       # should_exit + cancel + 关闭所有 WS 连接
```

---

## 10. 日志系统（Logging）

### 10.1 组件化日志

`_ComponentLogger` 为每个 ATTP 组件提供带 `[ATTP {Component}]` 前缀的日志：

```python
from attp.app.logging import get_logger
log = get_logger("Server")
log.info("started on {}:{}", "0.0.0.0", 8000)
# 输出: ... | INFO | ... - [ATTP Server] started on 0.0.0.0:8000
```

**已注册的组件名称**：

| 组件 | Logger 名称 | 前缀 |
|------|------------|------|
| ATTPClient | `"Client"` | `[ATTP Client]` |
| ATTPServer | `"Server"` | `[ATTP Server]` |
| MCPToolBridge | `"ToolBridge"` | `[ATTP ToolBridge]` |
| HeartbeatManager | `"Heartbeat"` | `[ATTP Heartbeat]` |
| AgentHealthChecker | `"Heartbeat.Agent"` | `[ATTP Heartbeat.Agent]` |
| ToolNodeHealthChecker | `"Heartbeat.Tool"` | `[ATTP Heartbeat.Tool]` |
| WebApp | `"WebUI"` | `[ATTP WebUI]` |
| ConfigManager | `"Config"` | `[ATTP Config]` |

底层使用 **loguru**，通过 `opt(depth=1)` 确保调用栈指向真实调用方。

### 10.2 Uvicorn 静默配置

```python
UVICORN_SILENT_LOG_CONFIG = {
    "loggers": {
        "uvicorn": {"handlers": ["null"]},
        "uvicorn.error": {"handlers": ["null"]},
        "uvicorn.access": {"handlers": ["null"]},
    },
    "handlers": {"null": {"class": "logging.NullHandler"}},
}
```

所有 Agent 端组件（ATTPServer、MCPToolBridge、WebApp）使用此配置启动 uvicorn，彻底静默 uvicorn 自身日志，避免与 ATTP 组件日志混淆。

### 10.3 第三方噪音过滤

`_NoiseFilter` 过滤已知的无害第三方日志：

| Logger 名称 | 过滤的消息子串 |
|-------------|--------------|
| `mcp.client.sse` | `"Error in sse_reader"` |
| `anp.anp_crawler.anp_client` | `"HTTP request failed"` |

### 10.4 全局日志等级

```python
set_log_level("DEBUG")   # 启用详细调试信息
```

---

## 11. Agent 端核心数据流

### 11.1 U2A（用户 → Agent）完整流程

```
  User (Browser)             WebApp              Protocol Node          Agent (nanobot)
       │                       │                      │                      │
       │  NodeMessage(U2A)     │                      │                      │
       ├──── WS ──────────────→│                      │                      │
       │                       │                      │                      │
       │                       │  BackMessage Phase 1 │                      │
       │                       │  (User 签名 identity │                      │
       │                       │   由前端完成)         │                      │
       │                       ├─────────────────────→│                      │
       │                       │                Branch A: 暂存               │
       │                       │                      │                      │
       │                       │  channel_callback    │                      │
       │                       ├──────────────────────┼─────────────────────→│
       │                       │                      │              LLM 处理 │
```

1. 前端构建 `NodeMessage`（含 `RecordedHop`，type=U2A）
2. 通过 WebSocket 发送给 WebApp
3. WebApp 执行 Phase 1 回传：`send_back_message()` → Protocol Node
4. 路由到 `channel_callback` → nanobot MessageBus → Agent LLM

### 11.2 A2A（Agent → Agent）完整流程

```
  Agent A (Client)                          Agent B (Server)           Protocol Node
       │                                         │                        │
       │  1. tracer.append_hop("A2A")            │                        │
       │  2. 构建 NodeMessage                    │                        │
       │                                         │                        │
       │  ★ 3. BackMessage Phase 2 (A 报告) ★    │                        │
       ├─────────────────────────────────────────┼───────────────────────→│
       │                                         │                  Branch A: 暂存
       │                                         │                        │
       │  4. NodeMessage(A→B)                    │                        │
       ├────────────────────────────────────────→│                        │
       │                                         │                        │
       │                                         │  ★ 5. BackMessage     │
       │                                         │  Phase 1 (B 确认) ★   │
       │                                         ├───────────────────────→│
       │                                         │                  Branch B: 匹配验证
       │                                         │                        │
       │                                         │  6. channel_callback   │
       │                                         │  → nanobot 处理        │
```

**发送方（Agent A）**：
1. 从 session 获取 trace metadata
2. `AgentTracer.append_hop(behavior_type="A2A")` — 递增 hop_count
3. 构建 `NodeMessage`
4. **先回传**：`send_back_message()` → Protocol Node（Phase 2，Agent A 报告）
5. **再发送**：`remote.receive_message()` → Agent B

**接收方（Agent B）**：
1. 解析 `NodeMessage`
2. 存储 trace 到 session
3. **回传**：`send_back_message()` → Protocol Node（Phase 1，Agent B 确认）
4. 路由到 `attp_channel_callback` → nanobot 处理

### 11.3 A2T（Agent → Tool）完整流程

参见[7.5 工具调用完整回传时序](#75-attp-工具调用--完整回传时序)。

关键特点：
- 工具调用在 `locked_session` 中执行，保护 `hop_count` 的 read-modify-write 原子性
- A2T 阶段 Agent 先回传 Phase 2（报告），再发送 NodeMessage 给 Tool Node
- T2A 阶段 Agent 收到返回后回传 Phase 1（确认），并更新 session trace

### 11.4 A2U（Agent → User）完整流程

```
  Agent (nanobot)             WebApp                    Protocol Node        User (Browser)
       │                        │                            │                    │
       │  OutboundMessage       │                            │                    │
       ├───────────────────────→│                            │                    │
       │                        │                            │                    │
       │                        │  1. tracer.append_hop      │                    │
       │                        │     behavior_type="A2U"     │                    │
       │                        │                            │                    │
       │                        │  ★ 2. BackMessage ★        │                    │
       │                        │  (Agent 签名 identity)     │                    │
       │                        ├───────────────────────────→│                    │
       │                        │                      Branch A: 暂存            │
       │                        │                            │                    │
       │                        │  3. NodeMessage(A2U)       │                    │
       │                        │     via WebSocket          │                    │
       │                        ├────────────────────────────┼───────────────────→│
       │                        │                            │                    │
       │                        │                            │  前端执行          │
       │                        │                            │  Phase 2 回传 ★    │
       │                        │                            │←───────────────────┤
```

1. nanobot 通过 MessageBus 发送 `OutboundMessage`
2. `ATTPChannel.send()` → `WebApp.send_message_to_user()`
3. WebApp 在 `locked_session` 中：
   - 获取 trace metadata → 提取 `user_did`
   - `AgentTracer.append_hop(behavior_type="A2U")` — 递增 intra hop_count
   - **先回传**：`send_back_message()` → Protocol Node
   - 更新 session trace
   - 构建 `NodeMessage` → WebSocket 广播给所有客户端
4. 前端收到 NodeMessage 后执行 Phase 2 回传

---

## 12. 设计模式与总结

### 12.1 设计模式

| 模式 | 应用场景 | 说明 |
|------|---------|------|
| **Facade 门面** | `AgentTracer` | 组合 KeyStore + ChainManager，提供统一溯源接口 |
| **Strategy 策略** | `HealthChecker` 协议 + `HeartbeatManager` | 调度逻辑与检查逻辑分离，支持插件化扩展 |
| **Observer 观察者** | `web_callback` / `channel_callback` | 事件驱动的 UI 通知和消息路由 |
| **Bridge 桥接** | `MCPToolBridge` | 桥接 MCP 协议和 ATTP 协议 |
| **Template Method** | `start()/stop()/reload()` 生命周期 | 所有组件遵循统一的生命周期模板 |
| **Factory Method** | `ATTPServer._create_agent()` | 动态创建 OpenANP Agent 类 |
| **Repository** | `ConfigManager` | 配置的持久化读写 |
| **Adapter** | `ATTPChannel` | 将 app 组件适配到 nanobot 框架 |
| **Proxy** | `PassthroughArgModel` | 透传远程工具参数，绕过函数签名内省 |
| **Lock Striping** | `locked_session()` | Per-session 异步锁，保护并发 read-modify-write |

### 12.2 统一生命周期管理

所有组件遵循一致的生命 cycle 模式：

```python
class Component:
    async def start(self) -> None:       # 启动（创建后台 Task / 绑定端口）
    async def stop(self) -> None:        # 停止（cancel Task / should_exit）
    async def reload(self, config) -> None:  # 热重载（stop → 更新参数 → start）
```

| 组件 | start 语义 | stop 语义 | reload 语义 |
|------|----------|---------|------------|
| ATTPClient | Agent 发现 | 清 running | 重建 auth/registry/缓存 |
| ATTPServer | uvicorn 启动 | should_exit + cancel | 重建 Agent/app + 等端口 |
| MCPToolBridge | MCP SSE 启动 | should_exit + cancel | 更新 host/port |
| HeartbeatManager | 后台 _loop Task | cancel Task | 更新 interval/timeout/max_fail |
| WebApp | FastAPI 启动 | should_exit + cancel + 关闭 WS | 仅更新属性 |

### 12.3 时序规则

ATTP Agent 端严格遵守**先回传协议节点，再发送消息**的时序规则：

| 场景 | 回传阶段 | 回传者 |
|------|---------|-------|
| A2A 发送 | Phase 2（发送方报告） | 发送方 Agent |
| A2A 接收 | Phase 1（接收方确认） | 接收方 Agent |
| U2A | Phase 1（接收方确认） | Agent（WebApp 代理） |
| A2U | Phase 2（发送方报告） | Agent（WebApp 代理） |
| A2T | Phase 2（发送方报告） | Agent（MCPToolBridge） |
| T2A | Phase 1（接收方确认） | Agent（MCPToolBridge） |

### 12.4 架构特点总结

| 特点 | 实现方式 |
|------|---------|
| **框架无关** | `app/` 组件无框架依赖，通过 `channels/` 适配不同框架 |
| **可插拔扩展** | Channel 插件 + HealthChecker 策略 + 动态 MCP 工具注册 |
| **差量热重载** | 基于 `changed_fields()` 检测变更，仅重载受影响的组件 |
| **并发安全** | `locked_session()` 保护 session 的 read-modify-write 原子性 |
| **优雅降级** | 无 trace 时记录 warning 并降级处理，不中断主流程 |
| **容错恢复** | 心跳 evict/retry 机制自动恢复连接和工具节点 |