# ATTP

[![官网](https://img.shields.io/badge/官网-attp--diting.cn-brightgreen)](https://attp-diting.cn/)
[![PyPI](https://img.shields.io/badge/PyPI-attp-blue)](https://pypi.org/project/attp/)
[![NPM](https://img.shields.io/badge/NPM-%40invictus--z%2Fattp-red)](https://www.npmjs.com/package/@invictus-z/attp)

## 目录

- [概述](#概述)
- [四端部署架构](#四端部署架构)
- [快速启动](#快速启动)
- [架构](#架构)
- [功能详情](#功能详情)
- [更新日志](#更新日志)

## 概述

**ATTP（Agent Trust and Traceability Protocol，智能体信任与溯源协议）** 是一套面向开放互联环境下多 AI Agent 协作的可溯源通信与信任协议。通过结合密码学技术与大模型意图追踪，实现通信链路的不可否认复原，并精准追踪与发现试图进行诱导或传播恶意 Prompt 的源头节点，为智能体通信构筑互连互信的数字基座。

协议自底向上分为四层：

- **身份管理和加密通信层**：基于 [anp](https://github.com/agent-network-protocol/anp)（Agent Network Protocol）与 W3C DID（did:wba）构建去中心化身份体系，提供身份解析、密钥管理与签名验证，并通过双签名机制绑定身份与消息内容（端到端加密通信规划于后续版本）
- **会话层**：定义节点类型、行为类型（U2A/A2A/A2T/T2A/A2U）与消息格式（单跳记录、转发消息、回传消息），承载节点间的业务通信与路由
- **消息固化层**：采用"先回传、后转发"的双回传时序，由协议节点执行七步交叉验证，将通信行为转化为不可篡改、不可抵赖的溯源记录
- **意图追踪层**：采用"十字锁定"协调架构对消息链逐跳进行语义评分（纵轴）并跨会话累积确认（横轴），精准定位传播恶意 Prompt 的源头节点

本项目（配套系统代号 **「谛听」**）是 **ATTP 协议的完整实现**，提供开箱即用的四端部署架构：用户端、Agent 端、工具端和协议节点端。Agent 端通过渠道插件接入主流 Agent 框架，目前已支持 [nanobot](https://github.com/HKUDS/nanobot) 与 [openclaw](https://github.com/openclaw/openclaw)，将来计划支持 [Hermes](https://github.com/NousResearch/hermes-agent) 等。

## 四端部署架构

ATTP 提供完整的四端部署架构，各端开箱即用：

- **用户端**：基于 Vue + Electron 的跨平台应用，提供可视化拓扑图和时序图，直观复原智能体间通信链路，支持用户与Agent交互发布任务
- **Agent端**：预封装协议核心逻辑的智能体节点，通过渠道插件快速接入 nanobot、openclaw 等主流框架，支持跨框架通信
- **工具端**：采用 MCP 桥接方式实现 ATTP 工具调用，支持原生 ATTP 工具开发和现有 MCP 服务转换
- **协议节点端**：运行回溯验证管线（字段校验 → DID 解析 → Nonce 双回传匹配 → 恶意节点判定 → 内容一致性校验 → 行为类型与 hop_count 推断 → 可信名单更新）的核心协议枢纽

目前协议已在多代理协同场景下成功复原了通信链路，验证了整体架构的可靠性。基于 Ed25519 与 SHA-256 构建了不可篡改的溯源网络，开发了审计大模型引擎对上下文及历史行为进行评估，并封装了适配主流 Agent 框架的通道插件与 SDK。

## 快速启动

### 准备工作

**安装**

通过包管理器安装：

```bash
# Python 包
pip install attp

# Node.js 包  
npm install @invictus-z/attp
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
| `key-2_private.pem` / `key-2_public.pem` | secp256r1 密钥对 — 预留（v0.4.0 端到端加密消息签名） |
| `key-3_private.pem` / `key-3_public.pem` | X25519 密钥对 — 预留（v0.4.0 端到端加密密钥协商） |

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

  Agent端通过渠道插件接入主流框架，目前支持 **nanobot** 与 **openclaw** 两种渠道。

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

  **openclaw 渠道**

  openclaw 渠道以原生 TypeScript 进程内插件形式接入，启动后在进程内拉起三个独立端口：WebUI `:19001`、Agent Server `:19000`、MCP 工具 `:19002`（相对 nanobot 的 8001/8000/8002 偏移，二者可共存）。

  ```bash
  # 1. 构建 TS 核心库与 openclaw 插件
  cd typescript && npm install && npm run build
  cd attp/channels/openclaw && npx tsup

  # 2. 以本地链接方式安装插件
  openclaw plugins install --link ./typescript/attp/channels/openclaw

  # 3. 配置 ATTP 渠道与 MCP 工具服务
  #    参见 examples/.openclaw/config.json（plugins / channels / mcp.servers）
  #    与   examples/.attp/agent/openclaw/config.json（ATTP Agent 配置，三端口）

  # 4. 重启网关并探测渠道
  openclaw gateway restart
  openclaw channels status --probe
  ```

  > openclaw 渠道按方向分发进站消息：浏览器 WebSocket 的 U2A 消息驱动 Agent 推理并广播回复；远端 Agent 的 A2A `receive_message` 仅记录输出，回复需通过 MCP `send_message` 主动发起。详见 [docs/attp-openclaw.md](docs/attp-openclaw.md)。

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
  | `web.host` | 协议节点监听地址（默认 `0.0.0.0`） |
  | `web.port` | 协议节点监听端口（默认 `9000`） |
  | `storage.data_dir` | 数据存储目录（默认 `~/.attp/protocol_node`） |
  | `storage.db_path` | 数据库文件名（相对 `data_dir`，默认 `attp.db`） |
  | `analysis.enabled` | 是否启用语义意图追踪（默认 `false`） |
  | `analysis.api_key` / `base_url` / `model` | 审计大模型 API Key / 基础 URL / 模型名 |
  | `analysis.horizontal_enabled` | 是否启用横轴跨会话确认（默认 `true`） |
  | `analysis.r_t` | 单点阈值：单跳评分 `s_i > r_t`（默认 `7.5`）立即告警 |
  | `analysis.r_s` | 累积阈值：`F = Σ s_i² > r_s`（默认 `25.0`）触发横轴确认 |
  | `analysis.rho` | 横轴高危兜底阈值（默认 `8.0`） |
  | `analysis.alpha` | 横轴确认候选会话上限（默认 `10`） |
  | `analysis.concurrency` | 逐跳打分并发数（默认 `8`） |

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
                            │  │ 协议节点 HTTP │  │
                            │  │   (:9000)     │  │
                            │  ├───────────────┤  │
                            │  │ 回溯验证管线  │  │
                            │  │ · 字段校验    │  │
                            │  │ · DID 解析    │  │
                            │  │ · Nonce 匹配  │  │
                            │  │ · 恶意判定    │  │
                            │  │ · 行为记录    │  │
                            │  └───────────────┘  │
                            └─────────────────────┘
```

> 端口说明：nanobot 渠道使用 WebUI `:8001` / Agent Server `:8000` / MCP 工具 `:8002`；openclaw 渠道对应 `:19001` / `:19000` / `:19002`（二者可共存）。协议节点固定监听 `:9000`，接收各端的双轮回传消息。

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

v0.3.0 将意图追踪重构为**逐跳、有状态**的语义识别模型（"十字锁定策略"），由协议节点的审计大模型对每条动作跳（A2A/A2T/T2A/A2U）实时评分：

- **意图流（纵轴上下文）**：会话首条及后续每条 U2A 均抽取一条意图增量（目标 / 约束 / 禁止项）追加为只增意图流；仅会话发起者 DID 的 U2A 可修订意图，防止被劫持 Agent 注入伪造意图。U2A 只抽意图不打分。
- **逐跳语义评分（纵轴）**：每条动作跳在 4 个正交维度上打分（0–10，0.5 步进）——意图对齐、能力域/越权、注入与操纵、外泄与篡改；聚合后得到单跳分 `s_i` 与 5 档严重度（none/low/medium/high/critical），严重度与最终判决由代码推导（critical→malicious、high→suspicious）。单跳 `s_i > R_T(7.5)` 立即告警。
- **跨会话确认（横轴）**：按发送者 DID 累加 `F = Σ s_i²`，超过累积阈值 `R_S(25.0)` 即触发横轴确认；候选会话按 `W(σ)=Σ s_i²` 排序取 `α` 个，并含高危兜底（任一跳 `≥ ρ(8.0)` 无条件纳入）。

逐跳评分异步进行（不阻塞 `/record` 写入），状态持久化至 SQLite，可中断恢复。该机制能精准定位传播恶意 Prompt 的源头节点，并对慢速投毒、跨会话分散攻击等隐蔽行为有效。

### 应用功能

#### 多 Agent 群组通信

通过 `nodeAds` 配置群组成员，Agent 间可自由选择通信对象，支持任意拓扑的协作模式（链式调用、扇出、直接回复等）。启动时通过 ad.json 自动发现远程 Agent 并建立连接缓存，未就绪节点进入失败队列。后台心跳机制周期性对已连接 Agent 发起健康检查，连续失败超限自动驱逐并回退至重连队列，实现节点恢复后的无缝接入。以 `chat_id` 为键维护会话生命周期，跨跳持久化溯源路径与上下文元数据，确保多轮协作中消息关联不丢失。

#### 用户交互界面

- **对话交互**：支持与 Agent 进行实时对话，发布任务和查询状态
- **可视化拓扑**：以拓扑图形式展示智能体间的通信关系和连接状态
- **时序图展示**：通过时序图直观复原完整的消息传递链路
- **溯源与分析**：展示行为链与恶意节点档案，支持触发意图追踪分析并实时查看逐跳评分与横轴确认报告
- **配置热重载**：支持 Agent 配置的热重载，无需重启即可应用配置变更
- **跨平台支持**：基于 Electron 框架，支持 Windows、macOS、Linux 等多个平台

#### ATTP 工具

ATTP 支持三种工具开发方式（详见"工具端"章节）：
  - **原生 ATTP 工具**：使用 SDK 开发原生 ATTP 工具，充分利用协议特性
  - **MCP 服务包装**：包装现有 MCP 服务为 ATTP 工具节点
  - **MCP 代理模式**：代理远程 MCP 服务（支持多服务），无需修改源代码

  工具启动后自动发布广告（ad.json），Agent 可自动发现和调用。

## 更新日志

### v0.4.0（开发中）
重构统一抽象通信层，强化分布式身份认证与权限管理。

### v0.3.0
意图追踪层框架升级：判定条件，横纵轴触发条件等多项优化。

### v0.2.2
TypeScript 核心库对等实现（与 Python 端序列化兼容）；新增 openclaw 渠道插件；用户端支持 SSE 实时推送。

### v0.2.1-demo
基于 v0.2.1，加入可自由切换的演示功能。

### v0.2.1
实现"十字锁定"（cross-lock）纵横双向意图追踪。

### v0.2.0
重大架构升级：推出完整四端部署架构（用户端、Agent 端、工具端、协议节点端），落地双回传消息固化与验证管线；发布至 PyPI 与 NPM。

### v0.1.0
初始版本：实现 ATTP 核心协议框架，包含 DID 身份认证、消息溯源、nanobot 集成与基础可视化界面。

