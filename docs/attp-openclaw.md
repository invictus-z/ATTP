# ATTP × openclaw 集成：设计与使用

把 ATTP 作为一个 **openclaw 渠道插件**运行，使 ATTP 全部组件随 `openclaw gateway` 一并启动，并保留 ATTP 完整能力（U2A/A2U、跨框架 A2A 与协议节点回传、ATTP 工具节点、溯源链、心跳、ProtocolNode）。配置示例见 `examples/.openclaw/` 与 `examples/.attp/agent/openclaw/`。

---

## 一、设计

### 1.1 目标与约束
- **openclaw 源码零改动**：只允许改 `~/.openclaw/openclaw.json`，外加一个被 `--link` 加载的插件目录。
- **ATTP 现有文件零改动**：新增代码以新模块形式加入（`attp/channels/openclaw/`、`integrations/openclaw-plugin/`）。
- **语义复刻 nanobot 集成**：ATTP WebUI 为用户面、宿主 gateway 的 agent 为「大脑」、ATTP 全组件存活。

### 1.2 关键事实：openclaw 渠道插件是进程内 Node.js
openclaw 的 channel 插件是加载进 gateway **Node 进程内**的模块（`ChannelPlugin` 对象，`gateway.startAccount(ctx)`/`stopAccount(ctx)` 生命周期），**没有**「外部进程 channel / 子进程 channel」模型。ATTP 是 **Python**，因此不能像 nanobot 那样让 ATTP 自己当 channel 类——必须由一个 **Node 侧渠道插件** spawn 一个 **ATTP Python 子进程**，两者在 loopback 上跨语言桥接。

### 1.3 架构总览
```
openclaw gateway (Node, 进程内)
┌─────────────────────────────────────────────────────────────┐
│ TS 渠道插件 "attp"  (integrations/openclaw-plugin/)         │
│  defineChannelPluginEntry({ setRuntime, registerFull, plugin })│
│   registerFull(api): api.registerHttpRoute("/attp/inbound") │
│                      + 生成 webhook token 写入 runtimeState │
│   gateway.startAccount(ctx): spawn <pythonPath> -m            │
│       attp.channels.openclaw --config <cfg> --webhook <url>   │
│       --token <tok>  (+ 健康探针 /api/status、退避重启、SIGTERM停)│
│   入站: /attp/inbound → resolveInboundRouteEnvelopeBuilder…   │
│         → runtime.channel.inbound.buildContext + run → agent  │
│   出站: outbound.sendText({to:"attp:<sid>"}) → POST /openclaw/reply│
└──────────────────┬──────────────────────────────┬───────────┘
     spawn 子进程   │                HTTP loopback │
┌──────────────────▼──────────────────────────────▼───────────┐
│ Python ATTP 适配器 (attp/channels/openclaw/)                │
│  OpenclawATTPAdapter —— 复用全部现有组件，0 改现有文件：      │
│   ConfigManager·AgentTracer·WebApp(:webAppPort)·AppSession·  │
│   ATTPClient·ATTPServer(:serverPort)·Heartbeat(+2 checker)· │
│   MCPToolBridge(:mcpPort)·[ProtocolNode]                      │
│  接线 = ATTPChannel.start() 的逐行翻译：                      │
│   WebApp.channel_callback       ──┐ POST {sender_did,sid,     │
│   ATTPServer.attp_channel_callback┘   content,direction}      │
│                                       → /attp/inbound (U2A+A2A)│
│   WebApp._app 挂 POST /openclaw/reply → send_message_to_user  │
└─────────────────────────────────────────────────────────────┘
```
语义：ATTP WebUI（默认 :19001）= 用户面；openclaw agent = 大脑；ATTP 全组件随 gateway 启停。

### 1.4 大脑接入：两处缝（与 nanobot 完全同构）
ATTP 与宿主框架只有两处耦合，其余（DID 鉴权、NodeMessage、溯源跳链、协议节点回传）都是框架无关的 ATTP 组件：
1. **入站**（→ 大脑）：`WebApp.channel_callback`（U2A，用户→大脑）与 `ATTPServer.attp_channel_callback`（A2A，远端 Agent→大脑）都接到「POST 到 `/attp/inbound`」的转发器。
2. **出站 A2A**（大脑→远端）：大脑调用 MCP 工具 `send_message_tool`（`MCPToolBridge` 以 SSE 暴露在 `:mcpPort`），其回调 = `ATTPClient.send_message`（append A2A 跳 → **回传协议节点** → OpenANP 发送给远端）。

