/**
 * ATTP MCP tools node —— host-agnostic 的 MCP 服务节点。
 *
 * 把 ATTP 的 A2A 发送能力 (executeSendMessage) 暴露成一个独立的 MCP server，
 * 暴露 `send_message` 工具，任何 MCP 客户端 (openclaw / nanobot / 任意宿主) 都能
 * 通过 SSE 连接消费：
 *
 *   openclaw config: mcp.servers.attp-tools = { url: "http://127.0.0.1:19002/sse", transport: "sse" }
 *
 * 之所以独立成节点 (而非用 openclaw 的 registerTool 原生注册)，是为了让 ATTP 的
 * 工具表面与宿主解耦：同一个 MCP 节点对 nanobot / openclaw / 独立进程都适用，
 * 不依赖任何 channel 的运行时。本模块 **不 import 任何 channel 代码**。
 *
 * 身份装载是 **lazy** 的：节点可以在 host 装载 DID 文档 / 私钥之前先启动 (端口先
 * 监听起来)，工具被真正调用时才读取 rt.didDocument / rt.privateKey / rt.agentConfig。
 * 若此时身份尚未就绪，工具以明确错误回报 (isError=true)，而不是崩节点。
 *
 * 传输：SSE (GET /sse 建流 + POST /message 投递)，对齐 Python FastMCP SSE +
 * openclaw `mcp.servers` 的约定。SDK 1.29 起 SSEServerTransport 标记为 deprecated
 * (推荐 StreamableHTTP)，但为兼容 openclaw 现有 `transport:"sse"` 配置仍使用 SSE。
 *
 * Plan 3 —— ATTP tools 表面 host-agnostic 化。
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { createServer, type Server, type IncomingMessage, type ServerResponse } from "node:http";
import { z } from "zod";
import { executeSendMessage } from "./tools.js";
import type { AnyKey } from "../core/authentication/keys.js";
import type { AgentTracer } from "../core/agent-tracer.js";
import { RecordedHop } from "../core/message/event.js";

/**
 * MCP 节点运行时 —— 由 host 在 startAccount 期间填充。
 *
 * 全部字段可选：节点启动时身份未必已装载；工具执行时 lazy 读取。
 */
export interface McpNodeRuntime {
  /** 本机 DID 文档 (用于 DID-wba 签名)。 */
  didDocument?: any;
  /** 本机私钥 (LoadedKey / AnyKey)。 */
  privateKey?: AnyKey;
  /** 本机 agent 配置：did 为发送方，protocolUrl 触发 Phase-1 回传。 */
  agentConfig?: { did?: string; protocolUrl?: string };
  /**
   * 已知对端 DID → ad.json URL 映射（host 从 nodeAds 预发现填充）。
   * send_message 优先命中此表，未命中再回退 didToAdUrl 推导。
   */
  peerRegistry?: Map<string, string>;
  /** AgentTracer：续链 appendHop 用（host 在 startAccount 期注入）。 */
  tracer?: AgentTracer;
  /**
   * 每 session 溯源轨迹（host 维护）：session_id → {protocolUrl, recordedHop}。
   * send_message 用 session_id 查表续链（appendHop A2A），传播 user 端的
   * session_id + protocol_url。结构镜像 channels/.../runtime.ts 的 SessionTrace，
   * 刻意不跨层 import channel 代码。
   */
  sessionTraces?: Map<string, { protocolUrl: string; recordedHop: any }>;
}

/** startMcpNode 的返回句柄：暴露实际监听端口 + 优雅关闭。 */
export interface McpNodeHandle {
  /** 实际监听端口 (port=0 时由 OS 分配)。 */
  port: number;
  /** 关闭 MCP server + 底层 http server，等待退出。 */
  close(): Promise<void>;
}

/**
 * 启动 ATTP MCP 节点：在给定端口监听 SSE，注册 send_message 工具。
 *
 * @param rt  运行时身份容器 (lazy 读取，可在节点启动后才被 host 填充)
 * @param port 监听端口，默认 19002；传 0 则由 OS 分配临时端口
 */
/** 单个 SSE 会话的句柄：每会话独立的 McpServer + transport。 */
interface Session {
  server: McpServer;
  transport: SSEServerTransport;
}

/**
 * 为一次 SSE 会话构造独立的 McpServer 并注册 send_message 工具。
 *
 * 高层 McpServer 内部封装了「单 transport」语义 (Protocol.connect 在已连接时会
 * 抛 'Already connected')，因此 SSE 多会话的正确做法是 **每条 /sse 连接配一个
 * 新的 McpServer 实例**，而不是复用同一个 server —— 这也是 SDK 文档的推荐模式。
 */
