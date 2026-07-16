# ATTP × openclaw：原生 TS 进程内 · 三端口独立架构

ATTP 作为 **openclaw 的原生进程内插件**运行——单 Node 进程，无 Python 子进程——但 **保留三个独立端口**，延续 ATTP「WebUI / Agent Server / 工具节点」的三面身份。这不是「把 ATTP 折叠成 openclaw 网关上的几条路由」（早期方案的尝试已废弃），而是让 ATTP 在 openclaw 进程内仍以**自己的网络面**对外：同一份 host-agnostic 的三端口引导可以被 openclaw / nanobot / 独立进程任意一种宿主复用。openclaw 负责「跑 agent turn」（这是「原生插件」的耦合点），ATTP 的三个面在收到消息后进程内直推 openclaw 的 `inbound.run`。

ProtocolNode 仍是独立的 Python 服务（`:9000`），所有宿主通过 HTTP `/record` 共用——不转译。

> 本文取代历史上的两类旧方案：(1) subprocess + loopback webhook + `/openclaw/reply`；(2) 把 WebUI/A2A 折叠到 openclaw 网关同端口路由、工具走 `registerTool` 的 gateway-routes 设计。旧代码（[`integrations/openclaw-plugin/`](../integrations/openclaw-plugin/)、[`python/attp/channels/openclaw/`](../python/attp/channels/openclaw/)）已废弃，待本方案实机验证后删除（见 [附录](#附录实机验证清单)）。

配置模板：[`examples/.openclaw/config.json`](../examples/.openclaw/config.json) + [`examples/.attp/agent/openclaw/config.json`](../examples/.attp/agent/openclaw/config.json)。

---

## 一、设计

### 1.1 目标

- **三端口独立性**：ATTP 在任意宿主下都保留三个独立网络端口（WebUI / Agent Server / MCP 工具），使其身份与可用性**不绑定到某一个宿主**——openclaw、nanobot、独立进程三种部署形态共用同一份 host-agnostic 引导（[`typescript/attp/app/attp-server.ts`](../typescript/attp/app/attp-server.ts) + [`typescript/attp/app/mcp-node.ts`](../typescript/attp/app/mcp-node.ts)）。
- **进程内直推，无 HTTP 桥**：入站（U2A / A2A）三端口 handler 直接调用 openclaw 的 `inbound.run`；出站（A2U / A2A）进程内直推 WS hub / A2A 客户端。无 loopback webhook、无 `/openclaw/reply` 回灌端口、无跨进程 spawn。
- **openclaw 跑 agent turn**：ATTP 三端口只负责「收/发消息 + 协议（DID-wba / NodeMessage / MCP）」，agent 推理由 openclaw 的 `channelRuntime.inbound.run` 完成——这是「原生插件」的耦合点。
- **跨框架线协议一致**：与现有 Python ATTP（nanobot 渠道、独立运行）经 A2A 互通并完成回传，NodeMessage / BackMessage / DID-wba 签名逐字节一致（共享测试向量锁定）。

### 1.2 三个端口 vs openclaw 网关

| 端口 | 归属 | 协议/职责 | 谁连它 |
|---|---|---|---|
| **WebUI `:19001`** | ATTP | NodeMessage WebSocket（+ 可选静态文件）；ATTP user 端的 U2A/A2U 通道 | ATTP user 端（浏览器/SDK） |
| **Agent Server `:19000`** | ATTP | DID-wba（RFC 9421）+ JSON-RPC `receive_message`（A2A 入站）；**提供 `ad.json` + `openrpc.json`** 供对端发现 | 远端 agent（Python nanobot 等） |
| **MCP Tools `:19002`** | ATTP | 独立 MCP 节点（SSE），暴露 `send_message` 工具 | openclaw agent（经 `mcp.servers.attp-tools`） |
| gateway `:18789` | **openclaw** | openclaw 自有网关面（不变，与 ATTP 三端口无关） | openclaw 的客户端 |

关键：ATTP 的三个端口**不是 openclaw 网关的路由**，而是 ATTP 自己监听的独立 HTTP server。openclaw 网关端口（`:18789`）是 openclaw 自己的表面，不在本文档的改动范围内。

### 1.3 架构总览

```
┌──────────────── openclaw 进程（单 Node · 无子进程）────────────────┐
│                                                                    │
│  openclaw 网关 :18789  (openclaw 自有表面，不变)                    │
│                                                                    │
│  ┌──── ATTP 三端口（host-agnostic 引导，进程内独立监听）────────┐  │
│  │                                                              │  │
│  │  WebUI :19001          Agent Server :19000      MCP :19002   │  │
│  │  NodeMessage WS         DID-wba A2A 收端        SSE 工具节点 │  │
│  │  (+ 可选静态)           ad.json / openrpc.json  send_message │  │
│  │       │                      │                      │       │  │
│  │       │ U2A                  │ A2A-in               │ 工具  │  │
│  │       ▼                      ▼                      ▼       │  │
│  │   onInbound ──► dispatchAttpInbound ──► openclaw inbound.run │  │
│  │                                  （openclaw 跑 agent turn）  │  │
│  │       ▲ reply                                               │  │
│  │       │ A2U: deliverOutbound("attp:<sid>")                  │  │
│  │       │   → 签名 NodeMessage → hub.broadcast(:19001 WS)     │  │
│  │       │ A2A-out: deliverOutbound("did:...")                 │  │
│  │       │   → discoverAgent(peer ad.json) → DID-wba POST      │  │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
        │ fetch POST /record                │ fetch POST + DID-wba 头 (NodeMessage)
        ▼ (BackMessage)                     ▼
  ┌───────────────┐                  ┌─────────────────────┐
  │ ProtocolNode  │ Python·独立(9000) │ 远端 ATTP Agent       │
  │ SQLite/SSE/LLM│ ◄─ 所有宿主共用   │ nanobot / 独立 / ...  │
  └───────────────┘   不转译          └─────────────────────┘
```

要点：
- 三端口各自 `createServer().listen(port)`，互不依赖；hub（WS 连接聚合）同时挂在 attp-server handle 与 runtime 上，供出站 A2U `broadcast` 用。
- 入站三端口 handler 收到消息后回调 `onInbound` → [`dispatchAttpInbound`](../typescript/attp/channels/openclaw/src/inbound.ts) → `channelRuntime.inbound.run`（openclaw 跑 turn）。
- 出站由 [`deliverOutbound`](../typescript/attp/channels/openclaw/src/outbound.ts) 按前缀分流：`attp:<sid>` → 签名 NodeMessage + `hub.broadcast`；`did:...` → `discoverAgent` + `sendMessage`。
- ProtocolNode 是外部 Python 服务，远端 Agent 走 DID-wba HTTP——与 Python Agent 走同一套线协议。

### 1.4 两层切分：宿主无关 SDK + openclaw 胶水

| 层 | 位置 | 职责 |
|---|---|---|
| **协议核心 + Agent 应用层（宿主无关）** | [`typescript/attp/core/`](../typescript/attp/core/) + [`typescript/attp/app/`](../typescript/attp/app/) | 与 Python `attp` 包对行的 TS SDK：签名、DID 解析、溯源链、回传、A2A client/server、WS hub、MCP 工具节点、三端口引导、配置。**宿主无关**——同样可被 nanobot 或独立宿主复用。跨语言互通由共享测试向量（同私钥 → 同签名 / 互验）锁定。 |
| **openclaw 宿主胶水** | [`typescript/attp/channels/openclaw/`](../typescript/attp/channels/openclaw/) | 把上面的 SDK 接到 openclaw 的 `defineChannelPluginEntry` 生命周期：`setRuntime` 捕获 `channelRuntime`、`startAccount` 拉起三端口服务并阻塞至 `abortSignal`、入站 dispatch 到 `inbound.run`、出站按前缀路由。 |

**ProtocolNode 保持 Python 不转译**：它是网络共享的篡改检测基础设施（SQLite + SSE + LLM 篡改检测 + 双重回传对账），每个节点的篡改检测逻辑必须全网一致，单一实现更安全。所有宿主（TS in-process / Python nanobot / 独立 Python）通过 HTTP `/record` 共用同一节点。

### 1.5 数据流

**U2A（用户 → Agent，进程内）**
ATTP user 端连 `ws://<host>:19001/ws` → WS handler 经 [`parseInboundNodeMessage`](../typescript/attp/app/web.ts) 解析 NodeMessage（取 `session_id` 并 `hub.register`）→ best-effort Phase-1 回传 → `onInbound({direction:"U2A"})` → `dispatchAttpInbound` → `channelRuntime.inbound.run`（openclaw 跑 turn）。

**A2U（Agent → 用户，进程内）**
turn 回执：`resolveTurn().delivery.deliver(payload)` → [`deliverOutbound("attp:<sid>", text)`](../typescript/attp/channels/openclaw/src/outbound.ts) → 构造签名后的 A2U `NodeMessage`（经 `nodeMessageFrame` 序列化）→ `hub.broadcast(sid, frame)`，推给订阅该 session 的全部 :19001 WS。best-effort Phase-1 回传。

**A2A 入站（远端 Agent → 我们，进程内）**
远端按 DID-wba 协议 POST 到我方 Agent Server 的 `/receive` → [`attp-server.ts`](../typescript/attp/app/attp-server.ts) 的 `parseInboundRequest` + `verifyInbound` 验签（DID-wba / RFC 9421，`Content-Digest` RFC 9530）→ best-effort Phase-1 回传 → `onInbound({direction:"A2A"})` → `dispatchAttpInbound`。

**A2A 出站（我们 → 远端 Agent，进程内）**
- **回复 A2A 入站 turn**：`delivery.deliver` 的 `to` 为远端 DID（入站时由 `dispatchAttpInbound` 按 `direction:"A2A"` 设定 `reply.to = sender_did`）→ `deliverOutbound("did:...", text)` → `didToAdUrl(did)` best-effort 推导 → `discoverAgent(adUrl)` 拉 ad.json + OpenRPC 取 rpcUrl → `sendMessage`（现场 rediscover，不依赖入站缓存）。
- **主动外呼**：openclaw agent 经 MCP（`mcp.servers.attp-tools` → :19002/sse）调用 `send_message({ target_did, content, ad_url? })` 工具 → [`executeSendMessage`](../typescript/attp/app/tools.ts) → `discoverAgent` + `sendMessage`（构造 NodeMessage + DID-wba 签名 + JSON-RPC POST）。

**回传（→ ProtocolNode，线协议不变）**
入站 / 出站的每一跳都由 [`core/message/back-sender.ts`](../typescript/attp/core/message/back-sender.ts) 的 `sendBackMessage` 做 Phase-1 回传：`fetch POST {protocol_url}/record`，payload 与 Python `core/message/back_sender.py` 逐字段一致。失败 best-effort 跳过（只记 warn），不阻断主流程。

### 1.6 组件文件

**协议核心** [`typescript/attp/core/`](../typescript/attp/core/)（宿主无关）
- `authentication/signatures.ts`：RSA-PSS / ECDSA（P-256/384/521、secp256k1）/ Ed25519 签名与验签，compact（`r‖s`）编码与 Python 互锁。
- `authentication/keys.ts`：PEM → CryptoKey / KeyObject 导入；JWK 导入。
- `authentication/did-resolver.ts`：`did:wba` / `did:web` HTTPS 解析、JWK / PEM 公钥提取、TTL 缓存。
- `provenance/chain.ts`：`ChainManager`——`append_hop` / `validate_hop` / `verify_back_propagation`。
- `message/back-sender.ts`：`sendBackMessage`（fetch POST `/record`）。
- `message/event.ts`：`NodeMessage` / `RecordedHop` 数据结构。
- `agent-tracer.ts`：`AgentTracer` 门面（KeyStore + ChainManager）。
- `sessions/`、`provenance/hashing.ts`：会话与哈希工具。

**Agent 应用层** [`typescript/attp/app/`](../typescript/attp/app/)（宿主无关）
- `config.ts`：`loadAgentConfig`——从 ATTP agent 配置（schema 不改）选取身份 / 协议 / **端口**（`webAppPort` / `agentServerPort` / `toolPort`）/ **`publicAgentUrl`** 字段。
- `did-wba.ts`：DID-wba HTTP Message Signatures（RFC 9421）生成与验签；`Content-Digest`（RFC 9530）。从 Python `http_signatures.py` 逐行翻译。
- `client.ts`：A2A 发送——`discoverAgent(adUrl)`（ad.json + OpenRPC → rpcUrl）、`sendMessage(...)`（NodeMessage + DID-wba 签名 + JSON-RPC POST）。
- `server.ts`：A2A 收端——`parseInboundRequest`（解析 JSON-RPC，含 `message_type` 参数）+ `verifyInbound`（DID-wba 验签）。
- `web.ts`：`WsHub`（`Map<sessionId, Set<ws>>`）+ `parseInboundNodeMessage` + `nodeMessageFrame`，宿主无关的连接聚合与帧解析/序列化。
- `tools.ts`：`executeSendMessage`（工具执行体，调 `client.discoverAgent` + `sendMessage`）。
- `attp-server.ts`：**三端口引导（其二）**——绑 WebUI 端口（WS + 可选静态）+ Agent Server 端口（ad.json / openrpc.json / POST `/receive`）。不 import 任何 channel 代码。
- `mcp-node.ts`：**三端口引导（其三）**——独立 MCP 节点（SSE），注册 `send_message` 工具。身份 lazy 读取（节点先于身份装载启动）。不 import 任何 channel 代码。

**openclaw 宿主胶水** [`typescript/attp/channels/openclaw/`](../typescript/attp/channels/openclaw/)
- `index.ts`：`defineChannelPluginEntry({ id:"attp", plugin, setRuntime, registerFull })`。`setRuntime(api.runtime)` 捕获 `channelRuntime`（外部插件必需）；`registerFull(api)` 只记下配置根（三端口改造后**不再在 gateway 上注册路由/工具**）。
- `openclaw.plugin.json`：顶层 `configSchema`（`enabled` / `config_path`）+ `channels:["attp"]`。
- `src/channel.ts`：`attpPlugin`（base + outbound + gateway）。`startAccount` 读配置 → 装身份 → 构造 `AgentTracer` + `WsHub` → `startAttpServer`（WebUI+AgentServer）+ `startMcpNode` → 阻塞至 `abortSignal`。
- `src/config.ts`：从 openclaw 配置的 `channels.attp` 段读 `enabled` / `config_path`，加载 ATTP agent 配置。
- `src/runtime.ts`：进程内单账户共享状态（`channelRuntime` / `cfg` / `agentConfig` / `hub` / `tracer` / `privateKey` / `didDocument` / `abortSignal`）。
- `src/inbound.ts`：`dispatchAttpInbound`——openclaw inbound 三件套（`resolveInboundRouteEnvelopeBuilderWithRuntime` + `buildContext` + `run`），`reply.to` 按方向（U2A→`attp:<sid>` / A2A→sender_did）分流。
- `src/outbound.ts`：`deliverOutbound`——`attp:<sid>` 构造签名 NodeMessage 推 WS hub；`did:...` 走 `discoverAgent` + `sendMessage`。
- `types/openclaw.d.ts`：本地类型 shim。

---

## 二、使用方式

### 2.1 前置

- **Node.js 18+**。
- **openclaw** 可运行（`openclaw --version`）。本机推荐用托管服务 `openclaw gateway start/stop/restart`（Windows 为 schtasks「OpenClaw Gateway」）；避免手动 `node .../openclaw.mjs gateway run` 长跑——它会与托管服务竞争端口并触发 gateway drain。
- **一个 ProtocolNode 实例**（Python，默认端口 9000）。所有宿主共用同一节点；TS agent 通过 HTTP `/record` 回传。本地无 ProtocolNode 时把 ATTP agent 配置的 `protocolNode.enabled` 设为 `false`（回传 best-effort 跳过，不影响 U2A/A2A 主体）。
- **一个 LLM provider**（openclaw 配置里的 `models.providers` + `agents.defaults.model`）。

### 2.2 构建 TS SDK

首次或源码变更后，先在 [`typescript/`](../typescript/) 下构建（npm 包根在此，不是仓库根）：

```bash
cd <ATTP_ROOT>/typescript
npm install
npm test              # vitest，116 用例（签名/DID-wba/Chain/DID 解析/回传/attp-server/mcp-node/outbound）
npm run build         # tsup 输出到 typescript/dist/
```

### 2.3 安装渠道插件（不改 openclaw 源码）

从「将要加载它的那个 openclaw」执行 `plugins install --link`，指向本仓库的 openclaw 渠道目录：

```bash
openclaw plugins install --link <ATTP_ROOT>/typescript/attp/channels/openclaw
openclaw plugins enable attp
openclaw gateway restart          # plugins.load.paths 属 Infrastructure，需重启
```

`--link` 不拷贝，改完 TS 代码 `npm run build` + `gateway restart` 即生效。

### 2.4 配置

#### (a) `~/.openclaw/openclaw.json`（在现有结构上合并；模板见 [`examples/.openclaw/config.json`](../examples/.openclaw/config.json)）

```jsonc
{
  "agents":   { "defaults": { "model": "${LLM_MODEL}" },
                "list": [ { "id": "main", "default": true } ] },
  "models":   { "providers": { "custom": { "baseUrl": "${LLM_BASE_URL}",
                                           "api": "openai-completions",
                                           "apiKey": "${LLM_API_KEY}" } } },
  "plugins":  { "entries": { "attp": { "enabled": true } },
                "load":   { "paths": [ "${ATTP_ROOT}/typescript/attp/channels/openclaw" ] } },
  "channels": { "attp": { "enabled": true,
                          "config_path": "~/.attp/agent/openclaw/config.json" } },
  "bindings": [ { "agentId": "main", "match": { "channel": "attp" } } ],
  "mcp":      { "servers": { "attp-tools": { "url": "http://127.0.0.1:19002/sse",
                                             "transport": "sse" } } },
  "gateway":  { "port": 18789, "bind": "loopback" }
}
```

要点：
- `channels.attp` 与 nanobot 完全同形（`enabled` + `config_path`）。ATTP 身份 / DID / 端口 / publicBaseUrl 都在 `config_path` 指向的 ATTP agent 配置里。
- **`mcp.servers.attp-tools`** 指向 ATTP 的 MCP 端口 `:19002/sse`（SSE 传输）。openclaw agent 经此消费 ATTP 的 `send_message` 工具。URL 主机换成 ATTP 实际可达地址（同机默认 `127.0.0.1`）。
- **没有在 gateway 上注册 ATTP 路由**：WebUI / WS / A2A 都在 ATTP 自己的三端口上，不在 gateway `:18789` 上。
- channel id `attp` 须三处一致：[`openclaw.plugin.json`](../typescript/attp/channels/openclaw/openclaw.plugin.json) 的 `channels`、入口 `defineChannelPluginEntry({id})`、`channels.attp` 键名、`bindings[].match.channel`。

#### (b) `~/.attp/agent/openclaw/config.json`（ATTP agent 配置；模板见 [`examples/.attp/agent/openclaw/config.json`](../examples/.attp/agent/openclaw/config.json)）

schema 与 nanobot profile 共享（[`python/attp/app/config/config.py`](../python/attp/app/config/config.py)），**不改 schema**。TS agent 经 [`app/config.ts`](../typescript/attp/app/config.ts) 的 `loadAgentConfig` 选取：

- **用（身份/协议）**：`did`、`attpClient.didDocPath` / `didKeyPath`、`protocolNode`（解析出 `protocol_url`）、`attpServer.name` / `description`。
- **用（三端口）**：`webApp.port`（默认 19001）、`attpServer.serverPort`（默认 19000）、`tool.port`（默认 19002）。
- **⚠️ 必须设置 `attpServer.publicBaseUrl`**：Agent Server 的**外部可达基址**（如 `https://agent.example.com:19000`），写进 `ad.json` / `openrpc.json`，让**远端** peer 能据此回调 `/receive`。缺省回退 `http://127.0.0.1:19000`——**仅本地可达，远端 peer 无法回调**。示例：

  ```jsonc
  "attpServer": {
    "name": "diting-agent-openclaw",
    "serverPort": 19000,
    "publicBaseUrl": "https://agent.example.com:19000"   // ← 生产必须设为远端可达 URL
  }
  ```

- DID 与密钥文件复用 [`examples/.attp/agent/openclaw/did/`](../examples/.attp/agent/openclaw/did/) 下的演示身份。

> **生产前必须**：为 openclaw-agent 配置独立 DID/密钥（不可与 nanobot-agent 复用同一身份，否则跨框架 A2A 身份混淆）；把 DID 文档（`did.json`）托管到对端可经 HTTPS 解析的地址。

### 2.5 运行与验证

```bash
openclaw gateway start                    # 或 restart
openclaw channels status                  # 期望 attp: running
openclaw plugins inspect attp --runtime --json
```

启动后三个端口各自监听：
- **WebUI** `http://<host>:19001/`（可选静态；`:19001/ws` 为 NodeMessage WS）。
- **Agent Server** `http://<host>:19000/ad.json`、`/openrpc.json`、`POST /receive`。
- **MCP 工具** `http://<host>:19002/sse`（openclaw agent 经 `mcp.servers.attp-tools` 接入）。

ATTP user 端连 `ws://<host>:19001/ws` 发 NodeMessage → 经 WS 进 `inbound.run` → agent turn → 回执由 `deliverOutbound` 构造签名 A2U NodeMessage 经 `hub.broadcast` 推回。

### 2.6 跨框架 A2A（Python nanobot ↔ openclaw-agent）

前提：双方各自独立 DID/密钥；DID 文档可被对端经 HTTPS 解析；**双方 `attpServer.publicBaseUrl` 都设为远端可达 URL**；共享可达的 ProtocolNode。

- **nanobot → openclaw（A2A-in）**：Python agent 经你 Agent Server 的 `ad.json` / `openrpc.json` 发现 `receive_message` 的 rpcUrl → 按 DID-wba 协议 POST 到你的 `:19000/receive`。验签通过后进 `inbound.run`，回复经 `deliverOutbound("did:...", text)` → `discoverAgent` + `sendMessage` 回发 Python。
- **openclaw → nanobot（A2A-out）**：openclaw agent 调用 MCP 工具 `send_message({ target_did, content, ad_url? })`（`ad_url` 缺省时由 `target_did` best-effort 推导为 `https://<host>/<path>/ad.json`）→ `discoverAgent` 拉 Python 端 ad.json/OpenRPC → `sendMessage`（DID-wba 签名 JSON-RPC POST）。
- **双方回传**：每一跳（发送前 / 收到后）都 POST `/record` 给共享 ProtocolNode，溯源链完整、跨语言一致。可在 ProtocolNode 的 `/api/behavior` 观察到。

### 2.7 排障

- **远端 peer 回调 `/receive` 失败 / ad.json 里 URL 不可达**：`attpServer.publicBaseUrl` 未设或仍是默认 `127.0.0.1`（仅本地可达）。把它设为远端可达的 URL（含正确 host + port），重启 gateway。
- **三端口对 peer 不可达**：`19000` / `19001` / `19002` 须对各自的连接方可达（防火墙 / 反向代理放行）。MCP `:19002` 须对 openclaw 可达；Agent Server `:19000` 须对远端 agent 可达；WebUI `:19001` 须对 ATTP user 端可达。
- **DID 不可 HTTPS 解析**（远端给你发 A2A 时验签失败 / 对端拿不到你的公钥）：演示 DID 仅为本地身份，生产需把 `did.json` 托管到 HTTPS。`did:wba` 的解析路径为 `https://<host>/<path>/did.json`。
- **DID-wba 验签失败**：检查密钥类型与编码——本实现支持 RSA-PSS、ECDSA（P-256/384/521、secp256k1）、Ed25519；签名编码为 compact（`r‖s`），与 Python 互锁（见 [`typescript/attp/app/did-wba.ts`](../typescript/attp/app/did-wba.ts) 头注释）。
- **gateway 反复 drain**：通常是手动 `node .../openclaw.mjs gateway run` 与托管服务抢端口——改用 `openclaw gateway start/stop/restart`；或 agent 的 LLM provider 限流导致 turn 失败，换 provider / model。
- **A2U 无回复**：查 gateway 日志是否有 `[attp]` 前缀日志；WS 连接是否真的进了 `WsHub`（`register`）；`routeSessionKey` 与 WS 携带的 `session_id` 是否对齐；`runtime.identity` 是否就绪（`privateKey` / `agentConfig.did`）。
- **`channelRuntime not captured`**：外部插件未走 `setRuntime`。本实现的 [`index.ts`](../typescript/attp/channels/openclaw/index.ts) 已在 `defineChannelPluginEntry.setRuntime(api.runtime)` 捕获，正常不应触发；若 openclaw 升级后 API 变更需复核。

---

## 三、已知注意点

- **ProtocolNode 保持 Python**（不转译）。它是网络共享的篡改检测基础设施，必须全网单一实现；所有宿主通过 HTTP `/record` 共用。
- **演示 DID 仅为本地身份**。生产前必须把 `did.json` 托管到 HTTPS 可解析地址，并为每个 agent 配独立 DID/密钥。
- **旧方案已废弃**：[`integrations/openclaw-plugin/`](../integrations/openclaw-plugin/) + [`python/attp/channels/openclaw/`](../python/attp/channels/openclaw/) 待本方案实机验证通过后删除（见附录第 5 步）。**本期不删任何代码，只更新文档。**
- **multibase / base58 公钥提取暂未实现**：[`did-resolver.ts`](../typescript/attp/core/authentication/did-resolver.ts) 目前支持 JWK / PEM 公钥；multibase / base58 编码的 verificationMethod 暂不支持，遇到会跳过该 key。
- **MCP SSE 传输**：SDK 1.29 起 `SSEServerTransport` 标记为 deprecated（推荐 StreamableHTTP），但为兼容 openclaw 现有 `transport:"sse"` 配置仍使用 SSE，功能正常。
- **`didToAdUrl` 实现重复**：[`app/mcp-node.ts`](../typescript/attp/app/mcp-node.ts) 与 [`channels/openclaw/src/outbound.ts`](../typescript/attp/channels/openclaw/src/outbound.ts) 各有一份同名同实现——刻意不跨层 import（mcp-node 须对任意 host 无依赖）。两边任一处升级请保持同步。
- **openclaw 内部运行时契约**（`runtime.channel.inbound.*`、`resolveInboundRouteEnvelopeBuilderWithRuntime`、`delivery.deliver` payload 形状）是对照内置渠道校准的；openclaw 版本升级时需复核。
- **WS 会话映射一致性**：`WsHub` 以 `sessionId` 为 key，须与 `resolveInboundRouteEnvelopeBuilderWithRuntime` 解出的 `routeSessionKey` 对齐，否则 A2U 回执推不到正确连接。

---

## 附录：实机验证清单

按顺序跑一遍以实机验证本方案。

1. **构建 + 单测**
   ```bash
   cd <ATTP_ROOT>/typescript
   npm install
   npm test                 # 116 用例：签名 / DID-wba / Chain / DID 解析 / 回传 / attp-server / mcp-node / outbound
   npm run build
   ```
2. **装插件 + 设 publicBaseUrl + 启 gateway + 看状态**
   ```bash
   openclaw plugins install --link <ATTP_ROOT>/typescript/attp/channels/openclaw
   openclaw plugins enable attp
   # 编辑 ~/.attp/agent/openclaw/config.json：设置 attpServer.publicBaseUrl 为远端可达 URL
   openclaw gateway restart
   openclaw channels status                 # 期望 attp: running
   openclaw plugins inspect attp --runtime --json
   # 确认三端口在监听：19001 (WebUI+WS) / 19000 (Agent Server) / 19002 (MCP)
   ```
3. **U2A / A2U 往返**（WebUI 端口 :19001，NodeMessage WS）：ATTP user 端连 `ws://<host>:19001/ws` 发 NodeMessage → agent turn → 回复经 `hub.broadcast` 推回（A2U NodeMessage 带签名）。验证 WebUI 即时渲染。
4. **Python nanobot A2A 双向**：
   - **nanobot → openclaw**：让 Python agent 拉你的 `:19000/ad.json` + `/openrpc.json` 发现 `receive_message` rpcUrl → DID-wba POST 到 `:19000/receive`。验证：TS 端验签通过、进 `inbound.run`、回复经 `sendMessage` 回到 Python。
   - **openclaw → nanobot**：让 openclaw agent 调 MCP 工具 `send_message({ target_did: <Python did>, content: "...", ad_url: <Python ad.json> })`（经 `mcp.servers.attp-tools` → :19002）。验证：Python 端收到、验签通过。
   - **双方回传**：到 ProtocolNode `/api/behavior` 看每一跳的 BackMessage 可见。
5. **验证通过后删除旧代码**（仅做、且只在实机验证通过后做；本期不执行）：
   ```bash
   rm -rf integrations/openclaw-plugin/ python/attp/channels/openclaw/
   ```
   然后提交（用户负责 commit）。
