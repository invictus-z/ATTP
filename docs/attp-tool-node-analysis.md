# ATTP 工具服务节点端（SDK Tools）代码与功能分析

> 本文档对 `python/attp/sdk/tools/` 目录下的所有模块进行全面的代码结构与功能分析。

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

### 辅助类

| 类 | 文件 | 职责 |
|----|------|------|
| `ToolHandler` | `handler.py` | 单工具处理器描述（名称 + Schema + 回调） |
| `ToolAd` | `tool_ad.py` | 服务描述文件 `ad.json` 的构建器 |

### 外部依赖关系

```
sdk/tools/
  ├── attp.core.authentication.keys      → load_private_key()  加载私钥
  ├── attp.core.authentication.signatures → sign_hash()         内容签名
  ├── attp.core.message.event            → NodeMessage, RecordedHop  消息结构
  ├── attp.core.message.back_sender      → send_back_message() 回传协议节点
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

### 2.2 类继承关系

```
              ToolNodeMixin (ABC, Mixin)
              ┌────────────────────────┐
              │ _execute_tool() [抽象]  │
              │ _build_ad()     [抽象]  │
              │ _handle_tool_request()  │
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
                  ├──→ send_back_message() (回传协议节点)
                  └──→ FastAPI + uvicorn (HTTP 服务)
```

---

## 3. ToolHandler — 单工具处理器描述

> 文件：`handler.py`（53 行）

`ToolHandler` 是单个工具的处理器抽象，将工具的**元信息**（名称、描述、输入 Schema）与**执行逻辑**（异步回调函数）封装在一起。

### 3.1 类定义

```python
class ToolHandler:
    def __init__(
        self,
        name: str,                                    # 工具名称（全局唯一标识）
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

> 文件：`tool_ad.py`（68 行）

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
        version: str = "0.1.0",                    # 版本号
    )
```

### 4.2 ad.json 输出格式

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

### 4.3 核心方法

| 方法 | 说明 |
|------|------|
| `to_dict()` | 序列化为字典 |
| `to_json(indent=2)` | 序列化为 JSON 字符串 |
| `save_to_file(path)` | 保存到文件（自动创建父目录） |
| `from_dict(data)` | 类方法：从字典反序列化 |
| `from_file(path)` | 类方法：从文件加载 |

### 4.4 默认输出路径

当未指定 `ad_output_path` 时，默认保存到：

```
~/.attp/tools/<node_name>/ad.json
```

---

## 5. ToolNodeMixin — 共用回传逻辑基类

> 文件：`mixin.py`（331 行）

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
| `private_key_path` | `Path` | 私钥文件路径 |
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
1. 设置基础属性（did, name, host, port 等）
2. 创建 `FastAPI` 实例（`app_title` 为标题）
3. 调用 `_setup_routes()` 注册路由
4. 确定 `ad.json` 输出路径

### 5.4 FastAPI 路由注册（`_setup_routes`）

注册三个 HTTP 端点：

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `{attp_prefix}` | 处理 ATTP 工具调用请求（核心端点） |
| GET | `{attp_prefix}/ad.json` | 返回工具节点描述文件 |
| GET | `{attp_prefix}/health` | 健康检查，返回 `{"status": "ok", "did": "..."}` |

默认 `attp_prefix` 为 `/attp`，因此默认端点为：

```
POST /attp           — 工具调用
GET  /attp/ad.json   — 服务描述
GET  /attp/health    — 健康检查
```

### 5.5 NodeMessage 解析（`_parse_node_message`）

静态方法，从 HTTP request body 解析 `NodeMessage`：

```python
@staticmethod
def _parse_node_message(body: dict) -> tuple[
    NodeMessage | None, RecordedHop | None, str, str, str
]
```

**返回值**：`(NodeMessage, RecordedHop, session_id, protocol_url, nonce)`

解析失败时前两项为 `None`，其余为空字符串。

### 5.6 工具请求处理（`_handle_tool_request`）— 核心模板方法

这是工具节点处理请求的核心方法，实现了完整的 ATTP 双轮回溯确认流程。整个处理分为**两大跳**：

#### 第一跳：A2T 确认（Agent → Tool 确认）

```
步骤 1: 解析 NodeMessage(A2T)
         从 request body 解析得到 node_message_a2t 和 recorded_hop_a2t
         提取 session_id, protocol_url, nonce
         
步骤 2: 解析工具调用参数
         从 recorded_hop_a2t.content 解析 JSON
         提取 tool_name 和 arguments
         
步骤 3: 执行工具（子类实现 _execute_tool）
         result_str, status_code = await self._execute_tool(tool_name, arguments)
         失败则直接返回错误响应
         
步骤 4: BackMessage #2 → Protocol Node
         发送 Phase 1 回传（Tool 确认收到 A2T 消息）
         使用 send_back_message() 发送到协议节点
         失败返回 502