> 普通「回复」（openclaw `outbound.sendText`）只到 WebUI 用户（A2U）；要回复**远端 Agent**，大脑必须用 `send_message_tool`——与 nanobot 一致。

### 1.5 跨框架 A2A 与协议节点回传（为何天然成立）
A2A 收发与回传完全由框架无关的 ATTP 组件承担：
- **发送方** `ATTPClient.send_to_agent`：`AgentTracer.append_hop(A2A)` → **先回传协议节点**（`send_back_message` → `POST {protocol_url}/record`）→ 再经 OpenANP（DID-Wba）发给目标。
- **接收方** `ATTPServer.receive_message`：解析 NodeMessage、存 trace、调 `attp_channel_callback`（唯一的大脑缝）→ **Phase-1 回传**给发送方的协议节点。

因此 nanobot-Agent ↔ openclaw-Agent 的 A2A 往返里，每一跳（发送前、收到后）都回传协议节点，溯源链完整、框架无关。前提：双方 `nodeAds` 互含对方 ad.json、各自独立 DID/密钥、共享可达协议节点、宿主连上 `:mcpPort`（既是工具桥，也是 A2A 出站依赖）。

### 1.6 组件文件
**Python 适配器** `python/attp/channels/openclaw/`（0 改现有文件）：
- `bridge.py`：`build_inbound_payload` + `post_inbound`（入站转发）；`mount_reply_route`（在 WebApp 挂 `POST /openclaw/reply` → `send_message_to_user`）。
- `adapter.py`：`OpenclawATTPAdapter`，`_build()` 构造并接线全部组件（翻译 `ATTPChannel.start()`），`run()` TaskGroup 并发起、阻塞、优雅停。
- `__main__.py`：`python -m attp.channels.openclaw --config --webhook --token` 子进程入口。

**TS 渠道插件** `integrations/openclaw-plugin/`（openclaw 源码 0 改动）：
- `index.ts`：`defineChannelPluginEntry({ setRuntime(api.runtime), registerFull(注册 webhook + token), plugin })`。
- `src/channel.ts`：`createChatChannelPlugin`（config/setup/outbound）+ 展开挂 `gateway:{startAccount,stopAccount}`（builder 不转发 `gateway` 兄弟字段，必须展开）。`startAccount` spawn + 退避重启 + `/api/status` 就绪探针。
- `src/supervisor.ts`：子进程 spawn/退避（1s,2s,5s,max5）/SIGTERM 停。
- `src/inbound.ts`：webhook 鉴权 + `resolveInboundRouteEnvelopeBuilderWithRuntime`（`openclaw/plugin-sdk/inbound-envelope`）→ `runtime.channel.inbound.buildContext` + `run`（adapter 的 `resolveTurn` 提供 `recordInboundSession` + `dispatchReplyWithBufferedBlockDispatcher` + `delivery.deliver`→POST `/openclaw/reply`）。
- `types/openclaw.d.ts`：本地类型 shim（`@openclaw/plugin-sdk` 当前为私有包；待其公开发布后替换为真实类型）。

---

## 二、使用方式

### 2.1 前置
- ATTP 仓库 + `.venv`（可 `import attp`）。
- openclaw 可运行（`openclaw --version`）。**本机推荐用托管服务**：`openclaw gateway start/stop/restart`（Windows 为 schtasks「OpenClaw Gateway」）。避免手动 `node .../openclaw.mjs gateway run` 长跑——它会与托管服务竞争 18789 端口并触发 gateway drain。
- ATTP openclaw profile：`~/.attp/agent/openclaw/config.json`（schema 与 nanobot profile 一致；端口示例 19000/19001/19002，见 `examples/.attp/agent/openclaw/config.json`）。

### 2.2 安装插件（不改 openclaw 源码）
```bash
cd <ATTP 仓库>
openclaw plugins install --link ./integrations/openclaw-plugin   # 写入 plugins.load.paths
openclaw plugins enable attp
openclaw gateway restart                                          # load.paths 属 Infrastructure，需重启
```
`--link` 不拷贝，便于改完 TS 代码后 `gateway restart` 即生效。

