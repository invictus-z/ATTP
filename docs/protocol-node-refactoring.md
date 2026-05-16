# 协议节点（Protocol Node）架构重构设计

## 1. 背景与动机

ATTP 原有架构中，行为储存、验证、溯源、污点审计等底层协议逻辑以及全部 API 服务均嵌入在 Agent Channel 内部，由 `ATTPServer`（ANP 协议）和 `WebApp`（FastAPI）混合承载。系统默认首节点（Origin Node）为可信任节点，`Origin_DID` 直接取值为发起者自身的 DID。

**痛点**：在前端远程操控等场景下，首节点往往不可信。原有的信任模型——"谁发起了会话就信任谁"——无法满足多方协作的安全审计需求。

**重构目标**：将协议底层逻辑剥离为独立的「协议节点（Protocol Node）」，以双端口架构运行。信任锚点从"发起者 DID"转变为"协议节点地址"。

---

## 2. 核心设计决策

### 2.1 `Origin_DID` → `Protocol_Node_Address`

| 维度 | 旧设计 | 新设计 |
|------|--------|--------|
| 字段名 | `Origin_DID` | `Protocol_Node_Address` |
| 语义 | 标识"谁发起的会话" | 标识"哪个协议节点负责审计该会话" |
| 取值示例 | `did:wba:home.local:agent-a` | `http://192.168.1.100:9000` |
| 注入时机 | `append_hop()` 在 `hop_count==0` 时自动设置 | 前端建立 Session 时动态传入，后端持久化到 Session metadata |
| 用于 | record 回传目标、哈希计算、验证 | record 回传目标、哈希计算、验证 |

全局替换范围：metadata 传播（`chain.py`、`session.py`）、哈希计算（`hashing.py`）、数据库存储（`sqlite_store.py`）、验证逻辑（`chain.py`）、门面接口（`tracer.py`）、客户端路由（`client.py`）。

### 2.2 双端口架构

```
┌──────────────────────────────────────────────────────────┐
│                     Protocol Node                        │
│                                                          │
│  ┌─────────────────────┐    ┌─────────────────────────┐  │
│  │   Port 1 (Data)     │    │   Port 2 (API)          │  │
│  │   default :9000     │    │   default :9001         │  │
│  │                     │    │                         │  │
│  │   POST /record      │    │   GET /api/behavior/*   │  │
│  │   ├─ BehaviorEntry  │    │   GET /api/analysis/*   │  │
│  │   ├─ 回传验证       │    │   POST /api/analysis/   │  │
│  │   └─ 触发分析       │    │        trigger/*        │  │
│  │                     │    │   GET /api/analysis/    │  │
│  │                     │    │        intent/*         │  │
│  └─────────────────────┘    └─────────────────────────┘  │
│            │                           │                  │
│            ▼                           ▼                  │
│       SqliteStore              AnalysisOrchestrator       │
│       SessionManager           (条件启用)                 │
└──────────────────────────────────────────────────────────┘
```

- **端口一（Data Port）**：普通 HTTP POST，不使用 ANP 协议。协议节点不是 Agent，不持有 DID 文档。
- **端口二（API Port）**：仅承载协议相关 API（trace/analysis）。通用 API（config、node_status）保留在 WebApp。

### 2.3 信任模型变更

```
旧：Agent A（Origin）← 信任 ← Agent B ← 信任 ← Agent C
新：Protocol Node ← 信任锚 ← Agent A ← Agent B ← Agent C
```

前端在建立 Session 时动态指定 `Protocol_Node_Address`，所有中间节点的 record 副本统一回传到该地址，由协议节点集中验证和审计。

---

## 3. 模块职责划分

### 3.1 迁移到协议节点的逻辑

| 来源 | 目标 | 说明 |
|------|------|------|
| `server.py` record 处理分支 (L224-275) | `data_port.py` `POST /record` | BehaviorEntry 储存、回传验证 |
| `server.py` `_verify_back_record` | `data_port.py` 内部 | PrevHop 一致性校验 |
| `web/api/trace.py` 全部路由 | `protocol_node/api/trace.py` | 行为溯源、分析报告、污点审计 API |
| `analysis/orchestrator.py` `on_record_received` | 由 `data_port.py` 触发 | record 到达时触发分析 |

### 3.2 保留在 Agent Channel 的逻辑

| 模块 | 说明 |
|------|------|
| `server.py` agent_request 处理 | 接收 Agent 间消息，转发到 Channel |
| `client.py` 消息发送 | 发送 agent_request，record 回传改为 HTTP POST |
| `web/app.py` WebSocket + 通用 API | `/ws`、`/api/status`、`/api/config`、`/api/nodes` |
| `web/app.py` SPA 静态文件 | 前端页面服务 |
| `heartbeat/heartbeat.py` | 心跳管理 |
| `tools/send_message_tool.py` | MCP 工具 |
| `web/app.py` 分析钩子 | `_on_field_U2A_recorded`、`_on_session_end`（由 orchestrator 注入） |

### 3.3 共享核心（`core/`）

不移动，通过依赖注入共享：`tracer.py`、`authentication/`、`provenance/`、`sessions/`、`storage/`、`analysis/`。

---

## 4. 数据流变更

### 4.1 Record 回传流

```
旧：
  Client.send_to_agent()
    → append_hop() 设置 Origin_DID = self
    → remote_agents.get(Origin_DID)
    → origin_remote.receive_message(type="record")  # ANP 协议

新：
  Client.send_to_agent()
    → append_hop() 传播 Protocol_Node_Address（从 session metadata）
    → aiohttp.post(Protocol_Node_Address + "/record")  # HTTP POST
    → DataPort POST /record 处理
```

