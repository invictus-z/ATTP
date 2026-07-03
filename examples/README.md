# 配置示例（预置演示身份）

本目录提供一套**开箱即用的预置演示身份与配置**，目录结构完全贴合运行时的 `~/.attp/`、`~/.nanobot/`，可直接复制到用户主目录使用，也可由 Docker 镜像在构建时 COPY 进容器对应位置。

> ⚠️ **安全提示**：`did/` 下的私钥（`*_private.pem`）是**演示用共享身份**，全网公开、任何人可见，仅供「演示模式」快速体验，**切勿用于生产**。用户端在演示模式下会在标题处标注红色「演示版」徽标以示区分。

## 目录结构

```
examples/
├── .attp/
│   ├── agent/nanobot/
│   │   ├── config.json        # 智能体节点配置（nanobot 渠道读取）
│   │   └── did/               # agent 身份：did.json + key-1/2/3 公私钥
│   ├── protocol_node/
│   │   └── config.json        # 协议节点配置（存储/分析）
│   ├── tool/
│   │   └── did/               # 工具节点身份（DID 内联于 test/demo_tool_node.py）
│   └── user/
│       ├── config.json        # 用户节点配置（含 mode:"demo"）
│       └── did/               # 用户身份
├── .nanobot/
│   └── config.json            # nanobot 配置模板（LLM provider + ATTP 渠道注册，${...} 占位）
└── README.md
```

## 预置身份（hostname: attp-diting.cn，e1 profile）

| 节点 | DID |
|---|---|
| agent | `did:wba:attp-diting.cn:test:agent:nanobot:e1_jrd7uiR2w6wEPDOe-_JtNpvrJjokOdz9Io_hZExLsKw` |
| tool  | `did:wba:attp-diting.cn:test:tool:add:e1_PqnyqzB9PTK4SvW3HHyxm-6xYMTexMo1rABMgGpfc1Y` |
| user  | `did:wba:attp-diting.cn:test:user:dashboard:e1_3mg8jiSh4lIDcGm98lFrtIeQBCy6dU_MX2oYZRmatSE` |

## 配置相关性（端口与引用）

端口约定：协议节点 **9000**、agent webApp（用户 WS 入口）**8001**、agent attpServer **8000**、工具节点 **9999**。用户节点跑在宿主（Electron），后端节点跑在 Docker：**宿主 ↔ 容器用 `localhost:<发布端口>`，容器互访用 compose 服务名**。

- `agent.tool.toolNodeAds` = `["http://tool:9999/attp/ad.json"]`（容器内服务名 `tool`）
- `user.protocolNodes` = `[{ name: "diting-pn", url: "http://localhost:9000" }]`
- `user.agents` = `[{ name: "diting-agent", baseUrl: "http://localhost:8001", did: <agent DID> }]`
- `user.toolNodes` = `[{ name: "diting-tool", url: "http://localhost:9999" }]`

> 关键：`protocol_url` 是**消息内字段**，由用户节点写入首跳、逐跳传递，agent/tool 从收到的消息中取用——因此**只有用户节点需要配 `protocolNodes.url`**，agent/tool 无需各自配置协议节点地址。

## DID 文档托管（跨节点验签必需）

跨节点签名验证时，`DIDResolver` 会按以下 URL 拉取对端 DID 文档，需在 `attp-diting.cn` 上**按路径托管**对应的 `did.json`（即各 `did/did.json` 的内容）：

```
https://attp-diting.cn/test/agent/nanobot/did.json
https://attp-diting.cn/test/tool/add/did.json
https://attp-diting.cn/test/user/dashboard/did.json
```

> 解析器默认走 `https://`，并强制开启证书校验。DID 文档服务器必须部署受信任的 TLS 证书，否则解析失败。

## 使用方式

### 本地（开发）
```bash
cp -r examples/.attp/* ~/.attp/
cp -r examples/.nanobot  ~/
# 编辑 ~/.nanobot/config.json，把 ${LLM_MODEL}/${LLM_API_KEY}/${LLM_BASE_URL} 替换为真实值
```

### Docker
各 `Dockerfile` 在构建时 `COPY examples/.attp/<node>/ /root/.attp/<node>/`（及 `examples/.nanobot/ /root/.nanobot/`），agent 容器启动前 `envsubst` 把 `.env` 里的 `LLM_*` 注入 nanobot 配置。详见仓库根 `docker-compose.yml`。

**镜像分发**：镜像**不打包进客户端**，统一以离线 tarball 形式放 **GitHub Release**。`docker/save-images.sh`（或 `.ps1`）负责 `docker compose build` 后 `docker save` 出 `attp-images-<ver>.tar[.gz]`；评委 `docker load -i <tarball>` 后镜像以 `ghcr.io/invictus-z/attp-*:latest` tag 进本地，`docker compose up` 直接命中本地、无需联网。用户端「后端服务」面板的「导入离线镜像」按钮可一键完成 load。完整发布流程见仓库根 `RELEASE.md`。


## 重新生成身份

如需更换身份（例如换域名或实例名），用仓库脚本：

```bash
python scripts/did_creator.py --hostname attp-diting.cn --type agent \
    --names did --path-segments test agent nanobot --output-dir examples/.attp/agent/nanobot
python scripts/did_creator.py --hostname attp-diting.cn --type tool  \
    --names did --path-segments test tool add     --output-dir examples/.attp/tool
python scripts/did_creator.py --hostname attp-diting.cn --type user  \
    --names did --path-segments test user dashboard --output-dir examples/.attp/user
```

生成后需把 `did.json` 中的 `id` 回填到对应 `config.json` 与 `test/demo_tool_node.py`。