### 2.3 配置
**(a) `~/.openclaw/openclaw.json`**（在现有结构上合并；模板见 `examples/.openclaw/config.json`）：
```jsonc
{
  "plugins":  { "entries": { "attp": { "enabled": true } } },
  "channels": {
    "attp": {
      "pythonPath": "<ATTP 仓库>/.venv/Scripts/python.exe",
      "configPath": "~/.attp/agent/openclaw/config.json",
      "webAppPort": 19001
    }
  },
  "bindings": [ { "agentId": "main", "match": { "channel": "attp" } } ],
  "mcp": {
    "servers": {
      "attp-tools": { "url": "http://127.0.0.1:19002/sse", "transport": "sse" }
    }
  }
}
```
- `channels.attp` 段存在即自动启动 channel。
- `webAppPort` 必须等于 ATTP profile 的 `webApp.port`（出站回复走它）。
- `mcp.servers.attp-tools.url` 端口必须等于 profile 的 `tool.port`；SSE 路径按 `FastMCP.sse_app()` 实测（预计 `/sse`），用 `curl -N http://127.0.0.1:<mcpPort>/sse` 确认。MCP 既是工具桥，也是 A2A 出站依赖。
- channel id `attp` 必须三处一致：manifest `channels:[]`、`package.json#openclaw.channel.id`、入口 `defineChannelPluginEntry({id})`，且与 `channels.attp` 键名、`bindings[].match.channel` 一致。

**(b) `~/.attp/agent/openclaw/config.json`**（ATTP profile；模板见 `examples/.attp/agent/openclaw/config.json`）：与 nanobot profile 同 schema，端口 19000(A2A server)/19001(WebApp)/19002(MCP 工具桥)；`attp_client.nodeAds` 填对端 agent 的 ad.json；`protocol_node.configPath` 指向可达协议节点。
> **生产前必须为 openclaw-agent 配置独立 DID/密钥**（不可与 nanobot-agent 复用同一身份，否则跨框架 A2A 身份混淆）。用 `scripts/did_creator.py` 生成并把 `did.json` 托管到对端可解析的 URL。

### 2.4 启动与验证
```bash
openclaw gateway restart                       # 托管服务（勿手动 node 长跑）
openclaw plugins inspect attp --runtime --json
openclaw channels status --probe               # 期望 attp: running
```
gateway 启动后会 spawn ATTP Python 子进程，绑定 19000/19001/19002；浏览器开 `http://127.0.0.1:19001` 即 ATTP WebUI。

### 2.5 跨框架 A2A 部署（nanobot-agent ↔ openclaw-agent）
前提：双方各自独立 DID/密钥；`attp_client.nodeAds` 互含对方 ad.json；共享可达协议节点；双方宿主均连上各自 `:mcpPort`。
在任一 WebUI 让 agent 调 MCP 工具 `send_message_tool(target=<对端 did>, chat_id=<sid>, content=...)` 即可发起 A2A；协议节点会记录每一跳（发送前、收到后）的回传，溯源链完整。

### 2.6 排查
- **channel 注册失败**：manifest 缺顶层 `configSchema`（openclaw 必需）；channel id 三处不一致。
- **`/attp/inbound` 401**：webhook token 不一致（由 `registerFull` 生成、经 `--token` 传 Python、入站校验）。
- **WebUI 无回复**：检查 `outbound.sendText` 是否 POST 到正确 `webAppPort`；`send_message_to_user` 是否找到 session trace；入站是否真正驱动 agent（看 gateway 日志 `message processed: channel=attp ... outcome=`）。
- **MCP 工具不可见**：`curl -N http://127.0.0.1:<mcpPort>/sse` 确认 SSE 路径；必要时改 `mcp.servers.attp-tools.url`。
- **子进程反复崩溃**：`gateway` 日志看 `[attp] python exited code=...`；手动跑 `python -m attp.channels.openclaw --config ~/.attp/agent/openclaw/config.json --webhook http://127.0.0.1:18789/attp/inbound` 排错。
- **gateway 反复 drain**：通常是手动 `node .../openclaw.mjs gateway` 与托管服务抢端口——改用 `openclaw gateway start/stop/restart`；或 agent 的 LLM provider 限流导致 turn 失败，换 provider/model。

## 三、已知注意点
- `@openclaw/plugin-sdk` 当前为私有包；TS 侧用本地类型 shim，待其公开发布后替换为真实类型。
- Windows 下 Python 子进程的 SIGTERM 优雅停依赖进程 kill（host supervisor 直接 kill）。
- TS 与 openclaw 内部运行时的若干契约（`runtime.channel.inbound.*`、`resolveInboundRouteEnvelopeBuilderWithRuntime`、reply payload）是通过对照内置 googlechat 渠道校准的；openclaw 版本升级时需复核。