### 4.2 Session 建立流

```
旧：
  Client 首条消息 → append_hop(hop_count=0) → metadata["Origin_DID"] = node_did

新：
  前端 WebSocket 发送 {"type":"chat", "Protocol_Node_Address":"http://..."}
  → WebApp 解析并写入 Session metadata
  → Client 首条消息 → append_hop() 从 metadata 传播 Protocol_Node_Address
```

### 4.3 API 请求路由

| 端点 | 旧端口 | 新端口 |
|------|--------|--------|
| `/api/behavior/*`、`/api/analysis/*` | WebApp:8001 | ProtocolNode:9001 |
| `/api/config`、`/api/nodes`、`/api/status` | WebApp:8001 | WebApp:8001 |
| `/ws` | WebApp:8001 | WebApp:8001 |

---

## 5. 三种启动模式

### 5.1 独立部署（Standalone）

```bash
attp protocol-node start --config ~/.attp/agent/nanobot/config.json [--data-port 9000] [--api-port 9001]
```

CLI 入口定义在 `attp.protocol_node.cli:main`，通过 `pyproject.toml` 的 `[project.scripts]` 注册。独立创建 `MessageTracer`、`SessionManager`、`AnalysisOrchestrator`（如果配置启用）。

### 5.2 混合部署（Hybrid）

在 `ATTPChannel.start()` 中，读取 `protocolNode.enabled` 配置：

```python
pn_cfg = self._attp_cfg.protocol_node
if pn_cfg.enabled:
    self._protocol_node = ProtocolNode(...)
    # 构建并注入 orchestrator（仅在 ProtocolNode 启用时）
    self._analysis_orchestrator = self._build_analysis_orchestrator()
    if self._analysis_orchestrator:
        self._protocol_node.set_orchestrator(self._analysis_orchestrator)
        self._web_app._on_field_U2A_recorded = ...
        self._web_app._on_session_end = ...
    # 注入 data port URL 到 Client
    self._attp_client.set_protocol_node_url(data_url)
```

Orchestrator 依赖 DataPort 的 `/record` 端点触发 `on_record_received`，因此仅在 ProtocolNode 启用时才构建。

### 5.3 完全禁用（Disabled）

`protocolNode.enabled == false` 且未执行 CLI 命令 → 不创建任何 ProtocolNode 或 AnalysisOrchestrator 资源。

---

## 6. 配置结构

新增 `ProtocolNodeConfig`：

```python
class ProtocolNodeConfig(ATTPBase):
    enabled: bool = False
    data_port_host: str = "127.0.0.1"
    data_port_port: int = 9000    # alias: dataPortPort
    api_port_host: str = "127.0.0.1"
    api_port_port: int = 9001     # alias: apiPortPort
```

配置文件示例：

```json
{
    "protocolNode": {
        "enabled": true,
        "dataPortHost": "127.0.0.1",
        "dataPortPort": 9000,
        "apiPortHost": "127.0.0.1",
        "apiPortPort": 9001
    }
}
```

---

## 7. 文件变更清单

### 新增文件（7个）

| 文件 | 职责 |
|------|------|
| `protocol_node/__init__.py` | 导出 ProtocolNode |
| `protocol_node/node.py` | 主类：双端口生命周期管理 |
| `protocol_node/data_port.py` | 端口一：POST /record |
| `protocol_node/api_port.py` | 端口二：trace/analysis API |
| `protocol_node/api/__init__.py` | 空 |
| `protocol_node/api/trace.py` | 迁移的溯源/分析路由 |
| `protocol_node/cli.py` | CLI 入口 |

### 修改文件（10个）

| 文件 | 变更 |
|------|------|
| `app/config/config.py` | 新增 `ProtocolNodeConfig` |
| `app/client.py` | record 回传改 HTTP POST；新增 `set_protocol_node_url()` |
| `app/server.py` | 移除 record 处理分支，仅保留 agent_request |
| `app/web/app.py` | 移除 trace 路由挂载；保留分析回调钩子 |
| `channels/nanobot.py` | 混合模式条件启动；orchestrator 仅在 PN 启用时构建 |
| `core/sessions/session.py` | trace keys 替换 |
| `core/provenance/hashing.py` | 参数 `origin_did` → `protocol_node_address` |
| `core/provenance/chain.py` | 字段替换 + 验证参数重命名 |
| `core/storage/sqlite_store.py` | 列名 + 索引重命名 |
| `core/tracer.py` | 接口参数重命名 |

### 删除文件（1个）

| 文件 | 原因 |
|------|------|
| `app/web/api/trace.py` | 迁移至 `protocol_node/api/trace.py` |

### 保留原位（不迁移）

| 文件 | 原因 |
|------|------|
| `app/web/api/config_setting.py` | 配置管理，非协议功能 |
| `app/web/api/node_status.py` | 节点状态，非协议功能 |

---

## 8. 后续事项

- **SDK 适配**：`attp/sdk/` 中 `tool_node.py`、`mcp_adapter.py`、`mcp_proxy.py` 仍引用 `Origin_DID`/`origin_did`，需单独更新以适配新接口签名。
- **前端适配**：WebSocket 消息需新增 `Protocol_Node_Address` 字段；API 请求需路由到 ProtocolNode API Port（:9001）。
- **热重载**：当前 ProtocolNode 配置变更后仅打印警告，需手动重启。
