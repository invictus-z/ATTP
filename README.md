# ATTP

[![PyPI](https://img.shields.io/badge/PyPI-attp-blue)](https://pypi.org/project/attp/)
[![NPM](https://img.shields.io/badge/NPM-invictus--z%40attp-red)](https://www.npmjs.com/package/invictus-z@attp)

## 概述

**Agents Traceability and Trust Protocol（ATTP）** 是一套面向开放互联环境下多 AI Agent 协作的可溯源通信与信任协议。通过结合密码学技术与大模型意图追踪，实现通信链路的不可否认复原，并精准追踪与发现试图进行诱导或传播恶意 Prompt 的源头节点，为智能体通信构筑互连互信的数字基座。

协议自底向上分为四层：

- **数据传输层**：负责节点间消息的可靠传递与路由，支持任意拓扑的协作模式
- **安全通信层**：在 [anp](https://github.com/agent-network-protocol/anp)（Agent Network Protocol）基础上扩展了分布式身份认证（DID），并实现端到端加密通信
- **消息追踪层**：通过哈希链接与双轮回溯确认机制，构建不可篡改的消息溯源链，确保通信链路的不可否认性
- **意图追踪层**：采用"十字锁定策略"对消息链和节点行为进行纵横双向评估，精准定位恶意 Prompt 的源头

本项目是 **ATTP 协议的完整实现**，提供开箱即用的四端部署架构：用户端、Agent 端、工具端和协议节点端。Agent 端通过渠道插件接入主流 Agent 框架（目前已支持 [nanobot](https://github.com/HKUDS/nanobot)，将来计划支持 [OpenClaw](https://github.com/openclaw/openclaw)、[Hermes](https://github.com/NousResearch/hermes-agent) 等）。

## 四端部署架构

v0.2.0-alpha 版本推出了完整的四端部署架构，各端开箱即用：

- **用户端**：基于 Vue + Electron 的跨平台应用，提供可视化拓扑图和时序图，直观复原智能体间通信链路，支持用户与Agent交互发布任务
- **Agent端**：预封装协议核心逻辑的智能体节点，通过渠道插件快速接入 Nanobot、OpenClaw 等主流框架，支持跨框架通信
- **工具端**：采用 MCP 桥接方式实现 ATTP 工具调用，支持原生 ATTP 工具开发和现有 MCP 服务转换
- **协议节点端**：运行四步验证管线（身份验证、签名验证、Nonce 匹配、行为记录）的核心协议枢纽

目前协议已在多代理协同场景下成功复原了通信链路，验证了整体架构的可靠性。基于 Ed25519 与 SHA-256 构建了不可篡改的溯源网络，开发了审计大模型引擎对上下文及历史行为进行评估，并封装了适配主流 Agent 框架的通道插件与 SDK。

## 快速启动

### 准备工作

**安装**

通过包管理器安装：

```bash
# Python 包
pip install attp

# Node.js 包  
npm install invictus-z@attp
```

  或从源码启动：

  ```bash
  git clone https://github.com/invictus-z/ATTP.git
  cd ATTP
  uv venv

  # 安装 Python 依赖（开发模式）
  uv pip install -e .

  # 安装用户端依赖
  cd user && npm install
  ```

**生成 DID 文档与密钥**

本项目基于 [anp](https://github.com/agent-network-protocol/anp) 实现分布式身份认证，启动前需要为每个节点生成 DID 文档及密钥对。项目提供了 `scripts/did_creator.py` 脚本，可批量生成：

```bash
# 为多个节点批量生成（输出到 ./did_output）
python scripts/did_creator.py --hostname did-server.test --names userA userB userC

# 指定输出目录（如与 nanobot 配置对齐）
python scripts/did_creator.py --hostname did-server.test --names my-agent --output-dir ~/.attp/agent/nanobot/did
```

每个节点会生成独立目录，包含：

| 文件 | 说明 |
|------|------|
| `did.json` | DID 文档 |
| `key-1_private.pem` / `key-1_public.pem` | Ed25519 密钥对 — 用于 DID 认证 |
| `key-2_private.pem` / `key-2_public.pem` | secp256r1 密钥对 — 用于 E2EE 消息签名 |
| `key-3_private.pem` / `key-3_public.pem` | X25519 密钥对 — 用于 E2EE 密钥协商 |

  > 生成后还需将 DID 文档部署至对应可访问的 HTTP 端点，供群组中的其他节点验证身份。

### 用户端

  用户端提供可视化界面，支持拓扑图和时序图展示智能体通信链路（数据来自协议节点API），支持用户与Agent交互发布任务。

 ```bash
  cd user
  npm install

  # Electron 应用开发模式
  npm run electron:dev

  # 生产构建
  npm run electron:build
 ```

  **首次配置**：首次启动后，需要通过界面配置用户DID：

  1. 启动用户端后，进入 **User Config** 页面
  2. 填写以下信息：
     - **User DID**：用户节点的分布式身份标识（如 `did:wba:hostname:user`）
     - **DID Document Path**：DID文档路径（如 `~/.attp/user/did/did.json`）
     - **Private Key Path**：私钥路径（如 `~/.attp/user/did/key-1_private.pem`）
  3. 点击 **Save User Config** 保存配置（配置保存至 `~/.attp/user/config.json`）

### Agent端

  Agent端通过渠道插件接入主流框架，目前仅支持 Nanobot。

  **配置文件**

  配置文件示例：参见 `examples/agent_config_demo.json`

  创建配置文件：
  ```bash
  # 复制示例配置
  cp examples/agent_config_demo.json ~/.attp/agent/nanobot/config.json

  # 根据实际情况修改配置项
  # - 修改 did 为你的节点 DID
  # - 修改路径为你的 DID 文档和密钥路径
  # - 修改 nodeAds 为其他节点的 ad.json 地址
  ```

  **启动步骤**

  ```bash
  # 1. 生成 nanobot 配置
  nanobot onboard

  # 2. 创建 ATTP 配置文件
  # 参照上面的示例创建 ~/.attp/agent/nanobot/config.json

  # 3. 启用 ATTP 渠道
  # 在 ~/.nanobot/config.json 中配置 ATTP 渠道：
  # {
  #   "channels": {
  #     "attp": {
  #       "enabled": true,
  #       "config_path": "~/.attp/agent/nanobot/config.json"
  #     }
  #   }
  # }

  # 4. 检查插件与启动
  nanobot plugins list   # 确认 attp 渠道插件已加载
  nanobot gateway        # 通过 nanobot 一键启动所有服务
  ```

### 工具端

  **工具客户端（MCPToolBridge）**

  工具客户端随 Agent 端渠道插件一起启动，无需单独配置或启动。

  在 `~/.attp/agent/nanobot/config.json` 中配置工具客户端：

  ```json
  {
    "tool": {
      "host": "127.0.0.1",
      "port": 8002,
      "tool_node_ads": [
        "http://tool-node:9000/ad.json"
      ]
    }
  }
  ```

  启动 Agent 端后，工具客户端会自动在 `http://127.0.0.1:8002` 提供 MCP SSE 服务。

  **工具服务端开发**

  SDK 提供三种工具开发方式：

  **方式一：原生 ATTP 工具**

  ```python
  from attp.sdk.tools.tool_node import ATTPToolNode

  # 创建工具节点
  tool = ATTPToolNode(
      name="my-tool",
      description="My ATTP Tool",
      host="0.0.0.0",
      port=9000,
      attp_prefix="/attp",
      private_key_path="~/.attp/tools/my-tool/did/key-1_private.pem"
  )

  # 注册工具
  @tool.tool()
  async def my_function(param1: str, param2: int) -> str:
      """Tool description"""
      return f"Result: {param1} - {param2}"

  # 启动工具
  await tool.start()
  ```

  **方式二：MCP 服务包装**

  ```python
  from attp.sdk.tools.mcp_adapter import MCPToATTPAdapter
  from mcp.server.fastmcp import FastMCP

  # 创建 FastMCP 实例
  mcp = FastMCP("my-mcp-tool")

  @mcp.tool()
  async def existing_tool(x: int) -> int:
      return x * 2

  # 包装为 ATTP 工具节点
  adapter = MCPToATTPAdapter(
      mcp_server=mcp,
      name="wrapped-mcp-tool",
      description="Wrapped MCP tool",
      host="0.0.0.0",
      port=9001,
      private_key_path="~/.attp/tools/wrapped/did/key-1_private.pem"
  )

  await adapter.start()
  ```

  **方式三：MCP 代理模式**

  ```python
  from attp.sdk.tools.mcp_proxy import MCPProxyToolNode

  # 代理远程 MCP 服务（支持多个MCP服务）
  proxy = MCPProxyToolNode(
      did="did:wba:proxy.local:my-proxy",
      name="my-proxy",
      description="Proxy for remote MCP services",
      config={
          "mcpServers": {
              "web-reader": {
                  "type": "streamableHttp",
                  "url": "https://open.bigmodel.cn/api/mcp/web_reader/mcp",
                  "headers": {"Authorization": "Bearer xxx"}
              },
              "code-interpreter": {
                  "type": "streamableHttp",
                  "url": "http://remote-server:8000/sse"
              }
          }
      },
      host="0.0.0.0",
      port=9002,
      private_key_path="~/.attp/tools/proxy/did/key-1_private.pem"
  )

  await proxy.start()
  ```

  工具启动后会自动生成 `ad.json` 并暴露 ATTP 端点，Agent 可通过 `tool_node_ads` 中的 URL 自动发现工具。

  ### 协议节点端

  协议节点负责处理回传消息和上层分析（如恶意节点检测）。

  **配置文件**

  配置文件示例：参见 `examples/protocol_node_config_demo.json`

  创建配置文件：
  ```bash
  # 复制示例配置
  cp examples/protocol_node_config_demo.json ~/.attp/protocol_node/config.json

  # 根据实际情况修改配置项
  # - 修改 host 和 port 为实际监听地址
  # - 如需启用分析，配置 analysis 相关参数
  ```

  **主要配置项说明**

  | 配置项 | 说明 |
  |--------|------|
  | `did` | 本节点的分布式身份标识（DID） |
  | `didDocPath` | DID 文档路径 |
  | `privateKeyPath` | 本节点私钥路径 |
  | `publicKeyPath` | 本节点公钥路径 |
  | `web.host` | 协议节点监听地址 |
  | `web.port` | 协议节点监听端口（默认 `8000`） |
  | `data_dir` | 数据存储目录 |
  | `db_path` | 数据库文件名（相对 data_dir） |
  | `analysis.enabled` | 是否启用语义意图追踪 |
  | `analysis.api_key` | 分析 API Key |
  | `analysis.base_url` | 分析 API 基础 URL |
  | `analysis.model` | 分析模型名称 |
  | `analysis.report_batch_size` | 批处理报告大小 |

  **启动协议节点**

  ```bash
  # 使用默认配置文件
  attp protocol_node start

  # 指定配置文件
  attp protocol_node start --config ~/.attp/protocol_node/config.json

  # 生成默认配置文件
  attp protocol_node init-config --output ~/.attp/protocol_node/config.json
  ```

  协议节点也可在 Agent 端配置中启用，随 Agent 端一起启动（参见 Agent 端配置示例中的 `protocol_node.enabled`）。

## 架构

### 四端协作架构

```
┌─────────────┐     ┌─────────────────────────────────────────────┐     ┌─────────────┐
│             │     │                Agent 端                      │     │             │
│   用户端    │────▶│  ┌──────────┐  ┌──────────┐  ┌───────────┐  │────▶│   工具端    │
│  (Vue +     │     │  │ Web App  │  │  Agent   │  │ ATTP Tool │  │     │  (MCP 桥接  │
│  Electron)  │     │  │ (:8001)  │  │(nanobot) │  │ (:8002)   │  │     │   / SDK)   │
│             │◀────│  └──────────┘  └──────────┘  └───────────┘  │◀────│             │
└─────────────┘     └──────────────────┬──────────────────────────┘     └─────────────┘
                                       │
                                       ▼
                            ┌─────────────────────┐
                            │    协议节点端         │
                            │  ┌───────────────┐  │
                            │  │ ATTP Server   │  │
                            │  │   (:8000)     │  │
                            │  ├───────────────┤  │
                            │  │ 验证管线      │  │
                            │  │ · 身份验证    │  │
                            │  │ · 签名验证    │  │
                            │  │ · Nonce 匹配  │  │
                            │  │ · 行为记录    │  │
                            │  └───────────────┘  │
                            └─────────────────────┘
```

  ### 消息传递与回溯确认

  每次节点间通信都会经过**双轮回溯确认**，确保通信链路的不可否认性。该机制适用于：

  - Agent ↔ Agent 通信
  - Agent ↔ Tool 通信
  - Agent ↔ User 通信

  **通信流程示例（Agent A → Agent B）：**

  ```mermaid
  sequenceDiagram
      participant A as Agent A
      participant B as Agent B
      participant P as 协议节点

      A->>B: ① NodeMessage（A签名内容）
      B->>P: ② BackMessage Phase 1（B签名身份 + 携带A签名内容）
      Note over P: Branch A：暂存为 PendingMessage
      A->>P: ③ BackMessage Phase 2（A签名身份 + 发送副本）
      Note over P: Branch B：Nonce 匹配 → 内容一致性验证 → 行为记录保存
  ```

  **阶段说明：**

  | 阶段 | 方向 | 说明 |
  |------|------|------|
  | ① A → B | 节点间转发 | A 构造 NodeMessage，签名内容完整性，发送至 B |
  | ② B → 协议节点 | 回传确认 | B 构造 BackMessage，签名确认身份，携带 A 的签名内容原样回传 |
  | ③ A → 协议节点 | 回传确认 | A 构造 BackMessage，签名确认身份，发送与 B 一致的内容副本 |
  | 匹配验证 | 协议节点内 | 通过 Nonce 匹配 Phase 1 和 Phase 2，验证双方内容一致性，记录行为 |

  > 双回传机制确保：发送方无法否认发送过该消息，接收方无法否认接收过该消息，协议节点可独立验证通信真实性。

## 功能详情

### 安全功能

#### DID 身份认证

在 [anp](https://github.com/agent-network-protocol/anp)（Agent Network Protocol）基础上进行了分布式身份认证扩展，基于 did:wba 标准实现去中心化身份标识。系统采用多密钥对机制支持不同安全需求，并扩展了身份验证和消息签名功能，为 ATTP 协议提供可靠的身份基础。

#### 消息追踪

通过协议节点（溯源节点）追踪消息传递，消息在传输过程中会被签名和记录并进行双向比对，确保通信链路的完整性和不可否认性。系统可以精确追踪每条消息的发送者、接收者、传输路径和时间戳，为后续的审计和责任追溯提供可靠依据。

#### 意图追踪

采用"十字锁定策略"进行综合评估：
- **纵向评估**：沿着消息链追踪每条消息的传播路径，分析消息内容在传递过程中的变化，识别可能的恶意注入或篡改
- **横向评估**：对参与通信的各个 Agent 节点进行行为分析，建立节点信誉模型，识别异常行为模式和潜在恶意节点

通过双向评估机制，系统能够精准定位传播恶意 Prompt 的源头节点，为智能体通信提供安全保障。

### 应用功能

#### 多 Agent 群组通信（待实现）

通过 `nodeAds` 配置群组成员，Agent 间可自由选择通信对象，支持任意拓扑的协作模式（链式调用、扇出、直接回复等）。启动时通过 ad.json 自动发现远程 Agent 并建立连接缓存，未就绪节点进入失败队列。后台心跳机制周期性对已连接 Agent 发起健康检查，连续失败超限自动驱逐并回退至重连队列，实现节点恢复后的无缝接入。以 `chat_id` 为键维护会话生命周期，跨跳持久化溯源路径与上下文元数据，确保多轮协作中消息关联不丢失。

#### 用户交互界面

- **对话交互**：支持与 Agent 进行实时对话，发布任务和查询状态
- **可视化拓扑**：以拓扑图形式展示智能体间的通信关系和连接状态
- **时序图展示**：通过时序图直观复原完整的消息传递链路
- **配置热重载**：支持 Agent 配置的热重载，无需重启即可应用配置变更
- **跨平台支持**：基于 Electron 框架，支持 Windows、macOS、Linux 等多个平台

#### ATTP 工具

ATTP 支持三种工具开发方式（详见"工具端"章节）：
  - **原生 ATTP 工具**：使用 SDK 开发原生 ATTP 工具，充分利用协议特性
  - **MCP 服务包装**：包装现有 MCP 服务为 ATTP 工具节点
  - **MCP 代理模式**：代理远程 MCP 服务（支持多服务），无需修改源代码

  工具启动后自动发布广告（ad.json），Agent 可自动发现和调用。

## 更新日志

### v0.2.0-alpha
重大架构升级：推出完整的四端架构（用户端、Agent端、工具端、协议节点端），支持 PyPI 和 NPM 包管理器发布。

### v0.1.0-alpha
初始版本发布：实现 ATTP 核心协议框架，包括 DID 身份认证、消息追踪、Nanobot 集成和基础可视化功能。

