/**
 * ATTP 双端口引导服务 —— host-agnostic 的进程内引导。
 *
 * 把 ATTP 的两条入站链路绑成两个独立端口，让 ATTP 在任意宿主
 * (openclaw / nanobot / 独立进程) 下都保留 **独立的网络身份**：
 *
 *   WebUI 端口 (webPort)   —— 浏览器 WS（NodeMessage 协议，ATTP user 端）
 *                              + 可选静态文件根（uiDir）。
 *   Agent 端口 (agentPort) —— DID-wba A2A 接收 (POST /receive)
 *                              + ad.json / openrpc.json 发现（OpenRPC）。
 *
 * 入站消息统一回调到 `onInbound({direction, session_id, sender_did, content})`，
 * 宿主用 `dispatchAttpInbound` 之类的包装来驱动 agent turn。A2U 出站由宿主通过
 * `runtime.hub.broadcast(sid, nodeMessageFrame(a2uNodeMessage))` 推送 —— 这就是
 * hub 同时挂在 runtime 和 handle 上的原因。
 *
 * 本模块 **不 import 任何 channel 代码**：openclaw / nanobot / 独立三种部署形态
 * 共用同一份引导。Phase-1 反向传播（U2A / A2A）best-effort 触发，失败只记日志，
 * 不阻断入站分发。
 *
 * Plan 4 —— ATTP host-agnostic 引导。
 */