```

#### 第二跳：T2A 构建（Tool → Agent 报告）

```
步骤 5: 构建 RecordedHop_T2A
         - nonce: "{原nonce}_t2a"
         - hop_count: [原a2a_count, 原intra_count + 1]（intra 递增）
         - sender_did: self.did（工具节点自身）
         - target_did: sender_did（回复给调用者）
         - content: JSON {"tool_name": ..., "result": ...}
         
步骤 6: 签名
         使用私钥对 content_hash() 签名，赋值给 sig_content
         
步骤 7: BackMessage #3 → Protocol Node
         发送 Phase 2 回传（Tool 报告 T2A 消息）
         
步骤 8: 返回 NodeMessage(T2A)
         以 JSON 响应返回给调用者
```

#### hop_count 递增规则

T2A 作为 **intra-hop**（节点内部操作），仅递增 `intra_count`：

```python
hop_count = [recorded_hop_a2t.hop_count[0], recorded_hop_a2t.hop_count[1] + 1]
#            a2a_count 保持不变              intra_count + 1
```

#### 错误处理策略

| 阶段 | 错误 | 处理 |
|------|------|------|
| NodeMessage 解析 | 格式错误 | 返回 400 |
| content 解析 | JSON 解码失败 | 返回 400 |
| 工具执行 | 未找到工具 | 返回 404 |
| 工具执行 | 执行异常 | 返回 500 |
| BackMessage #2 | 发送失败 | 返回 502 |
| BackMessage #3 | 发送失败 | 返回 502 |
| 私钥加载 | 加载失败 | 记录错误日志，跳过签名（不阻塞） |

### 5.7 ad.json 生成（`generate_ad`）

```python
def generate_ad(self, output_path: str | None = None) -> ToolAd
```

调用子类 `_build_ad()` 构建 `ToolAd`，保存到文件并返回。在 `start()` 中自动调用。

### 5.8 生命周期管理

#### `start()` — 启动服务

```python
async def start(self) -> None
```

1. 调用 `generate_ad()` 生成描述文件
2. 创建 `uvicorn.Config` 和 `uvicorn.Server`
3. 在 asyncio Task 中启动服务
4. 日志输出节点类型、名称、地址和 DID

#### `stop()` — 停止服务

```python
async def stop(self) -> None
```

1. 设置 `should_exit = True` 通知 uvicorn 优雅退出
2. 等待服务任务结束（超时 5 秒）
3. 超时后取消任务

---

## 6. ATTPToolNode — 自定义工具函数节点

> 文件：`tool_node.py`（114 行）

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

`@node.tool()` 装饰器内部调用 `register_handler()`，将函数封装为 `ToolHandler` 并注册到 `_handlers` 字典中。

#### 编程方式

```python
node.register_handler(ToolHandler(
    name="search",
    description="搜索知识库",
    input_schema={"type": "object", "properties": {...}},
    handler=my_search_func,
))
```

工具存储在 `self._handlers: dict[str, ToolHandler]` 中，以工具名称为键，**同名工具会被覆盖并发出警告日志**。

### 6.3 抽象方法实现

#### `_execute_tool(tool_name, arguments)`

```python
async def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, int]:
```

1. 在 `_handlers` 字典中查找工具
2. 未找到返回 `("Tool not found: ...", 404)`
3. 执行 `handler(**arguments)`，结果序列化为 JSON 字符串
4. 异常返回 `("Tool execution failed: ...", 500)`

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

> 文件：`mcp_adapter.py`（116 行）

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

1. 调用 `self.mcp_server.call_tool(tool_name, arguments)`
2. 结果处理：
   - 列表类型：`"\n".join()` 拼接每个元素的 `text` 属性
   - 其他类型：`str()` 转换
3. 异常返回 `("Tool execution failed: ...", 500)`

#### `_build_ad()`

调用 `_extract_tools_from_mcp()` 从 FastMCP 实例提取工具列表来构建 `ToolAd`。

### 7.3 MCP 工具提取（`_extract_tools_from_mcp`）

```python
def _extract_tools_from_mcp(self) -> list[dict[str, Any]]:
```

从 FastMCP 实例的内部 `_tool_manager._tools` 字典中提取工具信息：

```python
tool_manager = self.mcp_server._tool_manager
for tool_name, tool_obj in tool_manager._tools.items():
    tools.append({
        "name": tool_name,
        "description": tool_obj.description or '',
        "inputSchema": tool_obj.parameters or {},
    })
