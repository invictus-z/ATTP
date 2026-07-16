# 配置示例（预置演示身份）

本目录提供一套**开箱即用的预置演示身份与配置**，目录结构完全贴合运行时的 `~/.attp/`、`~/.nanobot/`，可直接复制到用户主目录使用，也可由 Docker 镜像在构建时 COPY 进容器对应位置。

> ⚠️ **安全提示**：`did/` 下的私钥（`*_private.pem`）是**演示用共享身份**，全网公开、任何人可见，仅供「演示模式」快速体验，**切勿用于生产**。用户端在演示模式下会在标题处标注红色「演示模式」徽标以示区分。

## 目录结构

```
examples/
├── .attp/
│   ├── agent/
│   │   ├── nanobot/
│   │   │   ├── config.json    # 智能体节点配置（nanobot 渠道读取，端口 8000/8001/8002）
│   │   │   └── did/           # agent 身份：did.json + key-1/2/3 公私钥
│   │   └── openclaw/
│   │       ├── config.json    # 智能体节点配置（openclaw 渠道读取，端口 19000/19001/19002）
│   │       └── did/           # openclaw agent 身份（独立 DID，跨框架 A2A 必需）
│   ├── protocol_node/
│   │   └── config.json        # 协议节点配置（存储/分析）
│   ├── tool/
│   │   └── did/               # 工具节点身份（DID 内联于 test/demo_tool_node.py）
│   └── user/
│       ├── config.json        # 用户节点配置（含 mode:"demo"）
│       └── did/               # 用户身份
├── .nanobot/
│   └── config.json            # nanobot 配置模板（LLM provider + ATTP 渠道注册，${...} 占位）
├── .openclaw/
│   └── config.json            # openclaw 配置模板（~/.openclaw/openclaw.json 用，${...} 占位）
└── README.md
```

## 预置身份（hostname: attp-diting.cn，e1 profile）

| 节点 | DID |
|---|---|
| agent (nanobot) | `did:wba:attp-diting.cn:test:agent:nanobot:e1_jrd7uiR2w6wEPDOe-_JtNpvrJjokOdz9Io_hZExLsKw` |
| agent (openclaw) | `did:wba:attp-diting.cn:test:agent:openclaw:e1_F25aQwabi60nv1os0v4fftulAtkc9w8emwnQbcmyDWA`（`did_creator.py` 本地生成，**未托管**——跨节点验签前需托管，见下文「DID 文档托管」） |
| tool  | `did:wba:attp-diting.cn:test:tool:add:e1_PqnyqzB9PTK4SvW3HHyxm-6xYMTexMo1rABMgGpfc1Y` |
| user  | `did:wba:attp-diting.cn:test:user:dashboard:e1_3mg8jiSh4lIDcGm98lFrtIeQBCy6dU_MX2oYZRmatSE` |

## 配置相关性（端口与引用）

端口约定：协议节点 **9000**、agent webApp（用户 WS 入口）**8001**、agent attpServer **8000**、工具节点 **9999**。用户节点跑在宿主（Electron），后端节点跑在 Docker：**宿主 ↔ 容器用 `localhost:<发布端口>`，容器互访用 compose 服务名**。

> **openclaw agent** 用错开端口以便与 nanobot agent 并存：attpServer **19000**、webApp **19001**、MCP 工具桥 **19002**（见 `examples/.attp/agent/openclaw/config.json`）。

- `agent.tool.toolNodeAds` = `["http://tool:9999/attp/ad.json"]`（容器内服务名 `tool`）
- `user.protocolNodes` = `[{ name: "diting-pn", url: "http://localhost:9000" }]`
- `user.agents` = `[{ name: "diting-agent", baseUrl: "http://localhost:8001", did: <agent DID> }]`
- `user.toolNodes` = `[{ name: "diting-tool", url: "http://localhost:9999" }]`

> 关键：`protocol_url` 是**消息内字段**，由用户节点写入首跳、逐跳传递，agent/tool 从收到的消息中取用——因此**只有用户节点需要配 `protocolNodes.url`**，agent/tool 无需各自配置协议节点地址。

## DID 文档托管（跨节点验签必需）

跨节点签名验证时，`DIDResolver` 会按以下 URL 拉取对端 DID 文档，需在 `attp-diting.cn` 上**按路径托管**对应的 `did.json`（即各 `did/did.json` 的内容）：

```
https://attp-diting.cn/test/agent/nanobot/did.json
https://attp-diting.cn/test/agent/openclaw/did.json
https://attp-diting.cn/test/tool/add/did.json
https://attp-diting.cn/test/user/dashboard/did.json
```

> openclaw agent 的 DID（`did:wba:attp-diting.cn:test:agent:openclaw:...`）由 `did_creator.py` 本地生成、**默认未托管**。若要 nanobot-agent ↔ openclaw-agent 跨框架 A2A 互通，需把 `examples/.attp/agent/openclaw/did/did.json` 托管到 `https://attp-diting.cn/test/agent/openclaw/did.json`（或自建 DID 服务器并改 hostname）。仅单 agent 体验（gateway 拉起 ATTP + U2A）无需托管。

