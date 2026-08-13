# ATTP 工具服务节点端（SDK Tools）代码与功能分析

> 本文档对 `python/attp/sdk/tools/` 目录下的所有模块进行全面的代码结构与功能分析，并说明其与 Agent 侧（`MCPToolBridge`）的交互契约。

## 目录

- [1. 概述](#1-概述)
- [2. 模块架构总览](#2-模块架构总览)
- [3. ToolHandler — 单工具处理器描述](#3-toolhandler--单工具处理器描述)
- [4. ToolAd — 服务描述文件构建器](#4-toolad--服务描述文件构建器)
- [5. ToolNodeMixin — 共用回传逻辑基类](#5-toolnodemixin--共用回传逻辑基类)
- [6. ATTPToolNode — 自定义工具函数节点](#6-attptoolnode--自定义工具函数节点)
- [7. MCPToATTPAdapter — FastMCP 实例适配器](#7-mcptoattpadapter--fastmcp-实例适配器)
- [8. MCPProxyToolNode — 远程 MCP 代理网关](#8-mcpproxytoolnode--远程-mcp-代理网关)
- [9. 核心数据流](#9-核心数据流)
- [10. 设计模式与总结](#10-设计模式与总结)

---

## 1. 概述

ATTP SDK Tools 模块是 ATTP 协议中**工具服务节点端**的实现，负责将各类工具服务包装为 ATTP 网络中的工具节点，使其具备溯源链签名和双轮回溯确认能力。

模块提供**三种接入策略**，覆盖不同的工具来源：

| 接入策略 | 核心类 | 适用场景 | 工具来源 |
|---------|--------|---------|---------|
| 自定义函数 | `ATTPToolNode` | 从零开发新的工具服务 | 本地 Python 异步函数 |
| 本地 MCP 适配 | `MCPToATTPAdapter` | 已有 FastMCP 实例，同进程包装 | 本地 FastMCP 对象 |
| 远程 MCP 代理 | `MCPProxyToolNode` | 远程 MCP 服务，跨网络代理 | 远程 HTTP MCP 端点 |

三种策略共享同一套回传逻辑（`ToolNodeMixin`），仅工具执行方式不同，对外暴露完全一致的 ATTP 端点。

### 信任边界说明（重要）

ATTP 保护**仅作用于 Agent ↔ Tool 这一跳**：即 Agent 侧的 `MCPToolBridge`（`python/attp/app/tools/mcp_tool_bridge.py`）与工具节点之间的通信。在当前 `dev` 分支上，该信任边界由以下机制构成，**不涉及 TLS / 传输层加密**：

- **DID 身份认证**：工具节点持有唯一 DID，回传 `BackMessage` 时对身份字段签名（`sig_identity`）；
- **内容溯源签名**：工具节点对 `RecordedHop.content_hash()` 用私钥签名（`sig_content`），保证工具产物可追溯、不可抵赖；
- **四轮回传协议**：Agent 报告（#1）→ Tool 确认（#2）→ Tool 报告（#3）→ Agent 确认（#4），由协议节点校验序号与身份。

工具节点内部（如 `MCPProxyToolNode` 到远程 MCP 服务的出站调用）不在 ATTP 信任边界之内。

### 辅助类

| 类 | 文件 | 职责 |
|----|------|------|
| `ToolHandler` | `handler.py` | 单工具处理器描述（名称 + Schema + 回调） |
| `ToolAd` | `tool_ad.py` | 服务描述文件 `ad.json` 的构建器 |

### 外部依赖关系

```
sdk/tools/
  ├── attp.core.authentication.keys      → load_private_key()           加载私钥
  ├── attp.core.authentication.signatures → sign_hash()                  内容签名
  ├── attp.core.message.event            → NodeMessage, RecordedHop      消息结构
  ├── attp.core.message.back_sender      → send_back_message()           回传协议节点
  │                                        BackPropagationError          回传失败异常
  ├── fastapi / uvicorn                  → HTTP 服务框架
  ├── mcp.server.fastmcp                 → FastMCP（MCPToATTPAdapter）
  └── aiohttp                            → 异步 HTTP 客户端（MCPProxyToolNode）
```

---

## 2. 模块架构总览

### 2.1 目录结构

```
sdk/tools/
├── __init__.py          # 模块声明，导出 6 个核心类
├── mixin.py             # ToolNodeMixin — 共用回传逻辑 Mixin 基类
├── tool_node.py         # ATTPToolNode — 自定义工具函数 → ATTP 节点
├── mcp_adapter.py       # MCPToATTPAdapter — 已有 FastMCP → ATTP 节点
├── mcp_proxy.py         # MCPProxyToolNode — 远程 MCP → ATTP 代理网关
├── handler.py           # ToolHandler — 单工具处理器描述
└── tool_ad.py           # ToolAd — ad.json 服务描述构建器
```

`__init__.py` 导出的 6 个核心类：`ToolNodeMixin`、`ATTPToolNode`、`MCPToATTPAdapter`、`MCPProxyToolNode`、`ToolHandler`、`ToolAd`。

### 2.2 类继承关系

```
              ToolNodeMixin (ABC, Mixin)
              ┌────────────────────────┐
              │ _execute_tool() [抽象]  │
              │ _build_ad()     [抽象]  │
              │ _handle_tool_request() │
              │ _setup_routes()         │
              │ start() / stop()        │
              └──────┬─────────────────┘
                     │
         ┌───────────┼───────────────┐
         │           │               │
         ▼           ▼               ▼
  ATTPToolNode  MCPToATTPAdapter  MCPProxyToolNode
  ┌──────────┐  ┌──────────────┐  ┌───────────────┐
  │ 装饰器注册 │  │ FastMCP      │  │ 远程服务发现   │
  │ _handlers │  │ call_tool()  │  │ MCP JSON-RPC  │
  └──────────┘  └──────────────┘  └───────────────┘
```

### 2.3 模块依赖关系图

```
ATTPToolNode ─────┬──→ ToolNodeMixin
                  ├──→ ToolHandler (工具注册)
                  └──→ ToolAd (ad.json 构建)

MCPToATTPAdapter ─┬──→ ToolNodeMixin
                  └──→ ToolAd

MCPProxyToolNode ─┬──→ ToolNodeMixin
                  ├──→ ToolAd
                  └──→ aiohttp (远程 MCP 通信)

ToolNodeMixin ────┬──→ NodeMessage / RecordedHop (消息解析)
                  ├──→ load_private_key() (密钥加载)
                  ├──→ sign_hash() (签名)
                  ├──→ send_back_message() (回传协议节点，POST {protocol_url}/record)
                  └──→ FastAPI + uvicorn (HTTP 服务)
```

---

## 3. ToolHandler — 单工具处理器描述

> 文件：`handler.py`（约 52 行）

`ToolHandler` 是单个工具的处理器抽象，将工具的**元信息**（名称、描述、输入 Schema）与**执行逻辑**（异步回调函数）封装在一起。

### 3.1 类定义

```python
class ToolHandler:
    def __init__(
        self,
        name: str,                                    # 工具名称（节点内唯一标识）
        description: str,                             # 工具描述
        input_schema: dict[str, Any],                 # JSON Schema 输入定义
        handler: Callable[..., Awaitable[Any]],       # 异步执行函数
    )
```

### 3.2 核心方法

| 方法 | 返回类型 | 说明 |
|------|---------|------|
| `to_mcp_tool_dict()` | `dict[str, Any]` | 序列化为 MCP tool 描述格式（写入 ad.json） |
| `__call__(**kwargs)` | `Any` | 代理调用 `self.handler(**kwargs)` |

### 3.3 MCP Tool 描述格式

`to_mcp_tool_dict()` 输出符合 MCP 工具描述规范的字典：

```json
{
  "name": "search",
  "description": "搜索知识库",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "搜索关键词"},
      "limit": {"type": "integer", "description": "返回数量", "default": 10}
    },
    "required": ["query"]
  }
}
```

---

## 4. ToolAd — 服务描述文件构建器

> 文件：`tool_ad.py`（约 67 行）

`ToolAd` 负责生成 ATTP 工具节点的服务描述文件（`ad.json`），供协议节点和 Agent 发现和调用工具。

### 4.1 类定义

```python
class ToolAd:
    def __init__(
        self,
        did: str,                                  # 节点 DID 标识
        name: str,                                 # 节点名称
        description: str = "",                     # 节点描述
        attp_endpoint: str = "",                   # ATTP 服务端点 URL
        mcp_tools: list[dict[str, Any]] | None = None,  # 工具列表
        public_key_endpoint: str = "",             # 公钥端点
        version: str = "0.1.0",                    # 描述符 schema 版本（见下注）
    )
```

> **关于 `version` 字段**：`version: str = "0.1.0"` 是 **ad.json 描述符自身的 schema 版本号**（`type: "attp-tool-node"` 的描述符版本），**不是** ATTP 协议版本、SDK 包版本或本文档版本。请勿与其他版本号混淆。构造时未传入则默认 `"0.1.0"`。

### 4.2 ad.json 输出格式

`to_dict()` 输出结构（字段顺序与代码一致）：

```json
{
  "type": "attp-tool-node",
  "version": "0.1.0",
  "identifier": "did:wba:tool-server.local:my-tool",
  "name": "my-tool-server",
  "description": "一个示例工具服务",
  "attp_endpoint": "http://localhost:9000/attp",
  "public_key_endpoint": "",
  "mcp_tools": [
    {
      "name": "search",
      "description": "搜索知识库",
      "inputSchema": { ... }
    }
  ]
}
```

其中 `"type": "attp-tool-node"` 是 Agent 侧 `MCPToolBridge.discover_tool_node` 在拉取 ad.json 时校验的类型标记。

### 4.3 核心方法

| 方法 | 说明 |
|------|------|
| `to_dict()` | 序列化为字典 |
| `to_json(indent=2)` | 序列化为 JSON 字符串（`ensure_ascii=False`） |
| `save_to_file(path)` | 保存到文件（自动创建父目录） |
| `from_dict(data)` (classmethod) | 从字典反序列化（读取 `identifier` → `did`） |
| `from_file(path)` (classmethod) | 从文件加载 |

### 4.4 默认输出路径

当未指定 `ad_output_path` 时，默认保存到：

```
~/.attp/tools/<node_name>/ad.json
```

---

## 5. ToolNodeMixin — 共用回传逻辑基类

> 文件：`mixin.py`（约 330 行）

`ToolNodeMixin` 是三种 SDK 工具节点的**共用逻辑基类**，采用 Mixin + 模板方法设计模式。它封装了 ATTP 工具节点所需的全部公共能力，子类只需实现两个抽象方法即可。

### 5.1 宿主类要求的属性

`ToolNodeMixin` 作为 Mixin，要求宿主类提供以下属性：

| 属性 | 类型 | 说明 |
|------|------|------|
| `did` | `str` | 节点 DID |
| `name` | `str` | 节点名称 |
| `description` | `str` | 节点描述 |
| `host` | `str` | 监听地址 |
| `port` | `int` | 监听端口 |
| `private_key_path` | `Path` | 私钥文件路径（已 `expanduser()`） |
| `attp_prefix` | `str` | ATTP 路由前缀 |
| `_ad_output_path` | `Path` | ad.json 输出路径 |
| `_app` | `FastAPI` | FastAPI 应用实例 |
| `_uvicorn_server` | `uvicorn.Server \| None` | Uvicorn 服务器实例 |
| `_serve_task` | `asyncio.Task \| None` | 异步服务任务 |

### 5.2 抽象方法

子类必须实现两个抽象方法：

```python
@abc.abstractmethod
async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, int]:
    """执行工具并返回 (result_str, http_status_code)。

    - 200 表示成功，result_str 为工具返回内容
    - 4xx/5xx 表示失败，result_str 为错误描述
    """

@abc.abstractmethod
def _build_ad(self) -> ToolAd:
    """构建 ToolAd 对象（供 ad.json 生成和端点返回）。"""
```

### 5.3 共用初始化（`_init_common`）

在子类 `__init__` 末尾调用，设置所有共用属性并注册 FastAPI 路由：

```python
def _init_common(
    self,
    did: str,
    name: str,
    description: str,
    host: str,
    port: int,
    private_key_path: str,
    attp_prefix: str,
    ad_output_path: str | None,
    app_title: str,
) -> None
```

初始化流程：
1. 设置基础属性（did, name, description, host, port, attp_prefix）
2. 将 `private_key_path` 包装为 `Path(...).expanduser()`
3. 创建 `FastAPI` 实例（`app_title` 为标题）
4. 调用 `_setup_routes()` 注册路由
5. 将 `_uvicorn_server`、`_serve_task` 置为 `None`
6. 确定 `_ad_output_path`（未指定则落到 `~/.attp/tools/<name>/ad.json`）

### 5.4 FastAPI 路由注册（`_setup_routes`）

注册三个 HTTP 端点：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `{attp_prefix}` | 处理 ATTP 工具调用请求（核心端点，接收纯 `NodeMessage` body） |
| GET | `{attp_prefix}/ad.json` | 返回工具节点描述文件（实时调用 `_build_ad().to_dict()`） |
| GET | `{attp_prefix}/health` | 健康检查，返回 `{"status": "ok", "did": "..."}` |

默认 `attp_prefix` 为 `/attp`，因此默认端点为：

```
POST /attp           — 工具调用
GET  /attp/ad.json   — 服务描述
GET  /attp/health    — 健康检查
```

POST 端点会对 body 做一次 JSON 解析；若 body 不是合法 JSON，直接返回 `400 {"error": "Invalid JSON body"}`。

### 5.5 NodeMessage 解析（`_parse_node_message`）

静态方法，从 HTTP request body 解析 `NodeMessage`：

```python
@staticmethod
def _parse_node_message(body: dict) -> tuple[
    NodeMessage | None, RecordedHop | None, str, str, str
]
```

**返回值**：`(NodeMessage, RecordedHop, session_id, protocol_url, nonce)`

内部逻辑：`NodeMessage.from_dict(body)` → 取 `nm.recorded_hop`，再从 `rh` 取 `session_id`、从 `nm` 取 `protocol_url` 与 `nonce`。解析失败时前两项为 `None`，其余三项为空字符串。

### 5.6 工具请求处理（`_handle_tool_request`）— 核心模板方法

这是工具节点处理请求的核心方法，实现了完整的 ATTP 双轮回溯确认流程。整个处理分为**两大跳**：

#### 第一跳：A2T 确认（Agent → Tool 确认）

```
步骤 1: 解析 NodeMessage(A2T)
         从 request body 解析得到 node_message_a2t 和 recorded_hop_a2t
         提取 session_id, protocol_url, nonce
         解析失败 → 400
         
步骤 2: 解析工具调用参数
         json.loads(recorded_hop_a2t.content) → tool_name, arguments
         JSONDecodeError / AttributeError → 400
         
步骤 3: 执行工具（子类实现 _execute_tool）
         result_str, status_code = await self._execute_tool(tool_name, arguments)
         status_code != 200 → 直接返回错误响应
         
步骤 4: 加载私钥
         load_private_key(self.private_key_path)
         加载失败 → 记录 error 日志，private_key = None（降级模式，见下）
         
步骤 5: BackMessage #2 → Protocol Node（Phase 1，Tool 确认收到 A2T）
         门控条件：protocol_url and recorded_hop_a2t and private_key 同时为真
         通过 send_back_message() POST 到 {protocol_url}/record
         BackPropagationError → 502
```

#### 第二跳：T2A 构建（Tool → Agent 报告）

```
步骤 6: 构建 RecordedHop_T2A
         - nonce: "{原nonce}_t2a"（原 nonce 为空时回退为 "{tool_name}_{time.time()}"）
         - hop_count: [原a2a_count, 原intra_count + 1]（intra 递增）
         - sender_did: self.did（工具节点自身）
         - target_did: sender_did（回复给调用者）
         - content: JSON {"tool_name": ..., "result": result_str}
         
步骤 7: 签名
         对 RecordedHop.content_hash() 用私钥签名 → sig_content
         门控条件：private_key 为真（否则跳过签名）
         
步骤 8: BackMessage #3 → Protocol Node（Phase 2，Tool 报告 T2A）
         门控条件：protocol_url and private_key 同时为真
         BackPropagationError → 502
         
步骤 9: 返回 NodeMessage(T2A)
         JSONResponse(node_message_t2a.to_dict())，HTTP 200
```

#### hop_count 递增规则

T2A 作为 **intra-hop**（节点内部操作），仅递增 `intra_count`：

```python
hop_count = [recorded_hop_a2t.hop_count[0], recorded_hop_a2t.hop_count[1] + 1]
#            a2a_count 保持不变              intra_count + 1
```

代码中另有一处防御性 fallback `hop_count = [0, 1]`（当 `recorded_hop_a2t` 为假时），但由于步骤 1 已在解析失败时返回 400，正常运行路径不会走到该分支。

#### 私钥缺失的降级行为（重要）

私钥加载失败时，`private_key` 为 `None`，此时**不仅跳过签名，还会跳过两次 `send_back_message`**（BackMessage #2 与 #3 的门控条件都包含 `private_key`）。即：工具仍会执行并返回 `NodeMessage(T2A)` 响应，但**整条 ATTP 溯源链断裂**——既无身份签名，也无回传确认。这是一种"可用优先"的降级，而非"安全优先"的拒绝。

#### 错误处理策略

| 阶段 | 错误 | 处理 |
|------|------|------|
| Body JSON 解析 | 非 JSON | 返回 400 |
| NodeMessage 解析 | 格式错误 | 返回 400 |
| content 解析 | JSON 解码失败 / AttributeError | 返回 400 |
| 工具执行 | 未找到工具 | 返回 404 |
| 工具执行 | 执行异常 | 返回 500 |
| BackMessage #2 | 发送失败（`BackPropagationError`） | 返回 502 |
| BackMessage #3 | 发送失败（`BackPropagationError`） | 返回 502 |
| 私钥加载 | 加载失败 | 记录日志，进入降级模式（跳过签名与回传，响应不阻塞） |

### 5.7 ad.json 生成（`generate_ad`）

```python
def generate_ad(self, output_path: str | None = None) -> ToolAd
```

调用子类 `_build_ad()` 构建 `ToolAd`，保存到文件（`output_path` 优先，否则用 `_ad_output_path`）并返回。在 `start()` 中自动调用。方法内部以惰性导入 `ToolAd`（避免循环导入）。

### 5.8 生命周期管理

#### `start()` — 启动服务

```python
async def start(self) -> None
```

1. 调用 `generate_ad()` 生成描述文件
2. 创建 `uvicorn.Config(self._app, host=self.host, port=self.port, log_level="info")`
3. 创建 `uvicorn.Server`，在 `asyncio.create_task` 中启动
4. 日志输出节点类型、名称、地址和 DID

#### `stop()` — 停止服务

```python
async def stop(self) -> None
```

1. 设置 `_uvicorn_server.should_exit = True` 通知 uvicorn 优雅退出
2. `await asyncio.wait_for(self._serve_task, timeout=5.0)` 等待结束
3. 超时则 `cancel()` 任务并吞掉 `CancelledError`

---

## 6. ATTPToolNode — 自定义工具函数节点

> 文件：`tool_node.py`（约 113 行）

`ATTPToolNode` 将开发者自定义的 Python 异步函数包装为 ATTP 工具节点，是最直接的接入方式。

### 6.1 类定义

```python
class ATTPToolNode(ToolNodeMixin):
    def __init__(
        self,
        did: str,                          # 节点 DID
        name: str,                         # 节点名称
        private_key_path: str | None = None,  # 私钥路径（默认 ~/.attp/tools/<name>/did/key-1_private.pem）
        host: str = "0.0.0.0",             # 监听地址
        port: int = 9000,                  # 监听端口
        description: str = "",             # 节点描述
        ad_output_path: str | None = None, # ad.json 输出路径
        attp_prefix: str = "/attp",        # ATTP 路由前缀
    )
```

> 说明：`dev` 分支的构造参数即以上 8 个，**不存在** `tls_config` / security 相关参数。

### 6.2 工具注册

#### 装饰器方式

```python
@node.tool(
    "search",                                    # 工具名称
    "搜索知识库",                                 # 工具描述
    {"type": "object", "properties": {...}},     # 输入 JSON Schema
)
async def search(query: str, limit: int = 10):
    return {"results": [...]}
```

`@node.tool()` 装饰器内部调用 `register_handler()`，将函数封装为 `ToolHandler` 并注册到 `_handlers` 字典中。装饰器返回原函数（不被替换）。

#### 编程方式

```python
node.register_handler(ToolHandler(
    name="search",
    description="搜索知识库",
    input_schema={"type": "object", "properties": {...}},
    handler=my_search_func,
))
```

工具存储在 `self._handlers: dict[str, ToolHandler]` 中，以工具名称为键，**同名工具会被覆盖并发出 warning 日志**。

### 6.3 抽象方法实现

#### `_execute_tool(tool_name, arguments)`

```python
async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, int]:
```

1. 在 `_handlers` 字典中查找工具
2. 未找到返回 `(f"Tool not found: {tool_name}", 404)`
3. 执行 `await handler(**arguments)`：
   - 若返回值已经是 `str`，**原样返回**（不再 `json.dumps`）
   - 否则 `json.dumps(result, ensure_ascii=False)` 序列化为字符串
4. 异常返回 `(f"Tool execution failed: {str(e)}", 500)`

#### `_build_ad()`

构建 `ToolAd`，其中 `mcp_tools` 从所有已注册的 `ToolHandler` 的 `to_mcp_tool_dict()` 方法获取。

`attp_endpoint` 构建：
- `host == "0.0.0.0"` 时使用 `http://localhost:{port}{prefix}`
- 否则使用 `http://{host}:{port}{prefix}`

### 6.4 使用示例

```python
from attp.sdk.tools import ATTPToolNode

node = ATTPToolNode(
    did="did:wba:tool-server.local:my-tool",
    name="my-tool-server",
    private_key_path="key.pem",
    port=9000,
)

@node.tool("add", "计算两数之和", {
    "type": "object",
    "properties": {
        "a": {"type": "number", "description": "第一个数"},
        "b": {"type": "number", "description": "第二个数"},
    },
    "required": ["a", "b"],
})
async def add(a: float, b: float):
    return {"result": a + b}

await node.start()
```

---

## 7. MCPToATTPAdapter — FastMCP 实例适配器

> 文件：`mcp_adapter.py`（约 115 行）

`MCPToATTPAdapter` 将已有的 **FastMCP 实例**（同进程）包装为 ATTP 工具节点，适用于已经基于 MCP 协议开发的服务。

### 7.1 类定义

```python
class MCPToATTPAdapter(ToolNodeMixin):
    def __init__(
        self,
        did: str,                              # 节点 DID
        name: str,                             # 节点名称
        mcp_server: FastMCP,                   # 已有的 FastMCP 实例
        private_key_path: str | None = None,   # 私钥路径
        host: str = "0.0.0.0",                 # 监听地址
        port: int = 9000,                      # 监听端口
        description: str = "",                 # 节点描述
        ad_output_path: str | None = None,     # ad.json 输出路径
        attp_prefix: str = "/attp",            # ATTP 路由前缀
    )
```

核心属性：
- `self.mcp_server` — 保存传入的 FastMCP 实例引用

### 7.2 抽象方法实现

#### `_execute_tool(tool_name, arguments)`

```python
async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, int]:
```

1. 调用 `await self.mcp_server.call_tool(tool_name, arguments)`
2. 结果处理：
   - 列表类型：`"\n".join()` 拼接每个元素的 `text` 属性（`getattr(item, 'text', str(item))`）
   - 其他类型：`str()` 转换
3. 异常返回 `(f"Tool execution failed: {str(e)}", 500)`

#### `_build_ad()`

调用 `_extract_tools_from_mcp()` 从 FastMCP 实例提取工具列表来构建 `ToolAd`。`attp_endpoint` 的构建规则与 `ATTPToolNode` 一致。

### 7.3 MCP 工具提取（`_extract_tools_from_mcp`）

```python
def _extract_tools_from_mcp(self) -> list[dict[str, Any]]:
```

从 FastMCP 实例的内部 `_tool_manager._tools` 字典中提取工具信息。整体被 `try/except` 包裹，失败时返回空列表并记录 warning：

```python
tools = []
try:
    tool_manager = getattr(self.mcp_server, '_tool_manager', None)
    if tool_manager:
        for tool_name, tool_obj in tool_manager._tools.items():
            tools.append({
                "name": tool_name,
                "description": getattr(tool_obj, 'description', '') or '',
                "inputSchema": getattr(tool_obj, 'parameters', {}) or {},
            })
except Exception as e:
    logger.warning("Failed to extract tools from FastMCP: %s", e)
return tools
```

> **注意**：此方法访问 FastMCP 的内部属性（`_tool_manager`、`_tools`），并对每个属性都用 `getattr(..., default)` 做了防御。仍依赖 FastMCP 的实现细节，版本升级时可能需要适配。

### 7.4 使用示例

```python
from mcp.server.fastmcp import FastMCP
from attp.sdk.tools import MCPToATTPAdapter

my_mcp = FastMCP("my-service")

@my_mcp.tool()
async def search(query: str) -> str:
    return "results..."

adapter = MCPToATTPAdapter(
    did="did:wba:tool.local:search-service",
    name="search-service",
    mcp_server=my_mcp,
    private_key_path="key.pem",
    port=9000,
)
await adapter.start()
```

---

## 8. MCPProxyToolNode — 远程 MCP 代理网关

> 文件：`mcp_proxy.py`（约 258 行）

`MCPProxyToolNode` 是最复杂的接入策略，它作为**本地代理网关**，连接远程 MCP 服务并暴露为 ATTP 端点。本地代理持有 DID 和私钥，负责对响应签名并记录溯源链；远程 MCP 服务本身不在 ATTP 信任边界之内。

### 8.1 与 MCPToATTPAdapter 的区别

| 维度 | MCPToATTPAdapter | MCPProxyToolNode |
|------|-----------------|-----------------|
| MCP 服务位置 | 同进程（本地对象） | 远程网络（HTTP 端点） |
| 工具执行方式 | 直接调用 Python 方法 | MCP JSON-RPC over HTTP |
| 签名方 | 本地进程 | 本地代理（非远程服务） |
| 工具发现 | 从对象属性提取 | 远程 MCP 协议发现 |
| 启动流程 | 直接启动 | 先发现远程工具，再启动 |

### 8.2 类定义

```python
class MCPProxyToolNode(ToolNodeMixin):
    def __init__(
        self,
        did: str,                              # 节点 DID
        name: str,                             # 节点名称
        config: dict[str, Any],                # MCP 服务配置（含 mcpServers）
        private_key_path: str | None = None,   # 私钥路径
        host: str = "0.0.0.0",                 # 监听地址
        port: int = 9000,                      # 监听端口
        description: str = "",                 # 节点描述
        ad_output_path: str | None = None,     # ad.json 输出路径
        attp_prefix: str = "/attp",            # ATTP 路由前缀
    )
```

核心属性：

| 属性 | 类型 | 说明 |
|------|------|------|
| `_config` | `dict[str, Any]` | MCP 服务配置（包含 `mcpServers` 键） |
| `_remote_tools` | `dict[str, list[dict]]` | 远程工具缓存：`server_name → [tool_dicts]` |
| `_tool_index` | `dict[str, tuple[str, dict]]` | 扁平工具索引：`tool_name → (server_name, server_config)` |

### 8.3 MCP 配置格式

`config` 参数遵循 MCP 标准配置格式：

```json
{
  "mcpServers": {
    "web-reader": {
      "type": "streamableHttp",
      "url": "https://open.bigmodel.cn/api/mcp/web_reader/mcp",
      "headers": {"Authorization": "Bearer xxx"}
    },
    "code-interpreter": {
      "type": "streamableHttp",
      "url": "https://example.com/mcp",
      "headers": {}
    }
  }
}
```

> 注：当前实现实际只读取每个服务配置中的 `url` 与 `headers` 字段，`type` 字段（如 `streamableHttp` / `sse`）仅作为声明性占位，代码不依据它切换传输方式——统一以 JSON-RPC POST 调用 `url`。

### 8.4 远程服务发现（`discover_remote_tools`）

```python
async def discover_remote_tools(self) -> None:
```

遍历 `_config["mcpServers"]` 中的所有服务配置，对每个服务：

1. 调用 `_fetch_tools_from_server(server_name, server_config)` 获取工具列表
2. 存入 `_remote_tools[server_name]`
3. 为每个工具建立 `_tool_index[tool_name] = (server_name, server_config)` 映射
4. 单个服务发现失败时记录 error 日志，不中断其他服务的发现

#### MCP JSON-RPC 发现协议（`_fetch_tools_from_server`）

完整的 MCP 三步握手（每个请求都会合并 `Content-Type: application/json` 与配置中的 `headers`）：

```
客户端                                    远程 MCP 服务
  │                                          │
  │  1. POST initialize                      │
  │  {"jsonrpc":"2.0","id":1,"method":       │
  │   "initialize","params":{                │
  │     "protocolVersion":"2024-11-05",      │
  │     "capabilities":{},                   │
  │     "clientInfo":{"name":"attp-proxy-    │
  │       <self.name>","version":"0.1.0"}}}  │
  ├─────────────────────────────────────────→│
  │  ← 200 OK                                │
  │                                          │
  │  2. POST notifications/initialized       │
  │  {"jsonrpc":"2.0",                       │
  │   "method":"notifications/initialized"}  │
  ├─────────────────────────────────────────→│
  │  ← 200 OK (响应被忽略)                    │
  │                                          │
  │  3. POST tools/list                      │
  │  {"jsonrpc":"2.0","id":2,                │
  │   "method":"tools/list","params":{}}     │
  ├─────────────────────────────────────────→│
  │  ← 200 OK                                │
  │  {"result":{"tools":[...]}}              │
  │                                          │
```

**超时设置**：
- Initialize：15 秒（非 200 抛 `RuntimeError`）
- Initialized 通知：10 秒（响应被忽略）
- tools/list：15 秒（非 200 抛 `RuntimeError`）

**协议版本**：`2024-11-05`

返回的每个 tool 会被规整为 `{"name", "description", "inputSchema"}` 三字段字典。

### 8.5 远程工具调用（`_call_remote_tool`）

```python
async def _call_remote_tool(
    self, server_config: dict[str, Any], tool_name: str, arguments: dict[str, Any]
) -> str:
```

通过 MCP JSON-RPC `tools/call` 方法调用远程工具：

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": { ... }
  }
}
```

**超时设置**：60 秒（比发现阶段更长，适应工具执行时间）

**结果解析**：

```python
result_data = result.get("result", {})
content_list = result_data.get("content", [])
if isinstance(content_list, list):
    parts = []
    for item in content_list:
        if isinstance(item, dict):
            parts.append(item.get("text", str(item)))   # 优先取 text，回退 str(item)
        else:
            parts.append(str(item))
    return "\n".join(parts)
return json.dumps(result_data, ensure_ascii=False)       # content 非列表时的回退
```

### 8.6 抽象方法实现

#### `_execute_tool(tool_name, arguments)`

1. 在 `_tool_index` 中查找工具（获取对应的 `(server_name, server_config)`）
2. 未找到返回 `(f"Tool not found: {tool_name}", 404)`
3. 调用 `_call_remote_tool()` 执行远程调用
4. 远程调用失败返回 `(f"Remote tool execution failed: {str(e)}", 502)`

#### `_build_ad()`

收集 `_remote_tools` 中所有服务的工具列表，合并后构建 `ToolAd`。`attp_endpoint` 构建规则同其它节点。

### 8.7 生命周期覆盖

```python
async def start(self) -> None:
    """启动代理：先发现远程工具，再启动 ATTP 服务。"""
    logger.info("Discovering remote MCP tools...")
    await self.discover_remote_tools()     # 先发现
    logger.info("Discovered %d tools from %d servers", ...)
    await super().start()                  # 再启动（生成 ad + uvicorn）
```

**启动顺序**：
1. 连接所有远程 MCP 服务，获取工具列表
2. 构建工具索引
3. 生成 ad.json（包含所有远程工具的描述）
4. 启动 FastAPI + uvicorn

### 8.8 使用示例

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

await proxy.start()  # 自动发现远程工具，暴露为 ATTP 端点
```

---

## 9. 核心数据流

### 9.1 工具调用请求处理全流程

以 Agent 通过协议节点调用工具为例，展示完整的请求处理流程（工具节点侧由 `ToolNodeMixin._handle_tool_request` 承担）：

```
  Agent A                   Protocol Node              Tool Node (Mixin)
    │                          │                          │
    │  ① NodeMessage(A2T)      │                          │
    │  (A 签名, tool_name,     │                          │
    │   arguments)              │                          │
    │  (经协议节点转发)          │                          │
    │ ────────────────────────→│ ────────────────────────→│
    │                          │                          │
    │                          │                   步骤 1: 解析 NodeMessage(A2T)
    │                          │                          │
    │                          │                   步骤 2: 解析 content
    │                          │                     → tool_name, arguments
    │                          │                          │
    │                          │                   步骤 3: _execute_tool()
    │                          │                     (子类实现：本地/MCP/远程)
    │                          │                     → result_str, 200
    │                          │                          │
    │                          │                   步骤 4: 加载私钥
    │                          │                     (失败则降级：跳过签名+回传)
    │                          │                          │
    │                          │  ② BackMessage #2        │
    │                          │  (Phase 1, Tool 确认 A2T) │
    │                          │←────────────────────────│
    │                          │                          │
    │                          │  协议节点校验：            │
    │                          │  身份签名 + 暂存 Tool 确认 │
    │                          │                          │
    │                          │                   步骤 5-6: 构建 T2A
    │                          │                     RecordedHop_T2A
    │                          │                     (Tool 签名, hop_count 递增)
    │                          │                          │
    │                          │  ③ BackMessage #3        │
    │                          │  (Phase 2, Tool 报告 T2A) │
    │                          │←────────────────────────│
    │                          │                          │
    │                          │  协议节点校验：            │
    │                          │  Nonce 匹配 + 行为记录     │
    │                          │                          │
    │  ④ NodeMessage(T2A)      │                          │
    │  (Tool 签名, result)      │                          │
    │←─────────────────────────│←────────────────────────│
    │                          │                          │
```

> Agent 侧还会在收到 T2A 后补发 BackMessage #4（Phase 1，Agent 确认 T2A），完成四轮回传。该步骤由 `MCPToolBridge` 负责，详见 9.4。

### 9.2 MCP 代理网关交互序列

`MCPProxyToolNode` 的完整交互序列，展示远程 MCP 服务发现和工具调用两个阶段：

```
                         MCPProxyToolNode                Remote MCP Service
                              │                              │
                 ════════ 服务发现阶段（启动时） ════════
                              │                              │
                              │  POST /mcp (initialize)      │
                              ├─────────────────────────────→│
                              │  ← 200 OK                    │
                              │                              │
                              │  POST /mcp (initialized)     │
                              ├─────────────────────────────→│
                              │  ← 200 OK                    │
                              │                              │
                              │  POST /mcp (tools/list)      │
                              ├─────────────────────────────→│
                              │  ← {"result":{"tools":[...]}} │
                              │                              │
                              │  缓存工具列表到               │
                              │  _remote_tools + _tool_index  │
                              │                              │
                 ════════ 工具调用阶段（运行时） ════════
                              │                              │
  Agent ──→ ATTP /attp ──→   │                              │
                              │  _execute_tool()             │
                              │  查找 _tool_index             │
                              │                              │
                              │  POST /mcp (tools/call)      │
                              │  {"name":"xxx","arguments":{}}│
                              ├─────────────────────────────→│
                              │  ← {"result":{"content":[..]}} │
                              │                              │
                              │  解析 content → result_str    │
                              │  签名 + 回传协议节点           │
                              │  返回 NodeMessage(T2A)        │
                              │                              │
```

### 9.3 三种节点的 `_execute_tool` 对比

```
ATTPToolNode:
  _handlers[tool_name](**arguments)
      ↓
  本地 Python 异步函数执行
      ↓
  str 结果原样返回；非 str → json.dumps(result)

MCPToATTPAdapter:
  mcp_server.call_tool(tool_name, arguments)
      ↓
  FastMCP 内部分发（同进程）
      ↓
  list 结果 → 拼接 text 字段；其他 → str()

MCPProxyToolNode:
  _tool_index[tool_name] → (server_name, server_config)
      ↓
  aiohttp POST (tools/call JSON-RPC)
      ↓
  解析远程响应的 content 列表（每项取 text）
```

### 9.4 Agent 侧对应方：MCPToolBridge（参考）

工具节点端的对端是 Agent 侧的 `MCPToolBridge`（`python/attp/app/tools/mcp_tool_bridge.py`）。本节仅说明与工具节点直接相关的契约，完整行为见 Agent 侧分析文档。

**角色**：`MCPToolBridge` 同时是一个 **MCP SSE Server**（通过 `FastMCP("attp-tools").sse_app()` 暴露，供 nanobot 内置的 MCP Client 连接）和一个 **ATTP Tool Client**（把 MCP 工具调用桥接为 ATTP 消息发往远程工具节点）。

**与工具节点端的契约**：

- **请求**：`MCPToolBridge._call_tool_node` 构造 `NodeMessage(A2T)`（`RecordedHop_A2T` 经 `AgentTracer.append_hop` 生成、`content` 为 `{"tool_name", "arguments"}`），以 `aiohttp` POST 到工具节点的 `{attp_prefix}` 端点，body 为 `node_message_a2t.to_dict()`，超时 60 秒。
- **响应**：工具节点返回 `NodeMessage(T2A)`（`to_dict()`），`MCPToolBridge` 用 `NodeMessage.from_dict(result_body)` 解析，从 `recorded_hop_t2a.content` 中取 `result`。
- **回传配合**：Agent 侧在发送 A2T 前先发 BackMessage #1（Phase 2，Agent 报告），收到 T2A 后补发 BackMessage #4（Phase 1，Agent 确认）。与工具节点的 #2/#3 合起来构成完整四轮回传。
- **发现**：`MCPToolBridge.discover_tool_node(ad_url)` 拉取 ad.json，校验 `type == "attp-tool-node"`，读取 `identifier / name / attp_endpoint / mcp_tools` 等字段；`attp_endpoint` 会用 `_rewrite_endpoint_host` 做 netloc 改写（跨容器可达性）。

换言之，工具节点对外暴露的就是"**纯 `NodeMessage` 进、纯 `NodeMessage` 出**"的 HTTP 端点；ATTP 的回传与签名细节完全封装在 `ToolNodeMixin` 与 `MCPToolBridge` 两侧。

---

## 10. 设计模式与总结

### 10.1 设计模式应用

| 设计模式 | 应用位置 | 说明 |
|---------|---------|------|
| **模板方法** | `ToolNodeMixin._handle_tool_request()` | 定义请求处理骨架，子类实现 `_execute_tool()` 和 `_build_ad()` |
| **Mixin** | `ToolNodeMixin` | 将共用逻辑抽取为独立 Mixin，三种节点类通过继承复用 |
| **装饰器** | `ATTPToolNode.tool()` | 提供类似 FastMCP 的 `@node.tool()` 装饰器注册方式 |
| **策略** | 三种 `_execute_tool()` 实现 | 不同的工具执行策略（本地函数 / MCP 对象 / 远程代理） |
| **代理** | `MCPProxyToolNode` | 本地代理远程 MCP 服务，隐藏网络通信细节 |
| **外观** | `ToolAd` | 简化 ad.json 的构建、序列化和文件操作 |

### 10.2 架构优势

1. **低接入成本**：开发者只需实现一个异步函数或传入 FastMCP 实例即可接入 ATTP 网络
2. **关注点分离**：工具执行逻辑与 ATTP 协议逻辑完全解耦，Mixin 承载协议复杂性
3. **MCP 生态兼容**：通过 Adapter 和 Proxy 两种方式无缝接入 MCP 生态
4. **统一接口**：三种接入策略对外暴露完全一致的 HTTP 端点（`/attp`, `/attp/ad.json`, `/attp/health`），且都是"纯 `NodeMessage` 进、纯 `NodeMessage(T2A)` 出"

### 10.3 安全机制

ATTP 保护**仅覆盖 Agent ↔ Tool 这一跳**（即 `MCPToolBridge` 与工具节点之间）。在 `dev` 分支上，该信任边界由 DID 身份与内容溯源签名构成，**不使用 TLS / 传输层加密**。

| 安全能力 | 实现方式 |
|---------|---------|
| **DID 身份标识** | 每个工具节点持有唯一 DID；`BackMessage` 携带 `sig_identity` 身份签名 |
| **内容签名** | 对 `RecordedHop.content_hash()` 使用私钥签名，写入 `sig_content`（T2A 必签；A2T 由 Agent 侧签） |
| **双轮回传** | 工具节点执行两次 `send_back_message`（#2 确认 A2T + #3 报告 T2A），由协议节点校验 |
| **hop_count 追踪** | T2A 消息递增 `intra_count`，保证消息序号连续性 |
| **严格门控** | 回传失败（`BackPropagationError`）直接返回 502，阻断响应 |
| **私钥缺失降级** | 私钥加载失败时进入"可用优先"降级：跳过签名**且**跳过两次回传，仍返回响应——此时溯源链断裂（见 5.6） |

### 10.4 扩展性

添加新的工具接入策略只需：

1. 创建新类继承 `ToolNodeMixin`
2. 实现 `_execute_tool()` — 定义工具执行逻辑（返回 `(result_str, status_code)`）
3. 实现 `_build_ad()` — 定义 ad.json 内容
4. 在 `__init__` 末尾调用 `_init_common()` — 完成路由注册和属性初始化

即可获得完整的 ATTP 协议能力（签名、回传、ad.json 生成、HTTP 服务）。