```

> **注意**：此方法访问 FastMCP 的内部属性（`_tool_manager`、`_tools`），依赖 FastMCP 的实现细节，版本升级时可能需要适配。

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

> 文件：`mcp_proxy.py`（259 行）

`MCPProxyToolNode` 是最复杂的接入策略，它作为**本地代理网关**，连接远程 MCP 服务并暴露为 ATTP 端点。

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
        config: dict[str, Any],                # MCP 服务配置
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

### 8.4 远程服务发现（`discover_remote_tools`）

```python
async def discover_remote_tools(self) -> None:
```

遍历 `_config["mcpServers"]` 中的所有服务配置，对每个服务：

1. 调用 `_fetch_tools_from_server()` 获取工具列表
2. 存入 `_remote_tools[server_name]`
3. 为每个工具建立 `_tool_index[tool_name] = (server_name, server_config)` 映射

#### MCP JSON-RPC 发现协议（`_fetch_tools_from_server`）

完整的 MCP 三步握手：

```
客户端                                    远程 MCP 服务
  │                                          │
  │  1. POST initialize                      │
  │  {"jsonrpc":"2.0","method":"initialize", │
  │   "params":{"protocolVersion":"2024-11-05", ...}}
  ├─────────────────────────────────────────→│
  │  ← 200 OK                                │
  │                                          │
  │  2. POST notifications/initialized       │
  │  {"jsonrpc":"2.0","method":"notifications/initialized"}
  ├─────────────────────────────────────────→│
  │  ← 200 OK (忽略响应)                      │
  │                                          │
  │  3. POST tools/list                      │
  │  {"jsonrpc":"2.0","method":"tools/list"}  │
  ├─────────────────────────────────────────→│
  │  ← 200 OK                                │
  │  {"result":{"tools":[...]}}              │
  │                                          │
```

**超时设置**：
- Initialize：15 秒
- Initialized 通知：10 秒
- tools/list：15 秒

**协议版本**：`2024-11-05`

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
# 提取每个 item 的 text 字段，拼接为字符串
```

### 8.6 抽象方法实现

#### `_execute_tool(tool_name, arguments)`

1. 在 `_tool_index` 中查找工具（获取对应的远程服务配置）
2. 未找到返回 `("Tool not found: ...", 404)`
3. 调用 `_call_remote_tool()` 执行远程调用
4. 远程调用失败返回 `("Remote tool execution failed: ...", 502)`

#### `_build_ad()`

收集 `_remote_tools` 中所有服务的工具列表，合并后构建 `ToolAd`。

### 8.7 生命周期覆盖

```python
async def start(self) -> None:
    """启动代理：先发现远程工具，再启动 ATTP 服务。"""
    await self.discover_remote_tools()     # 先发现
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

以 Agent 通过协议节点调用工具为例，展示完整的请求处理流程：

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
    │                          │                          │
    │                          │  ② BackMessage #2        │
    │                          │  (Phase 1, Tool 确认 A2T) │
    │                          │←────────────────────────│
    │                          │                          │
    │                          │  协议节点 Branch A:        │
    │                          │  暂存 + 验证 Tool 身份     │
    │                          │                          │
    │                          │                   步骤 5-6: 构建 T2A
    │                          │                     RecordedHop_T2A
    │                          │                     (Tool 签名, hop_count 递增)
    │                          │                          │
    │                          │  ③ BackMessage #3        │
    │                          │  (Phase 2, Tool 报告 T2A) │
    │                          │←────────────────────────│
    │                          │                          │
    │                          │  协议节点 Branch B:        │
    │                          │  Nonce 匹配 + 验证        │
    │                          │  行为记录                  │
    │                          │                          │
    │  ④ NodeMessage(T2A)      │                          │
    │  (Tool 签名, result)      │                          │
    │←─────────────────────────│←────────────────────────│
    │                          │                          │
```

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
  json.dumps(result)

MCPToATTPAdapter:
  mcp_server.call_tool(tool_name, arguments)
      ↓
  FastMCP 内部分发（同进程）
      ↓
  拼接 result list 的 text 字段

MCPProxyToolNode:
  _tool_index[tool_name] → (server_name, server_config)
      ↓
  aiohttp POST (tools/call JSON-RPC)
      ↓
  解析远程响应的 content 列表
```

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
4. **统一接口**：三种接入策略对外暴露完全一致的 HTTP 端点（`/attp`, `/attp/ad.json`, `/attp/health`）

### 10.3 安全机制

| 安全能力 | 实现方式 |
|---------|---------|
| **DID 身份标识** | 每个工具节点持有唯一 DID |
| **内容签名** | 对 `RecordedHop.content_hash()` 使用私钥签名 |
| **双轮回溯** | 工具节点执行两次 BackMessage 发送（A2T 确认 + T2A 报告） |
| **hop_count 追踪** | T2A 消息递增 intra_count，保证消息序号连续性 |
| **私钥保护** | 私钥仅用于签名，签名失败不阻塞响应（降级而非拒绝） |

### 10.4 扩展性

添加新的工具接入策略只需：

1. 创建新类继承 `ToolNodeMixin`
2. 实现 `_execute_tool()` — 定义工具执行逻辑
3. 实现 `_build_ad()` — 定义 ad.json 内容
4. 在 `__init__` 末尾调用 `_init_common()` — 完成路由注册和属性初始化

即可获得完整的 ATTP 协议能力（签名、回传、ad.json 生成、HTTP 服务）。