> 解析器默认走 `https://`，并强制开启证书校验。DID 文档服务器必须部署受信任的 TLS 证书，否则解析失败。

## 使用方式

### 本地（开发）
```bash
cp -r examples/.attp/* ~/.attp/
cp -r examples/.nanobot  ~/
# 编辑 ~/.nanobot/config.json，把 ${LLM_MODEL}/${LLM_API_KEY}/${LLM_BASE_URL} 替换为真实值
```

### openclaw（作为 openclaw 渠道插件运行）
把 ATTP 作为 openclaw 的渠道插件，随 `openclaw gateway` 一并启动全部 ATTP 组件。设计与使用详见 [docs/attp-openclaw.md](../docs/attp-openclaw.md)。
```bash
# 1) 拷贝 openclaw agent 的 ATTP profile（端口 19000/19001/19002，独立 DID）
cp -r examples/.attp/agent/openclaw ~/.attp/agent/
#    并在 ~/.attp/agent/openclaw/config.json 的 attpServer 设 publicBaseUrl 为对外可达地址
#    （如 https://attp-diting.cn）—— 供 ad.json/openrpc 广播 /receive，远端 A2A 才能回连

# 2) 构建 TS 插件自包含产物（openclaw 加载 dist/index.js，非 TS 源码）
cd typescript && npm install && npm run build          # 构建 SDK
cd attp/channels/openclaw && npx tsup                  # 产出 dist/index.js（内联 core/app/ws/mcp/依赖，仅 openclaw/* external）

# 3) 安装 TS 渠道插件（不改 openclaw 源码）
cd <ATTP 仓库>
openclaw plugins install --link ./typescript/attp/channels/openclaw

# 4) 把 examples/.openclaw/config.json 的 ${...} 占位替换为真实值后，
#    合并进 ~/.openclaw/openclaw.json（plugins.load.paths / channels.attp{enabled,config_path} / bindings / mcp.servers.attp-tools→:19002/sse）

# 5) 重启 gateway（托管服务；勿手动 node .../openclaw.mjs gateway 长跑）
openclaw gateway restart
openclaw channels status --probe   # 期望 attp: running；三端口 19000/19001/19002 就绪
```
关键占位：`${ATTP_ROOT}`=`<ATTP 仓库>`（插件路径前缀）；`${LLM_*}`=宿主 agent 模型配置。`channels.attp` 只需 `{enabled, config_path}`（端口在 ATTP agent 配置里）；`mcp.servers.attp-tools.url` 端口须等于 `tool.port`（19002）。**改了插件/core/app 的 TS 后，须重跑步骤 2 的 `npx tsup` 再 restart**（openclaw 加载的是 dist 构建产物）。

### Docker
各 `Dockerfile` 在构建时 `COPY examples/.attp/<node>/ /root/.attp/<node>/`（及 `examples/.nanobot/ /root/.nanobot/`）。`agent` 与 `protocol` 两容器的配置含 `${LLM_*}` 占位，由各自 entrypoint 在启动前 `envsubst` 渲染（agent→nanobot 配置；protocol→`analysis` 配置，驱动意图追踪）。`LLM_*` 经 docker-compose `environment` 注入，来源优先级：用户端「后端服务」面板填的 key（spawn env）> 仓库根 `.env`（dev 回落）。详见仓库根 `docker-compose.yml` 与 `RELEASE.md`。

**镜像分发**：镜像**不打包进客户端**，统一以离线 tarball 形式放 **GitHub Release**。`docker/save-images.sh`（或 `.ps1`）负责 `docker compose build` 后 `docker save` 出 `attp-images-<ver>.tar[.gz]`；评委 `docker load -i <tarball>` 后镜像以 `attp-*:latest` tag 进本地，`docker compose up` 直接命中本地、无需联网。用户端「后端服务」面板的「导入离线镜像」按钮可一键完成 load。完整发布流程见仓库根 `RELEASE.md`。


## 重新生成身份

如需更换身份（例如换域名或实例名），用仓库脚本：

```bash
python scripts/did_creator.py --hostname attp-diting.cn --type agent \
    --path-segments test agent nanobot  --output-dir examples/.attp/agent/nanobot/did
python scripts/did_creator.py --hostname attp-diting.cn --type agent \
    --path-segments test agent openclaw --output-dir examples/.attp/agent/openclaw/did
python scripts/did_creator.py --hostname attp-diting.cn --type tool  \
    --path-segments test tool add       --output-dir examples/.attp/tool/did
python scripts/did_creator.py --hostname attp-diting.cn --type user  \
    --path-segments test user dashboard --output-dir examples/.attp/user/did
```

生成后需把 `did.json` 中的 `id` 回填到对应 `config.json` 与 `test/demo_tool_node.py`。