function createSessionServer(rt: McpNodeRuntime): McpServer {
  const server = new McpServer({ name: "attp-tools", version: "0.1.0" });
  server.tool(
    "send_message",
    "向远端 ATTP agent 发送 A2A 消息 (send a message to a remote ATTP agent)。传入 session_id 以续接当前会话溯源链（传播 user 端的 session_id + protocol_url，对齐 Python send_message_tool 的 chat_id）",
    {
      target_did: z.string().describe("目标 agent 的 DID (did:wba:...)"),
      content: z.string().describe("消息内容"),
      session_id: z
        .string()
        .optional()
        .describe("当前会话 session_id：续接溯源链用（并发安全，显式传入）。缺省则另起新链"),
      ad_url: z
        .string()
        .optional()
        .describe("目标 ad.json URL；缺省时由 target_did best-effort 推导"),
    },
    async (args) => {
      // LAZY 读取运行时身份：节点先于身份装载启动，工具被调用时才需要身份
      if (!rt.didDocument || !rt.privateKey || !rt.agentConfig?.did) {
        throw new Error(
          "ATTP MCP node: agent identity not loaded yet (didDocument / privateKey / agentConfig.did missing)",
        );
      }
      // 续链：若提供 session_id 且存在该会话轨迹，用 appendHop(A2A) 从上一跳续接，
      // 传播 user 端的 session_id + protocol_url。并发安全——session_id 由调用方
      // 显式传入，不依赖全局「当前会话」指针（SSE 跨网络，无法用 AsyncLocalStorage）。
      let recordedHop: RecordedHop | undefined;
      let protocolUrl: string | undefined;
      const trace = args.session_id
        ? rt.sessionTraces?.get(args.session_id)
        : undefined;
      if (trace && rt.tracer) {
        try {
          const m = await rt.tracer.appendHop(
            {
              recordedHop: RecordedHop.fromDict(trace.recordedHop),
              sessionId: args.session_id!,
            },
            args.content,
            rt.agentConfig.did,
            args.target_did,
            rt.privateKey,
            "A2A",
          );
          recordedHop = m.recordedHop!;
          protocolUrl = trace.protocolUrl;
        } catch (e) {
          console.warn(
            "[attp/mcp] appendHop 续链失败，回退 genesis:",
            (e as Error).message,
          );
        }
      }
      const result = await executeSendMessage({
        targetDid: args.target_did,
        content: args.content,
        // adUrl 优先级：显式入参 > nodeAds 预发现注册表 > DID best-effort 推导
        adUrl:
          args.ad_url ??
          rt.peerRegistry?.get(args.target_did) ??
          didToAdUrl(args.target_did),
        didDocument: rt.didDocument,
        privateKey: rt.privateKey,
        senderDid: rt.agentConfig.did,
        protocolUrl,
        recordedHop,
      });
      // MCP 工具返回形状：{ content: [{type:"text", text}] }
      return { content: result.content };
    },
  );
  return server;
}

export async function startMcpNode(
  rt: McpNodeRuntime,
  port = 19002,
): Promise<McpNodeHandle> {
  // SSE 传输：/sse GET 建流 (建一个新 McpServer + transport)，/message POST 投递
  const sessions = new Map<string, Session>();

  const httpServer: Server = createServer(
    async (req: IncomingMessage, res: ServerResponse) => {
      const url = new URL(req.url ?? "", `http://127.0.0.1:${port}`);
      try {
        if (url.pathname === "/sse") {
          const transport = new SSEServerTransport("/message", res);
          const sessionServer = createSessionServer(rt);
          sessions.set(transport.sessionId, {
            server: sessionServer,
            transport,
          });
          res.on("close", () => {
            sessions.delete(transport.sessionId);
            sessionServer.close().catch(() => {});
          });
          await sessionServer.connect(transport);
        } else if (url.pathname === "/message") {
          const sessionId = url.searchParams.get("sessionId") ?? "";
          const session = sessions.get(sessionId);
          if (session) {
            await session.transport.handlePostMessage(req, res);
          } else {
            res.statusCode = 400;
            res.end("no session");
          }
        } else {
          res.statusCode = 404;
          res.end();
        }
      } catch (err) {
        // 兜底：避免单个请求异常拖垮整个节点
        if (!res.headersSent) {
          res.statusCode = 500;
          res.end(String((err as Error)?.message ?? err));
        }
      }
    },
  );

  const actualPort: number = await new Promise((resolve, reject) => {
    httpServer.on("error", reject);
    httpServer.listen(port, () => {
      const addr = httpServer.address();
      // address() 在 listen 成功后必为 AddressInfo (TCP)
      resolve(typeof addr === "object" && addr ? addr.port : port);
    });
  });

  return {
    port: actualPort,
    close: async () => {
      // 关掉所有挂着的 SSE 会话 (每个 session 有独立 McpServer)
      await Promise.all(
        Array.from(sessions.values()).map(async (s) => {
          await s.server.close().catch(() => {});
          await s.transport.close().catch(() => {});
        }),
      );
      httpServer.close();
    },
  };
}

/**
 * 由 did:wba best-effort 推导对端 ad.json URL。
 *
 * 这里 **本地复制** channels/openclaw/src/outbound.ts 的同名实现，刻意不跨层 import，
 * 以保证 mcp-node 对任意 host 都是无依赖的 (openclaw/nanobot/独立)：
 *   did:wba:host:p1:p2        → https://host/p1/p2/ad.json
 *   did:wba:host:p1:p2:e1_key → https://host/p1/p2/ad.json（剥离末尾 key id 段）
 *   did:wba:host              → https://host/.well-known/ad.json
 *
 * 推导不出 (非 did:wba/web 或格式非法) 时返回 ""，调用方需显式提供 ad_url。
 */
export function didToAdUrl(did: string): string {
  const parts = String(did ?? "").split(":");
  if (parts.length < 3 || parts[0] !== "did") return "";
  const method = parts[1];
  if (method !== "wba" && method !== "web") return "";
  const domain = decodeURIComponent(parts[2]);
  const segs = parts.slice(3);
  // 剥离末尾连续的 did:wba key id 段 (e1_/k1_ 前缀)
  while (segs.length > 0 && /^(e1_|k1_)/.test(segs[segs.length - 1])) {
    segs.pop();
  }
  const pathSegments = segs.map((s) => decodeURIComponent(s));
  const base = `https://${domain}`.replace(/\/+$/, "");
  if (pathSegments.length > 0) return `${base}/${pathSegments.join("/")}/ad.json`;
  return `${base}/.well-known/ad.json`;
}