import {
  createServer,
  type Server,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { WebSocketServer, type WebSocket } from "ws";
import { readFileSync, statSync } from "node:fs";
import * as path from "node:path";
import {
  WsHub,
  parseInboundNodeMessage,
  type WsLike,
} from "./web.js";
import { parseInboundRequest, verifyInbound } from "./server.js";
import { resolveDid } from "../core/authentication/did-resolver.js";
import { sendBackMessage } from "../core/message/back-sender.js";
import { RecordedHop } from "../core/message/event.js";
import type { AnyKey } from "../core/authentication/keys.js";

// ---------------------------------------------------------------------------
// 公共类型
// ---------------------------------------------------------------------------

/** 入站消息（U2A / A2A 共用形状）—— onInbound 回调契约。 */
export interface InboundMsg {
  direction: "U2A" | "A2A";
  session_id: string;
  sender_did: string;
  content: string;
}

/**
 * ATTP 运行时容器 —— 由宿主在 startAccount 期间填充。
 *
 * 全部字段可选：身份可在服务启动后才装载；hub 由本服务启动时注入。
 */
export interface AttpServerRuntime {
  agentConfig?: {
    did?: string;
    didDocPath?: string;
    didKeyPath?: string;
    agentName?: string;
    agentDescription?: string;
    protocolUrl?: string;
  };
  privateKey?: AnyKey;
  didDocument?: any;
  /** 启动后由本服务注入；宿主 A2U 出站路径用它 broadcast。 */
  hub?: WsHub;
  /** 每 session 溯源轨迹：U2A/A2A 入站时 set（供 A2U 续链）；由宿主在 startAccount 初始化为 Map。 */
  sessionTraces?: Map<string, { protocolUrl: string; recordedHop: any }>;
}

export interface StartAttpServerParams {
  /** WebUI + WS（NodeMessage）端口；传 0 由 OS 分配。 */
  webPort: number;
  /** Agent Server（DID-wba A2A + ad.json/OpenRPC）端口；传 0 由 OS 分配。 */
  agentPort: number;
  /**
   * Agent server 的外部可达基址，如 "https://host:19000"。
   * 用于 ad.json / openrpc.json 内的 URL，确保 **远端** peer 能回调 /receive。
   * 本地测试用 127.0.0.1 即可。
   */
  publicAgentUrl: string;
  /** A2A 接收路径，默认 "/receive"。 */
  receivePath?: string;
  /** 可选静态 WebUI 根；缺省则非 WS GET 一律 404。 */
  uiDir?: string;
  runtime: AttpServerRuntime;
  /** 入站消息回调（宿主用它驱动 agent turn）。 */
  onInbound: (m: InboundMsg) => Promise<void>;
  /**
   * DI：覆盖默认的 DID 文档解析（默认走 resolveDid → HTTPS）。
   * 主要用于测试注入，也可用于自定义发现端点。
   */
  resolveDidDoc?: (senderDid: string) => Promise<any>;
}

export interface AttpServerHandle {
  webPort: number;
  agentPort: number;
  /** 暴露 hub（也同步写入 runtime.hub），供宿主 A2U 出站 broadcast。 */
  hub: WsHub;
  close(): Promise<void>;
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

/** 读取可读流到 string（Node IncomingMessage）。 */
async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req as AsyncIterable<Buffer>) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

/** 简易 content-type 推断（与 channels/openclaw/src/web-ui.ts 旧版一致；该 channel 文件已在 Plan 4 移除）。 */
function contentTypeFor(fp: string): string {
  const ext = path.extname(fp).toLowerCase();
  switch (ext) {
    case ".html":
    case ".htm":
      return "text/html; charset=utf-8";
    case ".js":
      return "text/javascript; charset=utf-8";
    case ".css":
      return "text/css; charset=utf-8";
    case ".json":
      return "application/json; charset=utf-8";
    case ".svg":
      return "image/svg+xml";
    case ".png":
      return "image/png";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".ico":
      return "image/x-icon";
    default:
      return "application/octet-stream";
  }
}

/** 从 root 读 relPath 并返回；缺失/非文件/越界 → 返回 null（调用方写 404）。 */
function readStatic(root: string, relPath: string): { data: Buffer; contentType: string } | null {
  const safeRoot = path.resolve(root);
  const fp = path.resolve(safeRoot, relPath);
  // 防目录穿越
  if (!fp.startsWith(safeRoot + path.sep) && fp !== safeRoot) return null;
  let st: ReturnType<typeof statSync>;
  try {
    st = statSync(fp);
  } catch {
    return null;
  }
  if (!st.isFile()) return null;
  const data = readFileSync(fp);
  return { data, contentType: contentTypeFor(relPath) };
}

/**
 * best-effort Phase-1 反向传播：把入站 hop 回报给协议节点。
 *
 * 缺 protocolUrl / nonce / recordedHopDict，或运行时身份未就绪时静默跳过；
 * 任何失败只记 warn，不抛（不阻断入站分发）。
 */
async function backPropagate(
  runtime: AttpServerRuntime,
  protocolUrl: string | undefined,
  nonce: string | undefined,
  recordedHopDict: any,
): Promise<void> {
  if (!protocolUrl || !nonce || !recordedHopDict) return;
  const nodeDid = runtime.agentConfig?.did;
  const priv = runtime.privateKey;
  if (!nodeDid || !priv) return;
  try {
    const recordedHop = RecordedHop.fromDict(recordedHopDict);
    await sendBackMessage({
      protocolUrl,
      nodeDid,
      nonce,
      recordedHop,
      privateKey: priv,
    });
  } catch (e) {
    console.warn(
      `[attp/server] Phase-1 back-propagation to ${protocolUrl} failed:`,
      (e as Error).message,
    );
  }
}

/** 解析 query/path：取不含查询串的 pathname。 */
function pathnameOf(req: IncomingMessage): string {
  const u = req.url ?? "/";
  return u.split("?")[0];
}

// ---------------------------------------------------------------------------
// 主入口
// ---------------------------------------------------------------------------

/**
 * 启动 ATTP 双端口服务。返回实际监听端口 + 优雅关闭句柄。
 *
 * 两个端口互不依赖：WebUI 端口跑 WS（NodeMessage）+ 可选静态；Agent 端口跑
 * ad.json / openrpc.json / POST /receive。hub 同时挂在 runtime 与 handle 上。
 */
export async function startAttpServer(
  p: StartAttpServerParams,
): Promise<AttpServerHandle> {
  const receivePath = p.receivePath ?? "/receive";
  const publicAgentUrl = p.publicAgentUrl.replace(/\/+$/, "");
  const runtime = p.runtime;
  const onInbound = p.onInbound;
  // DI：默认走真实 HTTPS DID 解析
  const resolveDidDoc =
    p.resolveDidDoc ??
    (async (did: string) => (await resolveDid(did)).didDocument);

  // 1. 创建 hub，注入 runtime（宿主 A2U 出站路径依赖此）
  const hub = new WsHub();
  runtime.hub = hub;

  // --------------------------------------------------------------
  // WebUI server（WS + 可选静态）
  // --------------------------------------------------------------
  const wss = new WebSocketServer({ noServer: true });

  const webServer: Server = createServer(
    (req: IncomingMessage, res: ServerResponse) => {
      const pn = pathnameOf(req);
      // REST：ATTP WebApp 兼容端点（user 端探测 / 联系人列表）
      if (req.method === "GET" && pn === "/api/status") {
        res.statusCode = 200;
        res.setHeader("content-type", "application/json; charset=utf-8");
        res.end(JSON.stringify({ status: "active", ws_clients: wss.clients.size }));
        return;
      }
      if (req.method === "GET" && pn === "/api/nodes") {
        // 已出现过的对端 agent（从 sessionTraces 的 sender_did 汇总；无则空列表）
        const agents: any[] = [];
        const seen = new Set<string>();
        for (const [, t] of runtime.sessionTraces ?? []) {
          const did = t.recordedHop?.sender_did;
          if (did && !seen.has(did)) {
            seen.add(did);
            agents.push({ did, name: did, description: "", ad_url: "", capabilities: [], online: true });
          }
        }
        res.statusCode = 200;
        res.setHeader("content-type", "application/json; charset=utf-8");
        res.end(JSON.stringify({ agents }));
        return;
      }
      // 非 WS 的 GET 走静态（若提供 uiDir）；否则 404
      if (req.method === "GET" && p.uiDir) {
        const rel = decodeURIComponent(pn.replace(/^\/+/, ""));
        // 根路径 → index.html
        const relPath = rel === "" ? "index.html" : rel;
        const file = readStatic(p.uiDir, relPath);
        if (file) {
          res.statusCode = 200;
          res.setHeader("content-type", file.contentType);
          res.end(file.data);
          return;
        }
      }
      res.statusCode = 404;
      res.end("not found");
    },
  );

  // WS 升级：仅接受 /ws 路径
  webServer.on("upgrade", (req: IncomingMessage, socket: any, head: any) => {
    if (pathnameOf(req) !== "/ws") {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws: WebSocket) => {
      console.log("[attp/server] WS client connected");
      const sessionIdHolder: { sid?: string } = {};
      ws.on("message", (data: Buffer | ArrayBuffer | Buffer[], isBinary: boolean) => {
        // ws v8+：只处理文本帧
        if (isBinary) return;
        const raw = Buffer.isBuffer(data)
          ? data.toString("utf8")
          : Buffer.from(data as ArrayBuffer).toString("utf8");
        const msg = parseInboundNodeMessage(raw);
        if (!msg) {
          console.warn("[attp/server] WS non-NodeMessage frame ignored");
          return;
        }
        console.log(
          `[attp/server] U2A inbound sid=${msg.sessionId} content="${String(msg.content).slice(0, 60)}"`,
        );
        sessionIdHolder.sid = msg.sessionId;
        if (msg.sessionId) hub.register(msg.sessionId, ws as unknown as WsLike);

        // 存 session 溯源轨迹（供 A2U appendHop 续链 + /api/nodes 汇总）
        const inboundProtocolUrl =
          msg.nodeMessage?.protocol_url ?? runtime.agentConfig?.protocolUrl ?? "";
        if (msg.sessionId && runtime.sessionTraces && msg.nodeMessage?.recorded_hop) {
          runtime.sessionTraces.set(msg.sessionId, {
            protocolUrl: inboundProtocolUrl,
            recordedHop: msg.nodeMessage.recorded_hop,
          });
        }

        // best-effort Phase-1 U2A 回传：优先用入站 NodeMessage 的 protocol_url（对齐 Python WebApp:90-108）
        void backPropagate(
          runtime,
          inboundProtocolUrl,
          msg.nodeMessage?.nonce,
          msg.nodeMessage?.recorded_hop,
        )
          .then(() =>
            console.log(
              `[attp/server] U2A back-prop OK -> ${inboundProtocolUrl || "(no protocol_url)"}`,
            ),
          )
          .catch((e) => console.error("[attp/server] U2A back-prop error:", e));

        // 入站分发
        void onInbound({
          direction: "U2A",
          session_id: msg.sessionId,
          sender_did: msg.senderDid ?? "user",
          content: msg.content,
        }).catch((e) => console.error("[attp/server] U2A dispatch failed:", e));
      });
      ws.on("close", () => {
        console.log(
          `[attp/server] WS client disconnected sid=${sessionIdHolder.sid ?? "-"}`,
        );
        if (sessionIdHolder.sid) {
          hub.unregister(sessionIdHolder.sid, ws as unknown as WsLike);
        }
      });
    });
  });

  const actualWebPort: number = await new Promise((resolve, reject) => {
    webServer.on("error", reject);
    webServer.listen(p.webPort, () => {
      const addr = webServer.address();
      resolve(typeof addr === "object" && addr ? addr.port : p.webPort);
    });
  });

  // --------------------------------------------------------------
  // Agent server（ad.json / openrpc.json / POST /receive）
  // --------------------------------------------------------------
  const agentServer: Server = createServer(
    async (req: IncomingMessage, res: ServerResponse) => {
      const pn = pathnameOf(req);
      try {
        if (req.method === "GET" && pn === "/ad.json") {
          // 对齐 ANP/OpenRPC 发现契约（anp.openanp.RemoteAgent.discover +
          // ATTPClient._get_remote_agent）：
          //   - identifier：Python ATTPClient 用作 remote_agents 注册键（缺失则发现后丢弃）
          //   - name / description：RemoteAgent.discover 末尾 _require_non_empty_str 强制非空
          const did = runtime.agentConfig?.did;
          const name = runtime.agentConfig?.agentName || did || "attp-agent";
          const description =
            runtime.agentConfig?.agentDescription || "ATTP agent";
          res.statusCode = 200;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(
            JSON.stringify({
              did,
              identifier: did,
              name,
              description,
              interfaces: [
                {
                  type: "StructuredInterface",
                  protocol: "openrpc",
                  url: `${publicAgentUrl}/openrpc.json`,
                },
              ],
            }),
          );
          return;
        }

        if (req.method === "GET" && pn === "/openrpc.json") {
          // 对齐 anp.openanp.client.openrpc.parse_openrpc 的硬约束：每个方法
          //   必须有非空 description + result(dict) + params(list)；rpc 端点取自
          //   methods[0].servers[0].url（_extract_rpc_url）。params 带 schema，使
          //   RemoteAgent.tools 的 OpenAI 工具转换也能通过（convert_to_openai_tool
          //   要求每个 param 有 name + schema dict）。
          res.statusCode = 200;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(
            JSON.stringify({
              openrpc: "1.2.6",
              info: { title: "attp-agent", version: "1.0.0" },
              // anp parse_openrpc 把【顶层】servers 传播进每个方法的 m["servers"]，
              // 完全忽略方法内的 servers；故 rpc 端点必须出现在顶层（Python 端
              // _extract_rpc_url 读的是这个）。方法内同款 servers 一并保留，供本仓
              // TS discoverAgent 使用（它读 method.servers[0].url）。
              servers: [{ url: `${publicAgentUrl}${receivePath}` }],
              methods: [
                {
                  name: "receive_message",
                  description:
                    "Receive an ATTP A2A (agent-to-agent) message. DID-wba authenticated JSON-RPC over HTTP; the NodeMessage envelope is carried in params.metadata.NodeMessage.",
                  params: [
                    {
                      name: "sender_did",
                      required: true,
                      schema: {
                        type: "string",
                        description: "Sender agent DID (did:wba:...).",
                      },
                    },
                    {
                      name: "content",
                      required: true,
                      schema: { type: "string", description: "Message content." },
                    },
                    {
                      name: "message_type",
                      required: true,
                      schema: {
                        type: "string",
                        description: "Message type (agent_request | agent_reply).",
                      },
                    },
                    {
                      name: "metadata",
                      schema: {
                        type: "object",
                        description:
                          "Carries the ATTP NodeMessage envelope under 'NodeMessage'.",
                      },
                    },
                  ],
                  result: {
                    name: "result",
                    description: "Acknowledgement string.",
                    schema: { type: "string" },
                  },
                  servers: [{ url: `${publicAgentUrl}${receivePath}` }],
                },
              ],
            }),
          );
          return;
        }

        if (req.method === "POST" && pn === receivePath) {
          const bodyStr = await readBody(req);

          // 解析 JSON-RPC 业务字段
          let parsed: ReturnType<typeof parseInboundRequest>;
          try {
            parsed = parseInboundRequest(bodyStr);
          } catch {
            res.statusCode = 400;
            res.setHeader("content-type", "application/json; charset=utf-8");
            res.end(
              JSON.stringify({
                jsonrpc: "2.0",
                id: null,
                error: { code: -32700, message: "Parse error: invalid json" },
              }),
            );
            return;
          }

          // 重建完整 target-uri（RFC 9421 @target-uri 需绝对 URI）。
          // 远端 peer 按公开 URL 签名；服务器按 Host 头重建，使二者一致。
          const host = req.headers.host ?? "";
          const fullUrl = host
            ? new URL(req.url ?? "/", `http://${host}`).href
            : (req.url ?? "");

          const ok = await verifyInbound({
            method: req.method ?? "POST",
            url: fullUrl,
            headers: req.headers as Record<string, string>,
            body: Buffer.from(bodyStr, "utf8"),
            senderDid: parsed.senderDid,
            resolveDidDoc,
          });

          if (!ok) {
            res.statusCode = 401;
            res.setHeader("content-type", "application/json; charset=utf-8");
            res.end(
              JSON.stringify({
                jsonrpc: "2.0",
                id: parsed.id ?? null,
                error: { code: -32001, message: "unauthorized" },
              }),
            );
            return;
          }

          // best-effort Phase-1 A2A 回传（优先用消息内 protocolUrl，回退本机配置）
          void backPropagate(
            runtime,
            parsed.protocolUrl ?? runtime.agentConfig?.protocolUrl,
            parsed.nonce,
            parsed.nodeMessage?.recorded_hop,
          ).catch((e) =>
            console.error("[attp/server] A2A back-prop error:", e),
          );

          // 入站分发（即时 ack；dispatch 异步进行）
          const sessionId: string =
            parsed.nodeMessage?.recorded_hop?.session_id ?? parsed.senderDid;
          void onInbound({
            direction: "A2A",
            session_id: sessionId,
            sender_did: parsed.senderDid,
            content: parsed.content,
          }).catch((e) => console.error("[attp/server] A2A dispatch failed:", e));

          // 即时 JSON-RPC ack（对齐 Python receive_message 返回 "Message received"）。
          // agent turn 在 onInbound 内异步进行；A2A 不自动反向回复——若需回复，
          // 接收者 agent 自行调用 ATTP MCP send_message 工具发起一条新 A2A 消息。
          res.statusCode = 200;
          res.setHeader("content-type", "application/json; charset=utf-8");
          res.end(
            JSON.stringify({
              jsonrpc: "2.0",
              id: parsed.id ?? null,
              result: "Message received",
            }),
          );
          return;
        }

        // 其它路径
        res.statusCode = 404;
        res.end("not found");
      } catch (err) {
        // 兜底：单个请求异常不应拖垮服务
        if (!res.headersSent) {
          res.statusCode = 500;
          res.end(String((err as Error)?.message ?? err));
        }
      }
    },
  );

  const actualAgentPort: number = await new Promise((resolve, reject) => {
    agentServer.on("error", reject);
    agentServer.listen(p.agentPort, () => {
      const addr = agentServer.address();
      resolve(typeof addr === "object" && addr ? addr.port : p.agentPort);
    });
  });

  return {
    webPort: actualWebPort,
    agentPort: actualAgentPort,
    hub,
    close: async () => {
      // 关闭 WS 连接 + 底层 server；所有关闭 best-effort，不互相阻塞
      await Promise.allSettled([
        new Promise<void>((resolve) => wss.close(() => resolve())),
        new Promise<void>((resolve) => webServer.close(() => resolve())),
        new Promise<void>((resolve) => agentServer.close(() => resolve())),
      ]);
    },
  };
}
