# ATTP Agent 端代码与功能分析

> 本文档对 ATTP Agent 端运行时进行全面分析，覆盖两套等价的适配实现：
> - **Python**：`python/attp/app/`（框架无关组件）+ `python/attp/channels/nanobot.py`（nanobot 适配器）
> - **TypeScript**：`typescript/attp/`（Python 核心的跨语言移植）+ `typescript/attp/channels/openclaw/`（openclaw 原生插件）
>
> 两套适配共享同一份 ATTP 协议（`NodeMessage` / `RecordedHop` / `BackMessage` 序列化字节兼容），仅在"如何嵌入宿主框架"上不同。

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
- [11. openclaw 原生渠道插件（TypeScript）](#11-openclaw-原生渠道插件typescript)
- [12. Agent 端核心数据流](#12-agent-端核心数据流)
- [13. 设计模式与总结](#13-设计模式与总结)

---

## 1. 概述

ATTP Agent 端是 ATTP（Agent Trust and Traceability Protocol）协议在 Agent 节点上的完整运行时实现，负责：

| 能力 | 说明 |
|------|------|
| 身份管理和加密通信 | 基于 DID（`did:wba`）身份的 Agent 间通信，通过 OpenANP / DID-wba 实现互发现与消息传递（`dev` 分支为具体 HTTP/WS 传输 + DID-wba 鉴权，端到端加密见 `refactor/transport` 分支） |
| 消息追踪 | 通过 `AgentTracer.append_hop` 为每个出站跳构建 `RecordedHop`，严格区分 U2A / A2A / A2T / A2U 四种行为类型 |
| 双相回传确认 | 严格遵守"先回传协议节点（BackMessage），再发送业务消息"的时序规则 |
| 工具桥接 | 通过 MCP SSE Server 把远程 ATTP 工具节点桥接为本地 MCP 工具，供 Agent 内置 MCP Client 调用 |
| Web UI | 提供 WebSocket + REST API 前端通道，支持用户交互与配置管理 |
| 健康监测 | 可插拔的心跳检查器，监控远程 Agent 和工具节点的可达性，失败自动 evict + 重连/重发现 |

### 意图追踪层的参与方式

ATTP v0.3.0 的**意图追踪层**（位于 `core/analysis`，本文不展开）对每一跳做 per-hop / stateful 评分：分数 0–10、5 档严重度、4 个维度，裁决由代码衍生；横轴触发条件为 `F = Σs_i² > R_S(25.0)`，并设置最小消息数门槛；协议节点侧的 `/record` 异步处理。

**Agent 节点在此层的职责仅限于两步**（其余由协议节点完成）：

1. **构建并签名每一跳**：`AgentTracer.append_hop(..., behavior_type=...)` 生成带 `hop_count` 递增与 `sigContent` 签名的 `RecordedHop`。Agent 端实际产生的出站行为类型为 `A2A`（`client.py`）、`A2T`（`mcp_tool_bridge.py`）、`A2U`（`web/app.py`）；入站 `U2A` 的 hop 由前端构建、Agent 仅做 Phase-1 回传。
2. **回传协议节点**：每次出/入站都调用 `send_back_message(...)`（Phase-2 报告 / Phase-1 确认）把 hop 送往 `protocol_url`，由协议节点落库并交由意图层评分。

> Agent 端不做评分、不做横向触发判断；它只保证"每一跳都被正确构建、签名、回传"。

### 两套适配实现

| 维度 | Python（nanobot 适配器） | TypeScript（openclaw 插件） |
|------|--------------------------|----------------------------|
| 宿主框架 | nanobot（Python） | openclaw（Node.js / TS） |
| 组件位置 | `python/attp/app/` 框架无关组件 | `typescript/attp/app/` 对应的进程内服务 |
| 渠道文件 | `python/attp/channels/nanobot.py` | `typescript/attp/channels/openclaw/` |
| 端口（默认） | A2A=8000 / WebUI=8001 / MCP=8002 | A2A=19000 / WebUI=19001 / MCP=19002 |
| 接入方式 | setuptools entry-point（`nanobot.channels`） | openclaw 插件清单（`openclaw.plugin.json`） |

两者默认端口相差 +11000，**可在同一主机共存**而不冲突。

---

## 2. 模块架构总览

### 2.1 Python 目录结构

```
python/attp/
├── channels/
│   ├── __init__.py
│   └── nanobot.py                   # nanobot 框架适配器（ATTPChannel）
│
└── app/
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
        ├── app.py                   # WebApp — WebSocket + REST API
        └── api/
            ├── __init__.py
            ├── config_setting.py    # 配置读写 API
            └── node_status.py       # 节点状态 API
```

### 2.2 TypeScript 目录结构（openclaw 插件相关）

```
typescript/attp/
├── core/                            # Python 核心的跨语言移植（序列化字节兼容）
│   ├── message/event.ts             # ← 翻译自 python/attp/core/message/event.py
│   ├── agent-tracer.ts              # AgentTracer
│   ├── authentication/              # DID-wba 密钥 / 签名 / 解析
│   ├── provenance/                  # 链 / 哈希
│   └── message/back-sender.ts       # send_back_message
│
├── app/                             # host-agnostic 的进程内服务（不 import 任何 channel 代码）
│   ├── config.ts                    # loadAgentConfig — 字段选取（端口上浮）
│   ├── attp-server.ts               # startAttpServer — WebUI + Agent Server 双端口
│   ├── mcp-node.ts                  # startMcpNode — MCP 工具节点（send_message over SSE）
│   ├── web.ts                       # WsHub / parseInboundNodeMessage / nodeMessageFrame
│   ├── server.ts                    # parseInboundRequest / verifyInbound（DID-wba 验签）
│   ├── client.ts                    # discoverAgent / sendMessage
│   └── tools.ts                     # executeSendMessage
│
└── channels/openclaw/               # openclaw 渠道插件本体
    ├── package.json                 # @attp/openclaw-channel
    ├── openclaw.plugin.json         # 插件清单
    ├── index.ts                     # defineChannelPluginEntry 入口
    └── src/
        ├── channel.ts               # attpPlugin（base + outbound + gateway）
        ├── config.ts                # readChannelConfig
        ├── inbound.ts               # dispatchAttpInbound
        ├── outbound.ts              # deliverOutbound
        └── runtime.ts               # AttpRuntime 共享状态
```

### 2.3 Python 组件依赖关系

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
  │
  ├── ATTPClient (app/client.py)                  # 出站通信（A2A / A2U）
  │     ├── DIDWbaAuthHeader (anp)
  │     ├── RemoteAgent (anp)
  │     └── AgentTracer
  │
  ├── ATTPServer (app/server.py)                  # 入站通信（A2A receive）
  │     ├── FastAPI + OpenANP Agent
  │     └── AgentTracer
  │
  ├── MCPToolBridge (app/tools/mcp_tool_bridge.py) # 工具桥接（A2T / T2A）
  │     ├── FastMCP (MCP SSE Server)
  │     ├── ATTPClient (send_callback)
  │     └── AgentTracer
  │
  ├── HeartbeatManager (app/heartbeat/heartbeat.py) # 健康监测
  │     ├── AgentHealthChecker → ATTPClient
  │     └── ToolNodeHealthChecker → MCPToolBridge
  │
  ├── WebApp (app/web/app.py)                     # 前端通道（U2A / A2U）
  │     ├── FastAPI + WebSocket
  │     └── AgentTracer
  │
  ├── AppSessionManager (core/sessions/app.py)    # 内存会话 + per-session 锁
  │
  └── ProtocolNode (protocol_node/)               # 可选：内嵌协议节点
```

---

## 3. Channel 可插拔适配层

### 3.1 设计理念

`channels/` 是 ATTP Agent 端的**可插拔适配层**。每个 Channel 是一个独立插件，负责：

1. **组装** `app/` 中的所有框架无关组件（Client、Server、ToolBridge、Heartbeat、WebApp）
2. **适配**特定框架的消息总线、生命周期管理、配置加载等接口
3. **桥接**框架消息与 ATTP 协议（通过回调注入）

当前已实现**两套** Channel 适配器，二者行为等价、拓扑相同（三端口），仅宿主与语言不同：

| 适配器 | 路径 | 语言 | 宿主 |
|--------|------|------|------|
| **nanobot** | `python/attp/channels/nanobot.py` | Python | nanobot |
| **openclaw** | `typescript/attp/channels/openclaw/` | TypeScript | openclaw |

nanobot 适配器在 §3.2 详述；openclaw 适配器的完整说明见 [§11](#11-openclaw-原生渠道插件typescript)。

### 3.2 nanobot 适配器（`channels/nanobot.py`）

继承 `nanobot.channels.base.BaseChannel`，实现 `start()/stop()/send()` 接口，并通过 setuptools entry-point 注册：

```
[nanobot.channels]
attp = attp.channels.nanobot:ATTPChannel        # 见 python/attp.egg-info/entry_points.txt
```

#### 3.2.1 Channel 配置

```python
class ATTPConfig(Base):                          # nanobot.py:66
    """ATTP channel configuration."""
    enabled: bool = False
    config_path: str = "~/.attp/agent/nanobot/config.json"
    allow_from: list[str] = Field(default_factory=lambda: ["*"])
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | `bool` | 是否启用 ATTP Channel |
| `config_path` | `str` | ATTP 配置文件路径（交由 `ConfigManager` 加载） |
| `allow_from` | `list[str]` | 允许的消息来源（默认 `["*"]` 全部允许；当前为声明式字段） |

#### 3.2.2 组件组装

`start()` 按依赖关系组装所有组件（`nanobot.py:86`）：

```
ATTPChannel.start()
  │
  ├── 1. ConfigManager(config_path)         → 加载配置（构造即 load）
  ├── 2. AgentTracer()                      → 轻量级溯源（Agent 侧无 DB）
  ├── 3. WebApp(web_config, channel_callback=self._receive)
  ├── 4. AppSessionManager()                → 内存会话管理（per-session 异步锁）
  ├── 5. ATTPClient(agent_did, client_config,
  │                session_manager, web_callback=web_app.record_message,
  │                tracer)
  ├── 6. ATTPServer(agent_did, server_config,
  │                session_manager, web_callback=web_app.record_message,
  │                attp_channel_callback=self._receive, tracer)
  ├── 7. HeartbeatManager(heartbeat_config)
  │     ├── add_checker(AgentHealthChecker(attp_client, timeout, max_fail))
  │     └── add_checker(ToolNodeHealthChecker(tool_bridge, timeout, max_fail))
  ├── 8. MCPToolBridge(tool_config, attp_client, tracer,
  │                    session_manager, agent_did,
  │                    send_callback=attp_client.send_message)
  ├── 9. ProtocolNode(config_path)          → 可选：仅 protocol_node.enabled=true 时
  │
  ├── 10. discover_all_tool_nodes(tool.tool_node_ads)   → 启动前自动发现工具节点
  │
  └── 11. asyncio.TaskGroup()               → 并发启动所有组件
        ├── attp_client.start()
        ├── attp_server.start()
        ├── heartbeat_manager.start()
        ├── tool_bridge.start()
        ├── web_app.start(attp_client, config_manager,
        │                 reload_callback=self.reload,
        │                 session_manager, agent_did, tracer,
        │                 private_key_path=attp_client.auth.private_key_path)
        └── protocol_node.start()           → 可选
```

> ⚠️ **`web_callback` 当前是空操作**：`web_app.record_message` 在 `web/app.py:266` 首行即 `return`（注释"已被 send_message_to_user 替代"）。因此 `ATTPClient`/`ATTPServer` 内对 `web_callback` 的调用不会产生任何 UI 效果；UI 的实际数据通道是 `WebApp.send_message_to_user`（由 `ATTPChannel.send` 触发，构建 A2U NodeMessage 经 WS 下行）。详见 [§9.2](#92-websocket-消息处理)。

**关键依赖注入关系**：

| 组件 | 注入的依赖 |
|------|----------|
| `ATTPClient` | `session_manager`, `web_callback`(=record_message，空操作), `tracer` |
| `ATTPServer` | `session_manager`, `web_callback`(=record_message，空操作), `attp_channel_callback`(=_receive), `tracer` |
| `MCPToolBridge` | `attp_client`, `tracer`, `session_manager`, `send_callback=attp_client.send_message` |
| `AgentHealthChecker` | `attp_client`, `timeout`, `max_fail` |
| `ToolNodeHealthChecker` | `tool_bridge`, `timeout`, `max_fail` |
| `WebApp` | `channel_callback=self._receive` → 注入 nanobot MessageBus |

#### 3.2.3 MCP 启动竞态补丁

`nanobot.py:32-63` 在模块导入期（早于 `asyncio.gather` 启动）为 `nanobot.agent.loop.AgentLoop._connect_mcp` **注入重试逻辑**（不改 nanobot 源码）：

- **背景**：nanobot gateway 中 `agent.run()` 首行 `_connect_mcp`（只连一次）与 `channels.start_all()`（起 `MCPToolBridge` → uvicorn 绑 8002）经 `asyncio.gather` 并发；桥绑定晚几毫秒 → MCP SSE 连接被拒，而 ATTP 总线消息只走 `run()` 的 bus 不触发重试 → 工具永久不可用。
- **做法**：`_connect_mcp_with_retry` 循环最多 50 次（约 5s），每次调用原方法后等 0.1s，直到 `_mcp_connected=True` 即停。
- **失败兜底**：导入 nanobot 失败时静默跳过（`except Exception`）。

#### 3.2.4 消息路由

```
用户 → WebApp(WS) → channel_callback → ATTPChannel._receive()
                                              ↓
                                      （继承自 BaseChannel）_handle_message()
                                              ↓
                                      nanobot MessageBus → Agent LLM 处理
                                              ↓
                                      ChannelManager → ATTPChannel.send()
                                              ↓
                                      WebApp.send_message_to_user() → 用户（A2U）
```

- `_receive(sender, chat_id, content, media)`（`nanobot.py:206`）— 从 WebApp / ATTPServer 接收消息，调用继承的 `_handle_message` 注入 nanobot MessageBus。
- `send(msg: OutboundMessage)`（`nanobot.py:197`）— 从 nanobot MessageBus 接收回复，过滤空内容后交给 `WebApp.send_message_to_user(msg.content, msg.chat_id)` 构造 A2U 下行。

#### 3.2.5 热重载（Hot Reload）

`reload(old_cfg, new_cfg)`（`nanobot.py:215`）实现**差量热重载**——仅重载配置发生变化的组件：

| 变化项 | 处理策略 |
|--------|---------|
| DID 或 ATTPClient 配置 | `attp_client.reload(new_cfg.attp_client, new_cfg.did)` |
| DID 或 ATTPServer 配置 | `attp_server.reload(new_cfg.attp_server, new_cfg.did)` |
| Heartbeat 配置 | `heartbeat_manager.reload(new_cfg.heartbeat)` |
| Tool 配置（host/port） | `tool_bridge.reload(new_cfg.tool)` |
| Tool 配置（tool_node_ads 变化） | 先 `unregister_tool_node(did)` 注销所有旧节点 → 再 `discover_all_tool_nodes` 新列表 |
| ProtocolNode 配置 | 已启用则 `reload_config()`；未启用则 warning 提示需手动重启 |
| WebApp 配置（host/port） | 仅更新 `host`/`port` 属性（**无法热重载端口**，记 warning） |

热重载由 Web API `POST /api/config/reload` 触发（见 [§9.3](#93-rest-api)）：

```
POST /api/config/reload
  → old_cfg = deepcopy(current)
  → config_manager.load()                    # 重新读取磁盘
  → new_cfg = current
  → reload_callback(old_cfg, new_cfg)        # = ATTPChannel.reload()
```

#### 3.2.6 生命周期管理

```python
# 启动：并发启动（asyncio.TaskGroup）
async with asyncio.TaskGroup() as tg:
    tg.create_task(self._attp_client.start())
    tg.create_task(self._attp_server.start())
    tg.create_task(self._heartbeat_manager.start())
    tg.create_task(self._tool_bridge.start())
    tg.create_task(self._web_app.start(...))
    if self._protocol_node:
        tg.create_task(self._protocol_node.start())

# start() 必须阻塞直到 stop() 被调用
while self._running:
    await asyncio.sleep(1)

# 停止：并发停止
async with asyncio.TaskGroup() as tg:
    tg.create_task(self._heartbeat_manager.stop())
    tg.create_task(self._tool_bridge.stop())
    tg.create_task(self._attp_client.stop())
    tg.create_task(self._attp_server.stop())
    tg.create_task(self._web_app.stop())
    if self._protocol_node:
        tg.create_task(self._protocol_node.stop())
```

### 3.3 openclaw 适配器（简述）

`typescript/attp/channels/openclaw/` 是 ATTP 的第二个官方渠道适配器，作为 openclaw 原生插件在进程内拉起 ATTP 的三端口服务（WebUI / Agent Server / MCP）。其结构、端口拓扑、入站/出站分流、安装方式与示例配置在 [§11](#11-openclaw-原生渠道插件typescript) 完整说明。

---

## 4. 配置管理（Config）

> 本节描述 Python 端 `app/config/config.py`。TS 端 `app/config.ts` 的 `loadAgentConfig` 复用**同一份 schema**，仅做字段选取并把端口上浮为 `AgentConfig`（见 [§11.5](#115-配置读取-configts)）。

### 4.1 配置模型层级

基于 Pydantic v2 的多层配置模型，支持 camelCase / snake_case 双格式键名（`alias_generator=to_camel` + `populate_by_name=True`）：

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
  │     ├── server_host: str = "127.0.0.1"
  │     ├── server_port: int = 8000
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

> ℹ️ Python 的 `ATTPServerConfig` **不含** `publicBaseUrl` 字段；该字段是 TS 侧（openclaw）为暴露外部可达 URL 而新增的，TS `loadAgentConfig` 会读 `attpServer.publicBaseUrl`，缺省回退 `http://127.0.0.1:${agentServerPort}`。

### 4.2 ATTPBase — 配置基类

```python
class ATTPBase(BaseModel):                                # config.py:22
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def changed_fields(self, other: ATTPBase) -> set[str]:
        """返回与 other 值不同的字段名集合（用于差量热重载判断）。"""
```

特性：
- **双格式键名**：JSON 前端用 camelCase，Python 后端用 snake_case，二者皆可构造。
- **变更检测**：`changed_fields()` 基于 `model_dump()` 对比，用于热重载判断。

### 4.3 ConfigManager

```python
class ConfigManager:                                      # config.py:121
    def __init__(self, attp_config_path: str | Path)   # 构造即 load
    def load(self) -> None                            # 从磁盘加载（缺失则 FileNotFoundError）
    def update(self, partial: dict) -> ATTPConfigFile # 部分更新（合并 + 验证 + 写盘）
```

#### update() — 部分更新

支持嵌套部分更新，请求体只需包含要更新的字段：

```
PUT /api/config
{
    "attpClient": {
        "nodeAds": ["http://new-agent/ad.json"]
    }
}
```

#### _deep_merge() — 深度合并

```python
def _deep_merge(base, override, list_strategy="extend") -> dict   # config.py:86
```

| 数据类型 | `list_strategy="extend"`（函数默认） | `list_strategy="replace"` |
|---------|--------------------------------------|---------------------------|
| `dict` | 递归深度合并 | 递归深度合并 |
| `list` | 去重合并（追加 override 中新元素） | 完全用 override 替换 |
| 其他 | 直接覆盖 | 直接覆盖 |

> ⚠️ `ConfigManager.update()` 实际调用的是 `_deep_merge(current_data, partial, list_strategy="replace")`（`config.py:159`）——即 **PUT /api/config 对列表字段做整体替换**，而非追加。`"extend"` 仅是函数签名默认值，当前无调用方使用。

---

## 5. 客户端（ATTPClient）

ATTPClient 是 Agent 间通信的**出站客户端**，负责发现远程 Agent、维护连接缓存、发送 ATTP 消息（A2A）。定义在 `app/client.py:24`。

### 5.1 初始化

```python
class ATTPClient:
    def __init__(
        self,
        agent_did: str,
        client_config: ATTPClientConfig,
        session_manager: AppSessionManager | None = None,
        web_callback = None,               # 当前注入 record_message（空操作）
        tracer: AgentTracer = None,
    )
```

**内部状态**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `auth` | `DIDWbaAuthHeader` | DID WBA 认证头生成器（`did_doc_path` + `did_key_path`） |
| `registry` | `list[str]` | 远程 Agent ad.json URL 列表（来自 `client_config.node_ads`） |
| `remote_agents` | `dict[str, RemoteAgent]` | 已连接远程 Agent 缓存（DID → RemoteAgent） |
| `registered_agents` | `dict[str, dict]` | 已注册 Agent 元信息（DID → `{did, name, description, ad_url, capabilities}`） |
| `failed_urls` | `set[str]` | 连接失败的 URL（用于心跳重连） |

### 5.2 Agent 发现与缓存

#### initialize()（`client.py:90`）

启动时从 `registry` 加载所有 ad.json，逐个通过 OpenANP SDK 发现：

```
initialize()
  for ad_path in registry:
    remote = _get_remote_agent(ad_path)
    ├── 成功 → remote_agents[identifier] = remote；registered_agents[identifier] = {...}
    └── 失败 → failed_urls.add(ad_path)
```

#### _get_remote_agent()（`client.py:115`）

单 Agent 发现流程：

```
1. RemoteAgent.discover(target_ad, auth)          # OpenANP SDK 发现
2. HTTP GET target_ad                              # 再读一次 ad.json 拿 identifier
3. identifier = ad_data["identifier"]              # 作为缓存 key
4. 缓存到 remote_agents + registered_agents
```

### 5.3 统一消息发送

#### send_message() — 统一入口（`client.py:157`）

```python
async def send_message(self, target: str, content: str, chat_id: str) -> str
```

路由规则：

| target 格式 | 路由目标 |
|-------------|---------|
| `did:...` 前缀 | Agent 间通信（A2A），在 `locked_session(chat_id)` 内执行 |
| 其他 | 返回 `"Error: Invalid target format. Use 'did:wba:...'"` |

> 该方法也是 `MCPToolBridge.send_message_tool` 的 `send_callback`，故 MCP 工具发送消息最终也走这里。

#### send_to_agent() — A2A 发送（`client.py:198`）

完整 A2A 发送流程，严格遵循 ATTP 时序规则：

```
send_to_agent(target_did, sender_did, content, message_type="agent_request", metadata)
  │
  ├── 1. 查找/重连 RemoteAgent
  │     remote = remote_agents.get(target_did)
  │     if not remote → retry_failed_urls(target_did)
  │
  ├── 2. 追加溯源跳（在调用方已持有的 locked_session 内）
  │     nonce = uuid4().hex
  │     metadata = tracer.append_hop(metadata, content, sender_did, target_did,
  │                                  private_key_path, behavior_type="A2A")
  │
  ├── 3. 构建 NodeMessage
  │     recorded = RecordedHop.from_dict(metadata["recorded_hop"])
  │     node_msg = NodeMessage(protocol_url, nonce, recorded)
  │
  ├── 4. ★ 时序规则：先回传协议节点（Phase 2，发送方报告）★
  │     if protocol_url and private_key_path:
  │         private_key = tracer.load_private_key(private_key_path)
  │         send_back_message(protocol_url, sender_did, nonce, recorded, private_key)
  │
  ├── 5. 再发送 NodeMessage 给目标 Agent
  │     remote.receive_message(sender_did, content, message_type,
  │                            metadata={"NodeMessage": node_msg.to_dict()})
  │
  └── 6. 调用 web_callback（当前为 record_message 空操作，不产生 UI 效果）
        await web_callback(content, {is_A2A_message:True, direction:"out", other_did, Session_ID})
```

### 5.4 失败重连

```python
async def retry_failed_urls(self, target_did: str = None) -> RemoteAgent | None   # client.py:300
```

| 调用场景 | target_did | 行为 |
|---------|-----------|------|
| Agent 不在缓存中 | 指定 DID | 遍历 `failed_urls` 尝试重连，命中目标即返回 |
| 心跳批量重连 | `None` | 遍历所有 `failed_urls`，成功则移出失败集合 |

### 5.5 生命周期

```python
async def start()                                   # initialize() + 设 running
async def stop()                                    # 清 running
async def reload(client_config, agent_did)          # 清 running → 重建 auth/registry → 清三缓存 → reinitialize → 设 running
```

---

## 6. 服务端（ATTPServer）

ATTPServer 是 Agent 间通信的**入站服务端**，基于 FastAPI + OpenANP SDK 接收来自其他 Agent 的消息。定义在 `app/server.py:26`。

### 6.1 架构设计

```python
class ATTPServer:
    def __init__(
        self,
        agent_did: str,
        server_config: ATTPServerConfig,
        session_manager: AppSessionManager,
        web_callback = None,                 # 当前注入 record_message（空操作）
        attp_channel_callback = None,        # Channel 消息路由回调（=ATTPChannel._receive）
        tracer: AgentTracer | None = None,
    )
```

ATTPServer 通过 `_create_agent()`（`server.py:68`）**动态创建** OpenANP Agent 类并挂到 FastAPI：

```
ATTPServer
  ├── FastAPI app
  │     └── include_router(Agent.router())   # OpenANP Agent 路由
  │
  └── Agent（动态创建，闭包捕获实例属性）
        ├── @interface health() -> "ok"      # 健康检查端点
        └── @interface receive_message(...)  # 消息接收处理
```

### 6.2 消息接收处理

`receive_message()` 仅处理 `agent_request` 类型；`record` 类型由 ProtocolNode 的 DataPort 处理。

```
receive_message(sender_did, content, message_type="agent_request", metadata)
  │
  ├── 1. 解析 NodeMessage
  │     node_msg = NodeMessage.from_dict(metadata["NodeMessage"])
  │     session_id = node_msg.recorded_hop.session_id
  │
  ├── 2. 存储 trace 到 session
  │     session = session_manager.get_or_create(session_id)
  │     session.set_trace_metadata({recorded_hop, protocol_url})
  │     session_manager.save(session)
  │
  ├── 3. 路由到 Channel（attp_channel_callback）
  │     → ATTPChannel._receive → nanobot MessageBus → Agent LLM
  │
  ├── 4. 调用 web_callback（当前为 record_message 空操作）
  │
  ├── 5. ★ Phase 1 回传：向发送方的协议节点确认 ★
  │     _send_proof_callback(node_msg, agent_did, tracer, private_key_path)
  │       → send_back_message(protocol_url, agent_did, nonce, recorded_hop, private_key)
  │
  └── 6. 返回 "Message received"
```

### 6.3 Phase 1 回传回调

`_send_proof_callback`（`server.py:79`，闭包内定义）是服务端的 Phase 1 回传实现：

```
_send_proof_callback(node_msg, agent_did, tracer_ref, private_key_path)
  ├── 若 tracer 或 private_key_path 不可用 → 直接返回
  ├── private_key = tracer_ref.load_private_key(private_key_path)
  └── send_back_message(protocol_url, agent_did, nonce, recorded_hop, private_key)
        → POST {protocol_url}/record（BackMessage）
      失败仅 warning，不阻断主流程
```

### 6.4 生命周期

```python
async def start()                       # 创建 uvicorn.Server + asyncio.create_task(serve())
async def stop()                        # should_exit=True → 最多等 5s → 仍卡则 cancel serve_task
async def reload(server_config, agent_did)  # stop → _apply_config → 重建 Agent/FastAPI app → _wait_for_port → start
```

**端口等待**：`reload()` 调用 `_wait_for_port()`（`server.py:239`）轮询绑定探测端口是否释放（最长 10s，每 0.3s 探测一次，`SO_REUSEADDR`），避免 `Address already in use`。

---

## 7. 工具桥接器（MCPToolBridge）

MCPToolBridge 同时充当两个角色：

| 角色 | 协议 | 说明 |
|------|------|------|
| **MCP SSE Server** | MCP (Model Context Protocol) | 暴露给 nanobot（Agent 内置 MCP Client）连接 |
| **ATTP Tool Client** | ATTP | 将工具调用通过 ATTP 协议发送到远程工具节点 |

定义在 `app/tools/mcp_tool_bridge.py:124`。

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
        send_callback: Callable[[str, str, str], Awaitable[str]] | None = None,
    )
```

**内部状态**：

| 属性 | 类型 | 说明 |
|------|------|------|
| `_mcp` | `FastMCP` | MCP Server 实例（名称 `"attp-tools"`） |
| `_tool_nodes` | `dict[str, ToolNodeInfo]` | 已发现的远程工具节点（DID → info） |
| `_node_tool_map` | `dict[str, list[str]]` | DID → 注册的 MCP 工具名列表 |
| `_registry_lock` | `asyncio.Lock` | 工具注册/注销并发保护 |

### 7.2 核心工具 — send_message_tool

`_register_core_tools()`（`mcp_tool_bridge.py:185`）注册一个固定工具 `send_message_tool`，其描述强约束 LLM 行为（"必须且只能使用此工具来发送消息给其他 Agent；绝对不允许自行构造 JSON-RPC 接口"），内部委托 `_send_callback`（即 `attp_client.send_message`）：

```
send_message_tool(target, content, chat_id) → str
  └── _send_callback(target, content, chat_id)
        → attp_client.send_message(target, content, chat_id)   # A2A
```

### 7.3 动态工具注册/注销

#### 工具名生成规则（`mcp_tool_bridge.py:221`）

```python
_build_tool_mcp_name(node_name, tool_name, did)
  → "{sanitized_node_name}_{did_hash}__{tool_name}"
```

示例：`weather_service_abc12345__get_weather`（`did_hash` 取 DID 末段前 8 字符，避免不同节点同名冲突）。

#### 注册流程（`register_tool_node`，`mcp_tool_bridge.py:296`）

```
register_tool_node(tool_info: ToolNodeInfo)        # 持 _registry_lock
  ├── 1. 缓存 _tool_nodes[tool_info.did] = tool_info
  └── 2. 遍历 tool_info.tools:
        ├── 生成 mcp_name
        ├── 描述前缀 "[来自工具节点 {name} ({did})]"
        ├── 强制注入 chat_id 到 inputSchema.properties 并加入 required
        ├── 创建 PassthroughArgModel 子类（ConfigDict(extra="allow")）
        ├── 直接构造 MCPTool 对象（绕过 add_tool() 的函数签名内省）
        └── 注册到 _mcp._tool_manager._tools[mcp_name]
```

**PassthroughArgModel**（`mcp_tool_bridge.py:72`）— 透传参数模型，绕过 FastMCP 的函数签名内省限制：

```python
class PassthroughArgModel(ArgModelBase):
    model_config = ConfigDict(extra="allow")  # 接受任意字段

    def model_dump_one_level(self) -> dict[str, Any]:
        # 返回声明字段 + __pydantic_extra__（远程工具的实际参数）
```

handler 在运行时把除 `chat_id` 外的所有 kwargs `json.dumps` 为 `arguments`，透传给 `_call_tool_node`。

#### 注销流程（`unregister_tool_node`，`mcp_tool_bridge.py:326`）

```
unregister_tool_node(did)                          # 持 _registry_lock
  ├── 从 _node_tool_map[did] 取所有 mcp_name → 逐个 _unregister_remote_tool
  └── 移除 _tool_nodes[did]
```

### 7.4 工具节点发现

#### 跨容器端点改写（`_rewrite_endpoint_host`，`mcp_tool_bridge.py:33`）

```
_rewrite_endpoint_host(ad_url, attp_endpoint)
  → 用 ad_url 的 host:port 替换 attp_endpoint 的 netloc（保留 scheme/path/query）
```

**背景**：工具节点在 `host=0.0.0.0` 时会把广告里的 `attp_endpoint` 写成 `localhost:port`（自身视角），在 agent 容器内不可达；既然 ad 已从 `ad_url` 成功拉取，说明 `ad_url` 的 host:port 可达，工具调用也走它。

#### 发现流程（`discover_tool_node`，`mcp_tool_bridge.py:519`）

```
discover_tool_node(ad_url) → ToolNodeInfo | None
  ├── HTTP GET ad_url → ad_data
  ├── 验证 ad_data["type"] == "attp-tool-node"
  ├── 构建 ToolNodeInfo(did=identifier, name, description,
  │                     attp_endpoint=_rewrite_endpoint_host(ad_url, ad_data["attp_endpoint"]),
  │                     tools=ad_data["mcp_tools"], public_key_endpoint, ad_url)
  ├── 验证必填字段（identifier / attp_endpoint）
  └── register_tool_node(tool_info)

discover_all_tool_nodes(ad_urls)        # asyncio.gather 并行发现，单失败仅记录
```

#### ToolNodeInfo 数据结构（`mcp_tool_bridge.py:98`）

```python
class ToolNodeInfo:
    did: str                       # 工具节点 DID
    name: str                      # 节点名称
    description: str               # 节点描述
    attp_endpoint: str             # ATTP 消息接收端点（已改写）
    tools: list[dict]              # MCP 工具定义 [{name, description, inputSchema}]
    public_key_endpoint: str       # 公钥获取端点
    ad_url: str                    # 来源 ad.json URL（心跳恢复用）
```

### 7.5 ATTP 工具调用 — 完整回传时序

工具调用涉及 **4 次回传**（A2T 2 次、T2A 2 次）。入口 `_call_tool_node`（`mcp_tool_bridge.py:344`）获取工具信息与私钥后，在 `locked_session(chat_id)` 内调用 `_call_tool_node_locked`（`mcp_tool_bridge.py:391`）：

```
_call_tool_node_locked(session, tool_did, tool_name, arguments, chat_id, ...)
  │
  ├── 1. 取 session trace metadata + 生成 nonce
  ├── 2. tracer.append_hop(behavior_type="A2T")           # 递增 hop_count
  ├── 3. 构建 NodeMessage(A2T)
  │
  ├── === 第一跳 A2T ===
  │     ├── ★ BackMessage #1 (Phase 2, Agent 报告) → Protocol Node ★
  │     │     send_back_message(protocol_url, agent_did, nonce, recorded_hop_a2t, private_key)
  │     │
  │     └── HTTP POST NodeMessage(A2T) → Tool Node
  │           endpoint = tool_info.attp_endpoint
  │           body = node_message_a2t.to_dict()           # 60s 超时
  │
  └── === 第二跳 T2A ===（仅当 protocol_url && private_key）
        ├── 解析返回 NodeMessage(T2A)
        ├── result = json.loads(recorded_hop_t2a.content)["result"]
        ├── ★ BackMessage #4 (Phase 1, Agent 确认 T2A) → Protocol Node ★
        │     send_back_message(protocol_url, agent_did, nonce_t2a, recorded_hop_t2a, private_key)
        ├── 更新 session trace（用 T2A 的 recorded_hop）
        └── 返回 result

  （若 protocol_url 或 private_key 缺失：直接 return str(result_body)，不做 T2A 续链）
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
async def start()                  # FastMCP.sse_app() → uvicorn.Config(沉默日志) → asyncio.create_task(serve)
async def stop()                   # should_exit=True → cancel task
async def reload(tool_config)      # stop → 更新 host/port → start（callback 不变）
```

---

## 8. 心跳管理（Heartbeat）

心跳系统采用**策略模式**，将调度逻辑与检查逻辑分离。

### 8.1 HealthChecker 协议（`heartbeat.py:25`）

```python
@runtime_checkable
class HealthChecker(Protocol):
    async def check(self) -> None: ...
```

所有健康检查器必须实现 `check()`。`timeout` / `max_fail` 阈值由各 Checker 自持（`HeartbeatManager` 只负责调度，不感知阈值）。

### 8.2 HeartbeatManager（`heartbeat.py:38`）

通用心跳调度器：

```python
class HeartbeatManager:
    def __init__(self, heartbeat_config: HeartbeatConfig)
        self._interval = heartbeat_config.interval    # 心跳间隔（秒）
        self._timeout   = heartbeat_config.timeout    # 单次超时（秒，传给 checker 用）
        self._max_fail  = heartbeat_config.max_fail   # 连续失败阈值（传给 checker 用）
```

#### 调度循环（`_loop`，`heartbeat.py:122`）

```python
async def _loop(self):
    while True:
        await asyncio.sleep(self._interval)         # CancelledError → break
        for checker in self._checkers:
            try: await checker.check()
            except Exception as e: logger.error(...)  # 单 checker 异常不影响其他
```

#### Checker 管理

```python
def add_checker(checker)              # 注册
def remove_checker(checker)           # 移除
def checkers -> list[HealthChecker]   # 只读视图（返回副本）
```

### 8.3 AgentHealthChecker（`_agent.py:23`）

检查远程 Agent 连接状态。构造参数 `attp_client, timeout=90, max_fail=3`，内部维护 `_fail_counts: dict[str, int]`。

#### check() 流程

```
check()
  ├── 1. 重连失败的 URL
  │     attp_client.retry_failed_urls(target_did=None)
  │
  └── 2. 检查所有已连接 Agent
        for did, remote in remote_agents.items():
            _check_agent(did, remote)
              ├── asyncio.wait_for(remote.health(), timeout)
              ├── 返回 "ok" → 重置失败计数
              ├── 超时 / 异常 / 非 "ok" → 递增失败计数
              └── 失败次数 >= max_fail → _evict(did)
```

#### Evict 策略（`_evict`，`_agent.py:124`）

```
agent 连续失败 >= max_fail 次
  → remote_agents.pop(did)（停止向其发送消息）
  → fail_counts.pop(did)
  → 从 registered_agents 取 ad_url → failed_urls.add(ad_url)（下次心跳自动重连）
```

### 8.4 ToolNodeHealthChecker（`_tool.py:24`）

检查远程工具节点健康状态。构造参数 `tool_bridge, timeout=90, max_fail=3`，内部维护 `_fail_counts` 与 `_failed_nodes: dict[ad_url, did]`。

#### check() 流程

```
check()
  ├── 1. _check_tool_nodes()
  │     for did, info in tool_bridge.get_tool_nodes().items():
  │         HTTP GET {info.attp_endpoint}/health  （总超时 = timeout）
  │         ├── 200 → 重置失败计数
  │         └── 非 200 / 异常 → _record_fail(did, info.ad_url)
  │               ├── 失败次数 < max_fail → 记 debug 日志
  │               └── 失败次数 >= max_fail → _evict(did, ad_url)
  │                     ├── tool_bridge.unregister_tool_node(did)   # 移除 MCP 工具
  │                     └── _failed_nodes[ad_url] = did
  │
  └── 2. _retry_failed_nodes()
        for ad_url in _failed_nodes:
            tool_bridge.discover_tool_node(ad_url)
            ├── 成功 → 移出 _failed_nodes（MCP 工具自动重新注册）+ 清失败计数
            └── 失败 → 留在 _failed_nodes，下次心跳再试
```

#### 工具节点的 Evict / Recover 生命周期

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
async def start()                       # 创建后台 _loop Task（已运行则 warning 并返回）
async def stop()                        # cancel Task + 等待退出
async def reload(heartbeat_config)      # stop → 更新 interval/timeout/max_fail → start（Checkers 保持不变）
```

---

## 9. Web UI 通道（WebApp）

WebApp 是面向用户的前端通道，提供 WebSocket 实时通信和 REST API 管理。定义在 `app/web/app.py:29`。

> 协议相关 API（trace / analysis）不在 WebApp，而由 ProtocolNode 的 ApiPort 提供。WebApp 只承载通用 API（config / node_status）。

### 9.1 架构

```
WebApp
  ├── FastAPI app
  │     ├── CORSMiddleware（allow_origins=["*"], methods=["*"], headers=["*"]）
  │     ├── GET  /api/status           → {status, ws_clients}
  │     ├── WebSocket /ws              → 双向实时通信（NodeMessage 协议）
  │     ├── GET  /api/nodes            → Agent 节点列表（mount_api 挂载）
  │     ├── GET  /api/config           → 配置读取（可选 ?refresh=true）
  │     ├── PUT  /api/config           → 配置更新（写盘，不热重载）
  │     └── POST /api/config/reload    → 重新读盘 + 热重载
  │
  └── WebSocket 客户端管理
        _clients: list[WebSocket]
```

> ℹ️ 与旧版本不同，当前 WebApp **不再托管前端 SPA 静态文件**（无 `StaticFiles` / `/assets` / `index.html` fallback）。前端为独立部署，仅通过 WS + REST 与 WebApp 交互。

### 9.2 WebSocket 消息处理

#### 入站消息（User → Agent，U2A）

前端发送 `NodeMessage.to_dict()` 的 JSON（`web/app.py:66`）：

```
WebSocket /ws 收到消息
  │
  ├── 1. json.loads → NodeMessage.from_dict(message_data)
  │     （非 NodeMessage JSON 则 warning 后 continue）
  │
  ├── 2. 提取 session_id、content；记录 _active_session_id
  │
  ├── 3. ★ U2A Phase 1 回传 ★（条件：tracer && private_key_path && agent_did）
  │     async with locked_session(session_id):
  │         session.set_trace_metadata({recorded_hop, protocol_url})
  │     private_key = tracer.load_private_key(private_key_path)
  │     send_back_message(protocol_url, agent_did, nonce, recorded_hop, private_key)
  │     （失败仅 warning）
  │
  └── 4. 路由到 Channel
        channel_callback(sender="user", chat_id=session_id, content=content, media=[])
          → ATTPChannel._receive → nanobot MessageBus → Agent LLM
```

#### 出站消息（Agent → User，A2U）

`send_message_to_user(content, session_id)`（`web/app.py:175`）构建 A2U NodeMessage 并经 WS 下行，内部委托 `_send_message_to_user_locked`（`web/app.py:200`，在 `locked_session(session_id, create=False)` 内执行）：

```
_send_message_to_user_locked(session, content, session_id)
  │
  ├── 获取 trace metadata → 提取 protocol_url 与上一跳 sender_did（作为 user_did）
  │
  ├── tracer.append_hop(behavior_type="A2U")        # 构建 A2U RecordedHop
  │
  ├── ★ 时序规则：先回传协议节点 ★
  │     send_back_message(protocol_url, agent_did, nonce, recorded, private_key)
  │
  ├── 更新 session trace（recorded_hop + protocol_url）
  │
  └── 序列化 NodeMessage → WS 广播
        for client in _clients: client.send_text(json.dumps(node_msg.to_dict()))
        发送失败的 client 移出 _clients

  （无 trace / 无 user_did → 记 warning，返回 False，消息被丢弃）
```

> ⚠️ `record_message`（`web/app.py:266`）**首行即 `return`**，是已被 `send_message_to_user` 替代的死代码；当前仍作为 `web_callback` 注入 `ATTPClient` / `ATTPServer`，但调用它是空操作。因此 A2A 入/出站的 UI 通知路径目前不生效，UI 数据仅经由上面的 A2U WS 广播获得。

### 9.3 REST API

#### 节点状态 API（`node_status.py`）

```
GET /api/nodes → {"agents": [...]}
```

字段：`did` / `name` / `description` / `ad_url` / `capabilities` / `online`（DID 是否在 `remote_agents` 中）。数据来自 `ATTPClient.registered_agents`。

#### 配置管理 API（`config_setting.py`）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/config?refresh=true` | GET | 读取配置（`refresh=true` 先 `config_manager.load()`）；未启用返回 `{error:"ATTP is not enabled"}` |
| `/api/config` | PUT | 部分更新（`config_manager.update(partial)`，写盘，**不热重载**） |
| `/api/config/reload` | POST | `old_cfg=deepcopy` → `load()` → `reload_callback(old,new)` |

#### 运行状态 API

```
GET /api/status → {"status": "active" | "offline", "ws_clients": <int>}
```

### 9.4 生命周期

```python
async def start(attp_client, attp_config_manager, reload_callback=None,
                session_manager=None, agent_did="", tracer=None, private_key_path="") -> None
# mount_api → uvicorn.Config(沉默日志) → asyncio.create_task(serve) → 设 running

async def stop()    # running=False → should_exit → cancel serve_task → 关闭所有 WS → _clients.clear()
```

WebApp **没有 `reload` 方法**：`ATTPChannel.reload` 对 WebApp host/port 变化仅直接赋值 `self._web_app.host/port` 并记 warning（需手动重启）。

---

## 10. 日志系统（Logging）

### 10.1 组件化日志（`logging.py:18`）

`_ComponentLogger` 为每个 ATTP 组件提供带 `[ATTP {Component}]` 前缀的日志：

```python
from attp.app.logging import get_logger
log = get_logger("Server")
log.info("started on {}:{}", "0.0.0.0", 8000)
# 输出: ... | INFO | ... - [ATTP Server] started on 0.0.0.0:8000
```

**已注册的组件名称**（散见于各模块 `get_logger(...)` 调用）：

| 组件 | Logger 名称 | 前缀 |
|------|------------|------|
| ATTPChannel | `"Channel"` | `[ATTP Channel]` |
| ATTPClient | `"Client"` | `[ATTP Client]` |
| ATTPServer | `"Server"` | `[ATTP Server]` |
| MCPToolBridge | `"ToolBridge"` | `[ATTP ToolBridge]` |
| HeartbeatManager | `"Heartbeat"` | `[ATTP Heartbeat]` |
| AgentHealthChecker | `"Heartbeat.Agent"` | `[ATTP Heartbeat.Agent]` |
| ToolNodeHealthChecker | `"Heartbeat.Tool"` | `[ATTP Heartbeat.Tool]` |
| WebApp | `"WebUI"` | `[ATTP WebUI]` |
| ConfigManager / config API | `"Config"` | `[ATTP Config]` |

底层使用 **loguru**，通过 `opt(depth=1)` 确保调用栈指向真实调用方而非本类。`set_log_level(level)` 设置全局等级（`nanobot.py` 导入期默认调到 `"DEBUG"`）。

### 10.2 Uvicorn 静默配置（`logging.py:130`）

```python
UVICORN_SILENT_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "uvicorn":        {"handlers": ["null"], "level": "INFO", "propagate": False},
        "uvicorn.error":  {"handlers": ["null"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["null"], "level": "INFO", "propagate": False},
    },
    "handlers": {"null": {"class": "logging.NullHandler"}},
}
```

所有 Agent 端 uvicorn 组件（ATTPServer、MCPToolBridge、WebApp）启动时传入此配置，彻底静默 uvicorn 自身日志。

### 10.3 第三方噪音过滤（`logging.py:149`）

`_NoiseFilter`（标准 `logging.Filter`，非 loguru）过滤已知的无害第三方日志：

| Logger 名称 | 过滤的消息子串 |
|-------------|--------------|
| `mcp.client.sse` | `"Error in sse_reader"` |
| `anp.anp_crawler.anp_client` | `"HTTP request failed"` |

> 桥接 uvicorn 日志到 loguru 的 `InterceptHandler` 在源码中存在但**被整段注释禁用**（`logging.py:91-121`），默认不启用。

---

## 11. openclaw 原生渠道插件（TypeScript）

ATTP 自 v0.2.2 起随附第二个官方渠道适配器：**openclaw 渠道插件**。它不依赖 Python 子进程，而是作为 openclaw 的原生插件，在 openclaw 进程内拉起 ATTP 的三端口服务。代码位于 `typescript/attp/channels/openclaw/`。

### 11.1 定位与设计

openclaw 插件刻意复用 `typescript/attp/app/` 下 **host-agnostic** 的进程内服务（`attp-server.ts` / `mcp-node.ts` / `client.ts` / `server.ts` / `web.ts`），这些模块**不 import 任何 channel 代码**，可被 openclaw / nanobot / 独立进程三种形态共用。渠道层（`channels/openclaw/src/`）只负责：

- 读 openclaw 配置 + ATTP agent 配置；
- 在 `startAccount` 拉起三端口、装载身份、预发现 peer；
- 把入站消息驱动成 openclaw agent turn；
- 把 openclaw agent 的回复按目标前缀分流到 A2U / A2A 出站链路。

### 11.2 清单与包

#### `package.json`

```jsonc
{
  "name": "@attp/openclaw-channel",
  "version": "0.1.0",
  "description": "ATTP agent-mesh channel plugin for openclaw (native in-process, three-port)",
  "openclaw": {
    "extensions": ["./dist/index.js"],
    "channel": { "id": "attp", "label": "ATTP", "order": 50 },
    "compat":   { "pluginApi": ">=2026.7.2" },
    "install":  { "minHostVersion": ">=2026.7.2" }
  },
  "peerDependencies":       { "openclaw": ">=2026.7.2" },
  "peerDependenciesMeta":   { "openclaw": { "optional": true } }
}
```

#### `openclaw.plugin.json`

```jsonc
{
  "id": "attp", "name": "ATTP", "version": "0.1.0",
  "channels": ["attp"],
  "channelConfigs": {
    "attp": {
      "schema": {
        "type": "object",
        "properties": {
          "enabled":     { "type": "boolean", "default": true },
          "config_path": { "type": "string", "description": "ATTP agent 配置路径" }
        }
      }
    }
  }
}
```

渠道配置精简为 `{ enabled, config_path }`（与 nanobot 同形）；ATTP 身份 / DID / 端口都由 `config_path` 指向的 ATTP agent 配置文件提供。

### 11.3 三端口拓扑

openclaw 插件在进程内拉起 **三个独立端口**（经两个 host-agnostic 服务句柄）：

| 端口（默认） | 服务 | 来源 | 承载内容 |
|--------------|------|------|----------|
| **19000** | Agent Server | `startAttpServer({agentPort})` | DID-wba A2A 接收（`POST /receive`）+ `/ad.json` + `/openrpc.json` 发现 |
| **19001** | WebUI | `startAttpServer({webPort})` | 浏览器 WS（NodeMessage，ATTP user 端）+ `GET /api/status` + `GET /api/nodes`（+ 可选静态根 `uiDir`） |
| **19002** | MCP node | `startMcpNode(rt, toolPort)` | MCP `send_message` 工具（SSE：`GET /sse` 建流 + `POST /message` 投递） |

默认端口定义在 `app/config.ts`：`DEFAULT_AGENT_SERVER_PORT=19000` / `DEFAULT_WEB_APP_PORT=19001` / `DEFAULT_TOOL_PORT=19002`。相对 nanobot 的 8000/8001/8002 整体 +11000，角色对应关系一致（最低端口=A2A 服务、中端口=WebUI、最高端口=MCP），故**两者可同机共存**。

> `startAttpServer` 返回的 `AttpServerHandle` 同时暴露 `webPort`、`agentPort` 与共享的 `hub: WsHub`（也写入 `runtime.hub`，供 A2U 出站 `hub.broadcast` 用）。`publicAgentUrl`（如 `https://host:19000`）用于 ad.json / openrpc.json 中暴露给远端 peer 回调的 URL；缺省回退 `http://127.0.0.1:${agentServerPort}`（仅本地可达）。

### 11.4 插件入口与生命周期

#### `index.ts`

```typescript
export default defineChannelPluginEntry({
  id: "attp", name: "ATTP",
  description: "ATTP agent-mesh channel (WebUI + cross-framework A2A + tools), native three-port in-process",
  plugin: attpPlugin,
  setRuntime(rt) { runtime.channelRuntime = rt; },   // 注册期注入 openclaw channel 运行时
  registerFull(api) { runtime.cfg = api.config; },    // 仅记下配置根；不在 gateway 上注册路由/工具
});
```

#### `src/channel.ts` — `attpPlugin`

`attpPlugin = { ...chatPlugin, gateway: { startAccount, stopAccount } }`，其中 `chatPlugin` 由 `createChatChannelPlugin` 构造（`base` 提供账户发现 / `inspectAccount`，`outbound.attachedResults.sendText` 动态 import `deliverOutbound`）。

**`startAccount(ctx)`** 流程（`channel.ts:98`）：

```
1. readChannelConfig(ctx.cfg) → { enabled, agent:AgentConfig }
   若 enabled !== true（即显式 false）→ log + return
2. 装载身份写入 runtime：
     runtime.privateKey   = loadPrivateKeyPem(readFileSyncUtf8(didKeyPath))
     runtime.didDocument  = JSON.parse(readFileSyncUtf8(didDocPath))
     runtime.tracer       = new AgentTracer()
     runtime.abortSignal  = ctx.abortSignal
     runtime.sessionTraces = new Map()
3. 预发现 nodeAds（best-effort，单失败不阻断）：
     for adUrl in agent.nodeAds:
       fetch(adUrl) → ad.did ?? ad.identifier → peerRegistry.set(peerDid, adUrl)
   （目的：A2A 发送优先命中此表，避免对本地 DID 走 didToAdUrl 推导出不可达 URL）
4. startAttpServer({ webPort, agentPort, publicAgentUrl, runtime,
                     onInbound: m => dispatchAttpInbound(m, runtime) })
   → serverHandle（同时把 WsHub 写入 runtime.hub）
5. startMcpNode(runtime, toolPort) → mcpHandle
6. ctx.setStatus({ phase: "running" })
7. 阻塞至 ctx.abortSignal 触发（addEventListener("abort")）
8. abort 后 best-effort 关闭：Promise.allSettled([server.close(), mcp.close()])
```

**`stopAccount()`**：abortSignal 已在 `startAccount` 尾部驱动服务关闭，这里只清 `runtime` 引用（`hub` / `tracer` / `privateKey` / `didDocument`）。

### 11.5 配置读取（`config.ts`）

`readChannelConfig(cfg)` 是 openclaw 简洁渠道配置与 ATTP agent 配置之间的桥梁：

```typescript
const section = cfg?.channels?.attp ?? {};
const raw = JSON.parse(readFileSync(expandHome(section.config_path), "utf8"));
return { enabled: section.enabled !== false, agent: loadAgentConfig(raw) };
```

> `enabled` 默认为 `true`（仅显式写 `false` 才关闭），与 nanobot 渠道一致。

`loadAgentConfig`（`app/config.ts:91`）**不改 schema**，从 ATTP agent 配置 JSON 选取字段并上浮端口：

```
did             ← raw.did
didDocPath      ← raw.attpClient.didDocPath
didKeyPath      ← raw.attpClient.didKeyPath
nodeAds         ← raw.attpClient.nodeAds
agentName/Desc  ← raw.attpServer.name / description
protocolUrl     ← raw.protocolNode.enabled ? loadProtocolUrlFromNodeConfig(configPath) : undefined
webAppPort      ← raw.webApp.port                      (default 19001)
agentServerPort ← raw.attpServer.serverPort            (default 19000)
toolPort        ← raw.tool.port                        (default 19002)
publicAgentUrl  ← raw.attpServer.publicBaseUrl ?? `http://127.0.0.1:${agentServerPort}`
```

`protocolUrl` 解析对齐 Python `ProtocolNodeConfigFile` 的 `{web:{host,port}}`，并把 `0.0.0.0` 归一化为 `127.0.0.1`（Windows 不可达）。> Python 的 `ATTPServerConfig` 无 `publicBaseUrl`，这是 TS 为暴露外部 URL 新增的字段。

### 11.6 入站分发（`inbound.ts` — `dispatchAttpInbound`）

同时服务 U2A（浏览器 WS）与 A2A（远端 agent `POST /receive`），由 `attp-server.ts` 的 `onInbound` 回调驱动：

```typescript
dispatchAttpInbound({ session_id, sender_did, content, direction }, runtime)
```

流程：

```
1. reply 目标按方向分流：
     U2A → replyTo = `attp:${sid}`
     A2A → replyTo = sender_did（但见步骤 3：A2A 不自动反向回复）
2. resolveInboundRouteEnvelopeBuilderWithRuntime 解析路由 + 构造存储信封
   （peer={kind:"direct", id:sid}, sessionStore=cfg.session.store）
3. buildContext：把 session_id 注入 agent 可见输入
     bodyForAgent = `[attp_session_id=${sid}]\n${content}`
   （openclaw 的 sessionId 仅 provider 缓存用、不暴露给 LLM；
    而 MCP send_message 续接溯源链需显式 session_id，故注入 bodyForAgent；
    rawBody/body 保持干净）
4. cr.channel.inbound.run 驱动 agent turn：
     delivery.deliver(payload) → extractReplyText(payload)
       ├── direction==="A2A"：仅 log agent 文本输出，**不自动回送**
       │     （设计：发送方发完即无后续；接收者是否回复由提示词决定，
       │      需要回复时 agent 自行调用 MCP send_message 工具发起一条新 A2A）
       └── direction==="U2A"：deliverOutbound(replyTo=`attp:${sid}`, text)  # 走 A2U
```

### 11.7 出站路由（`outbound.ts` — `deliverOutbound`）

`deliverOutbound(to, text)` 按目标前缀分流，全程 in-process：

```
deliverOutbound(to, text)
  │
  ├── to 以 "attp:" 开头 → A2U（Agent → User）
  │     ├── sid = to.slice("attp:".length)
  │     ├── 取 runtime.sessionTraces.get(sid) 续链
  │     │     protocolUrl = trace?.protocolUrl ?? agentConfig.protocolUrl ?? ""
  │     │     userDid     = trace?.recordedHop.sender_did ?? "did:user"
  │     ├── tracer.appendHop(prevMetadata, text, agentDid, userDid, privateKey, "A2U")
  │     ├── 构造 NodeMessage（randomUUID 去 "-" 为 nonce）
  │     ├── best-effort Phase-1 回传：sendBackMessage → protocolUrl（失败只 warn）
  │     ├── 更新 sessionTraces.set(sid, {protocolUrl, recordedHop: newHop.toDict()})
  │     └── hub.broadcast(sid, nodeMessageFrame(nodeMsg))   # 推给订阅该 session 的浏览器 WS
  │
  ├── to 以 "did:" 开头 → A2A（Agent → Agent，现场 rediscover）
  │     ├── adUrl = runtime.peerRegistry.get(to) || didToAdUrl(to)
  │     ├── discoverAgent(adUrl) → peer.rpcUrl
  │     └── sendMessage({ rpcUrl, didDocument, privateKey, senderDid, targetDid, content, messageType:"agent_reply" })
  │
  └── 其它前缀 → 占位返回 { messageId: to }（不抛）
```

`didToAdUrl(did)`（`outbound.ts:161`）按 `did:wba/web` best-effort 推导 ad.json URL（剥离末尾 `e1_`/`k1_` key id 段），与 `app/mcp-node.ts` 中同实现刻意同步、避免跨层反向依赖。

> MCP `send_message` 工具（`app/mcp-node.ts`）也走相同的 `peerRegistry` + `didToAdUrl` + `executeSendMessage` 链路发起 A2A，故 openclaw agent 的主动 A2A 既可经 `deliverOutbound`（回复触发）、也可经 MCP 工具（LLM 主动调用）。

### 11.8 共享运行时（`runtime.ts` — `AttpRuntime`）

进程内单账户共享状态，分两阶段填充：

```typescript
export interface AttpRuntime {
  channelRuntime?: any;            // register 期由 setRuntime 注入
  cfg?: any;                       // registerFull 期记下配置根
  agentConfig?: AgentConfig;       // startAccount 期由 readChannelConfig 填入
  hub?: WsHub;                     // startAttpServer 启动时注入
  tracer?: AgentTracer;            // startAccount 期 new AgentTracer()
  privateKey?: LoadedKey;          // startAccount 期装载
  didDocument?: any;               // startAccount 期装载
  abortSignal?: AbortSignal;       // startAccount 期注入
  sessionTraces?: Map<string, SessionTrace>;  // 每 session 溯源轨迹（入站 set、出站续链）
  peerRegistry?: Map<string, string>;         // nodeAds 预发现：DID → adUrl
}
export const runtime: AttpRuntime = {};
```

### 11.9 安装与示例配置

**安装（link 本地源码）**：

```bash
openclaw plugins install --link ./typescript/attp/channels/openclaw
```

**示例配置 1**：`examples/.attp/agent/openclaw/config.json`（ATTP agent 配置，schema 与 nanobot 相同）：

```jsonc
{
  "did": "did:wba:attp-diting.cn:test:agent:openclaw:e1_...",
  "attpClient": { "didDocPath": "~/.attp/agent/openclaw/did/did.json",
                  "didKeyPath": "~/.attp/agent/openclaw/did/key-1_private.pem",
                  "nodeAds": [] },
  "attpServer": { "name": "diting-agent-openclaw", "description": "谛听演示智能体节点 (openclaw)",
                  "serverHost": "0.0.0.0", "serverPort": 19000, /* ... */ },
  "webApp":   { "host": "0.0.0.0", "port": 19001 },
  "tool":     { "host": "127.0.0.1", "port": 19002,
                "toolNodeAds": ["http://tool:9999/attp/ad.json"] },
  "heartbeat": { "interval": 30, "timeout": 90, "maxFail": 3 },
  "protocolNode": { "enabled": false, "configPath": "~/.attp/protocol_node/config.json" }
}
```

**示例配置 2**：`examples/.openclaw/config.json`（openclaw 配置片段，合并进 `~/.openclaw/openclaw.json`）：

```jsonc
{
  "plugins":  { "entries": { "attp": { "enabled": true } },
                "load":   { "paths": ["${ATTP_ROOT}/typescript/attp/channels/openclaw"] } },
  "channels": { "attp": { "enabled": true,
                          "config_path": "~/.attp/agent/openclaw/config.json" } },
  "bindings": [{ "agentId": "main", "match": { "channel": "attp" } }],
  "mcp":      { "servers": { "attp-tools": { "url": "http://127.0.0.1:19002/sse",
                                              "transport": "sse" } } },
  "gateway":  { "port": 18789, "bind": "loopback" }
}
```

agent 通过 `mcp.servers.attp-tools` 接入 ATTP MCP 工具节点（`send_message` over SSE）。

### 11.10 TS 核心库：与 Python 跨语言序列化兼容

`typescript/attp/core/` 是 Python `attp/core/` 的跨语言移植。`core/message/event.ts` 头部明确：

> 从 `python/attp/core/message/event.py` 翻译而来。序列化格式（`to_dict`/`from_dict`）与 Python 端**完全一致**，确保跨语言通信时的数据兼容性。

约定：**内部字段 camelCase，上线（wire）字段 snake_case**。因此 Python 的 `RecordedHop` / `NodeMessage` / `BackMessage` 与 TS 的同名类可互相解析；`AgentTracer.appendHop`、`send_back_message` 在两端语义对齐（见 `outbound.ts` 中"对齐 Python:216-223"等注释）。

---

## 12. Agent 端核心数据流

### 12.1 U2A（用户 → Agent）完整流程

**Python（WebApp）**：

```
  User (Browser)             WebApp              Protocol Node          Agent (nanobot)
       │                       │                      │                      │
       │  NodeMessage(U2A)     │                      │                      │
       ├──── WS ──────────────→│                      │                      │
       │                       │                      │                      │
       │                       │  BackMessage Phase 1 │                      │
       │                       │  (Agent 签名 identity,│                      │
       │                       │   前端已构建 hop)     │                      │
       │                       ├─────────────────────→│                      │
       │                       │                Branch A: 暂存               │
       │                       │                      │                      │
       │                       │  channel_callback    │                      │
       │                       ├──────────────────────┼─────────────────────→│
       │                       │                      │              LLM 处理 │
```

1. 前端构建 `NodeMessage`（含 `RecordedHop`，type=U2A）
2. WS 发给 WebApp；WebApp 存 session trace
3. WebApp 执行 Phase 1 回传：`send_back_message()` → Protocol Node
4. `channel_callback` → `ATTPChannel._receive` → nanobot MessageBus → Agent LLM

**TypeScript（openclaw）**：浏览器 WS 连 WebUI 端口（19001）→ `attp-server.ts` 解析 NodeMessage、存 `sessionTraces`、best-effort Phase-1 回传 → `onInbound({direction:"U2A"})` → `dispatchAttpInbound` 驱动 openclaw agent turn（§11.6）。

### 12.2 A2A（Agent → Agent）完整流程

**发送方（Agent A）** — `ATTPClient.send_to_agent`：

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
       │                                         │  6. attp_channel_callback
       │                                         │  → nanobot 处理        │
```

1. 从 session 取 trace metadata
2. `AgentTracer.append_hop(behavior_type="A2A")` — 递增 hop_count
3. 构建 `NodeMessage`
4. **先回传**：`send_back_message()` → Protocol Node（Phase 2，A 报告）
5. **再发送**：`remote.receive_message(...)` → Agent B

**接收方（Agent B）** — `ATTPServer.receive_message`：

1. 解析 `NodeMessage`
2. 存 trace 到 session
3. **回传**：`send_back_message()` → Protocol Node（Phase 1，B 确认）
4. `attp_channel_callback` → `ATTPChannel._receive` → nanobot 处理

**TypeScript（openclaw）**：远端 peer 经 DID-wba 签名 POST 到 Agent Server 端口（19000）的 `/receive` → `attp-server.ts` 验签、best-effort Phase-1 回传 → `onInbound({direction:"A2A"})` → `dispatchAttpInbound`（A2A 不自动反向回复，agent 须显式调 MCP `send_message` 发起新 A2A，§11.6/§11.7）。

### 12.3 A2T（Agent → Tool）完整流程

参见 [§7.5 工具调用完整回传时序](#75-attp-工具调用--完整回传时序)。

关键特点：
- 工具调用在 `locked_session` 中执行，保护 `hop_count` 的 read-modify-write 原子性
- A2T 阶段 Agent 先回传 Phase 2（报告），再发送 NodeMessage 给 Tool Node
- T2A 阶段 Agent 收到返回后回传 Phase 1（确认），并用 T2A 的 `recorded_hop` 更新 session trace
- 若无 `protocol_url` / 私钥，直接返回原始响应体，不做 T2A 续链

### 12.4 A2U（Agent → User）完整流程

**Python（WebApp）**：

```
  Agent (nanobot)             WebApp                    Protocol Node        User (Browser)
       │                        │                            │                    │
       │  OutboundMessage       │                            │                    │
       ├───────────────────────→│                            │                    │
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

1. nanobot 经 MessageBus 发 `OutboundMessage`
2. `ATTPChannel.send()` 过滤空内容 → `WebApp.send_message_to_user()`
3. WebApp 在 `locked_session` 内：取 trace → 提取 `user_did` → `append_hop("A2U")` → **先回传** → 更新 session trace → 构建 `NodeMessage` → WS 广播
4. 前端收到 NodeMessage 后执行 Phase 2 回传

**TypeScript（openclaw）**：openclaw agent 的 U2A 回复 → `delivery.deliver` → `deliverOutbound("attp:<sid>", text)`（§11.7）：appendHop("A2U") → best-effort Phase-1 回传 → `hub.broadcast(sid, nodeMessageFrame(nodeMsg))` 推给订阅该 session 的浏览器 WS。

---

## 13. 设计模式与总结

### 13.1 设计模式

| 模式 | 应用场景 | 说明 |
|------|---------|------|
| **Facade 门面** | `AgentTracer` | 组合 KeyStore + ChainManager，提供统一溯源接口（Agent 侧轻量、无 DB） |
| **Strategy 策略** | `HealthChecker` 协议 + `HeartbeatManager` | 调度逻辑与检查逻辑分离，阈值由各 Checker 自持 |
| **Observer 观察者** | `channel_callback` / `onInbound` | 事件驱动的消息路由（`web_callback` 当前为空操作） |
| **Bridge 桥接** | `MCPToolBridge` | 桥接 MCP 协议与 ATTP 协议 |
| **Template Method** | `start()/stop()/reload()` 生命周期 | 所有组件遵循统一生命周期模板 |
| **Factory Method** | `ATTPServer._create_agent()` | 动态创建 OpenANP Agent 类 |
| **Repository** | `ConfigManager` | 配置的持久化读写 |
| **Adapter** | `ATTPChannel` / `attpPlugin` | 将 app 组件适配到 nanobot / openclaw 框架 |
| **Proxy** | `PassthroughArgModel` | 透传远程工具参数，绕过函数签名内省 |
| **Lock Striping** | `locked_session()` | Per-session 异步锁，保护并发 read-modify-write |
| **Host-agnostic 服务** | TS `attp-server.ts` / `mcp-node.ts` | 同一份服务供 openclaw / nanobot / 独立进程共用，不 import channel 代码 |

### 13.2 统一生命周期管理

所有 Python 组件遵循一致的生命周期模式：

```python
class Component:
    async def start(self) -> None            # 启动（创建后台 Task / 绑定端口）
    async def stop(self) -> None             # 停止（cancel Task / should_exit）
    async def reload(self, config) -> None   # 热重载（stop → 更新参数 → start）
```

| 组件 | start 语义 | stop 语义 | reload 语义 |
|------|----------|---------|------------|
| ATTPClient | Agent 发现 | 清 running | 重建 auth/registry/三缓存 |
| ATTPServer | uvicorn 启动 | should_exit + 等 5s/取消 | 重建 Agent/app + 等端口 |
| MCPToolBridge | MCP SSE 启动 | should_exit + cancel | 更新 host/port |
| HeartbeatManager | 后台 _loop Task | cancel Task | 更新 interval/timeout/max_fail |
| WebApp | FastAPI 启动 | should_exit + cancel + 关闭 WS | **无**（仅更新属性，需手动重启） |

### 13.3 时序规则

ATTP Agent 端严格遵守**先回传协议节点，再发送消息**的时序规则：

| 场景 | 回传阶段 | 回传者 |
|------|---------|-------|
| A2A 发送 | Phase 2（发送方报告） | 发送方 Agent（`ATTPClient`） |
| A2A 接收 | Phase 1（接收方确认） | 接收方 Agent（`ATTPServer`） |
| U2A | Phase 1（接收方确认） | Agent（WebApp / TS `attp-server.ts`） |
| A2U | Phase 2（发送方报告） | Agent（WebApp / TS `outbound.ts`） |
| A2T | Phase 2（发送方报告） | Agent（`MCPToolBridge`） |
| T2A | Phase 1（接收方确认） | Agent（`MCPToolBridge`） |

TS 端（openclaw）回传统一为 best-effort：失败只 warn，不阻断入站分发或出站广播（见 `attp-server.ts` 的 `backPropagate` 与 `outbound.ts` 的 A2U 回传）。

### 13.4 架构特点总结

| 特点 | 实现方式 |
|------|---------|
| **框架无关** | `app/` 组件无框架依赖，通过 `channels/` 适配不同框架 |
| **双渠道等价** | nanobot（Python）与 openclaw（TS）两套适配，拓扑相同、端口可共存（+11000 偏移） |
| **跨语言兼容** | TS 核心是 Python 核心的移植，`NodeMessage` 序列化字节兼容 |
| **可插拔扩展** | Channel 插件 + HealthChecker 策略 + 动态 MCP 工具注册 |
| **差量热重载** | 基于 `changed_fields()` 检测变更，仅重载受影响组件（Python 侧） |
| **并发安全** | `locked_session()` 保护 session 的 read-modify-write 原子性 |
| **优雅降级** | 无 trace 时记 warning 并降级处理，不中断主流程；TS 回传 best-effort |
| **容错恢复** | 心跳 evict/retry 机制自动恢复 Agent 连接与工具节点 |
