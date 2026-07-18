/**
 * ATTP Agent 配置加载 — 进程内（in-process）TS agent 的字段选取器。
 *
 * 配置 schema 不改（见 python/attp/app/config/config.py 的 ATTPConfigFile）。
 * 本模块取出 TS in-process agent 需要的身份 / 名称 / 端口字段——
 * 三端口设计（WebUI + Agent Server + MCP node）需要在进程内启动这三组服务，
 * 故 webAppPort / agentServerPort / toolPort / publicAgentUrl 一并上浮到
 * AgentConfig，供 channels/openclaw/src/channel.ts 的 startAccount 读取。
 *
 * Plan 2, Task 1（端口上浮为 Plan 4 三端口改造的一部分）。
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";

/** Agent Server 默认端口（DID-wba A2A + ad.json/OpenRPC）。 */
const DEFAULT_AGENT_SERVER_PORT = 19000;
/** WebUI 默认端口（NodeMessage WS + 可选静态）。 */
const DEFAULT_WEB_APP_PORT = 19001;
/** MCP node 默认端口（send_message tool over SSE）。 */
const DEFAULT_TOOL_PORT = 19002;

/**
 * TS in-process agent 所需的配置视图。
 */
export interface AgentConfig {
  /** Agent 的 DID。 */
  did: string;
  /** DID 文档路径（attpClient.didDocPath）。 */
  didDocPath: string;
  /** DID 私钥路径（attpClient.didKeyPath）。 */
  didKeyPath: string;
  /**
   * 已知对端 agent 的 ad.json URL 列表（attpClient.nodeAds）。
   *
   * 启动时预发现：读取每个 ad.json 的 DID（did/identifier）→ 建立 DID→adUrl 映射，
   * 供 A2A 发送时优先命中（避免对本地/未托管 DID 走 didToAdUrl 推导出不可达 URL）。
   * 对齐 nanobot ATTPClient 的 nodeAds 预发现语义。
   */
  nodeAds?: string[];
  /** Agent 名称（attpServer.name）。 */
  agentName?: string;
  /** Agent 描述（attpServer.description）。 */
  agentDescription?: string;
  /**
   * Protocol Node 的 HTTP URL。
   *
   * 仅当 protocolNode.enabled=true 时，从其 node config 文件解析得到；
   * 否则 undefined。解析失败（文件缺失 / 字段缺失）同样返回 undefined（非致命）。
   */
  protocolUrl?: string;
  /**
   * WebUI 端口（webApp.port）—— NodeMessage WS + 可选静态文件。
   * 默认 19001。
   */
  webAppPort: number;
  /**
   * Agent Server 端口（attpServer.serverPort）—— DID-wba A2A 接收 +
   * ad.json / openrpc.json 发现。默认 19000。
   */
  agentServerPort: number;
  /**
   * MCP tools node 端口（tool.port）—— send_message tool over SSE。
   * 默认 19002。
   */
  toolPort: number;
  /**
   * Agent Server 的外部可达基址（attpServer.publicBaseUrl），如
   * "https://host:19000"。用于 ad.json / openrpc.json 内的 URL，确保 **远端**
   * peer 能回调 /receive。
   *
   * 操作者必须将其设为远端可达的 URL；缺省回退到
   * `http://127.0.0.1:${agentServerPort}` —— 仅本地可达，远端 peer 无法回调。
   */
  publicAgentUrl: string;
}

/**
 * 读 ATTP agent 配置（schema 不改），选择性取字段。
 *
 * 端口与 publicAgentUrl 一并上浮，供进程内三端口启动使用。缺失字段以默认值填补：
 *   webAppPort       ← webApp.port       (default 19001)
 *   agentServerPort  ← attpServer.serverPort (default 19000)
 *   toolPort         ← tool.port         (default 19002)
 *   publicAgentUrl   ← attpServer.publicBaseUrl
 *                       (default http://127.0.0.1:${agentServerPort}；仅本地可达)
 *
 * 入参 `raw` 为解析后的 ATTP agent config JSON 对象
 * （对应 python 的 ATTPConfigFile）。
 */
export function loadAgentConfig(raw: any): AgentConfig {
  const agentServerPort = numberOr(raw?.attpServer?.serverPort, DEFAULT_AGENT_SERVER_PORT);
  return {
    did: raw?.did,
    didDocPath: raw?.attpClient?.didDocPath,
    didKeyPath: raw?.attpClient?.didKeyPath,
    nodeAds: Array.isArray(raw?.attpClient?.nodeAds)
      ? raw.attpClient.nodeAds.filter((u: unknown) => typeof u === "string")
      : undefined,
    agentName: raw?.attpServer?.name,
    agentDescription: raw?.attpServer?.description,
    protocolUrl: raw?.protocolNode?.enabled
      ? loadProtocolUrlFromNodeConfig(raw.protocolNode.configPath)
      : undefined,
    webAppPort: numberOr(raw?.webApp?.port, DEFAULT_WEB_APP_PORT),
    agentServerPort,
    toolPort: numberOr(raw?.tool?.port, DEFAULT_TOOL_PORT),
    publicAgentUrl:
      typeof raw?.attpServer?.publicBaseUrl === "string" && raw.attpServer.publicBaseUrl.length > 0
        ? raw.attpServer.publicBaseUrl
        : `http://127.0.0.1:${agentServerPort}`,
  };
}

/** 取数值字段；非有限数回退 default。容忍字符串型数字（"19000"）。 */
function numberOr(v: unknown, def: number): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return def;
}

/**
 * 从 Protocol Node 配置文件解析其 HTTP URL。
 *
 * 对齐 python/attp/protocol_node/config/config.py 的 ProtocolNodeConfigFile：
 * 该模型只有 `web.host` + `web.port`（PNWebConfig），并无 protocol_url 顶层字段。
 * 这里以 `web.host:port` 构造 URL；同时兼容顶层 `protocol_url` 字段以备前向扩展。
 *
 * 文件缺失 / JSON 解析失败 / 字段缺失时返回 undefined（非致命）。
 */
function loadProtocolUrlFromNodeConfig(
  configPath: string | undefined,
): string | undefined {
  if (!configPath) return undefined;

  let text: string;
  try {
    text = readFileSync(expandHome(configPath), "utf8");
  } catch {
    return undefined;
  }

  let raw: any;
  try {
    raw = JSON.parse(text);
  } catch {
    return undefined;
  }

  if (typeof raw?.protocol_url === "string") return raw.protocol_url;

  const host = raw?.web?.host;
  const port = raw?.web?.port;
  if (
    typeof host === "string" &&
    (typeof port === "number" || typeof port === "string")
  ) {
    // 0.0.0.0 是「绑定所有网卡」的监听地址，作为客户端连接目标在 Windows 等平台
    // 不可达（连接会失败）。协议节点通常与本机 agent 同机，归一化为 127.0.0.1。
    const clientHost = host === "0.0.0.0" ? "127.0.0.1" : host;
    return `http://${clientHost}:${port}`;
  }
  return undefined;
}

/**
 * 展开 `~` / `~/` 为用户 home 目录；其余路径原样返回。
 */
function expandHome(p: string): string {
  if (p === "~") return homedir();
  if (p.startsWith("~/") || p.startsWith("~\\")) {
    return homedir() + p.slice(1);
  }
  return p;
}
