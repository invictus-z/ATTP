/**
 * 入站分发 —— Plan 3, Task 4。
 *
 * `dispatchAttpInbound` 从 integrations/openclaw-plugin/src/inbound.ts 移植而来
 * （openclaw inbound 三件套 route→envelope→buildContext→run 已经在那里调通，
 * 本文件保持其结构不变，仅做三处与 in-process 化相关的改动，见类头注释）。
 *
 * 三处改动（相对老 subprocess 版本）：
 *   1. 入参改为接收 { session_id, sender_did, content, direction } 与 AttpRuntime，
 *      而非老的 st:{channelRuntime,cfg,webAppPort,token} 状态对象。
 *   2. reply.to 按方向分流：U2A → "attp:<sid>"（WS 广播）；A2A → 仅记录 agent 文本输出，
 *      **不自动反向回复**（发送方发完即无后续）。接收者 agent 是否回复由其提示词决定：
 *      需要回复时 agent 自行调用 ATTP MCP send_message 工具发起一条新 A2A。
 *   3. delivery.deliver 不再 POST /openclaw/reply（loopback HTTP），而是抽取出
 *      回复文本后按方向处理（U2A 走 deliverOutbound 广播；A2A 仅日志）。
 *
 * 该函数同时服务于：
 *   - U2A：浏览器 WS 消息（attp-server.ts WebUI 端口的 WS handler）→ direction "U2A"
 *   - A2A：远端 agent 的 receive_message（attp-server.ts Agent Server 端口验签后）→ direction "A2A"
 */

import { DEFAULT_ACCOUNT_ID } from "openclaw/plugin-sdk/account-id";
import { resolveInboundRouteEnvelopeBuilderWithRuntime } from "openclaw/plugin-sdk/inbound-envelope";
import type { AttpRuntime } from "./runtime.js";
import { deliverOutbound } from "./outbound.js";

/** 入站消息体（U2A 与 A2A 共用形状）。 */
export interface AttpInboundBody {
  session_id: string;
  sender_did: string;
  content: string;
  direction: "U2A" | "A2A";
}

/** 从 openclaw 回复 payload 中 best-effort 抽取文本（block / final / 原始串）。 */
function extractReplyText(payload: any): string | undefined {
  if (!payload) return undefined;
  if (typeof payload === "string") return payload;
  return payload.text ?? payload.body ?? payload.content ?? payload.rawText ?? undefined;
}

/**
 * 分发一条入站 ATTP 消息到 openclaw 的 channel-inbound 运行时（in-process）。
 *
 * 流程（与老 inbound.ts 一致）：
 *   1. resolveInboundRouteEnvelopeBuilderWithRuntime 解析路由（agentId + sessionKey）
 *      + 构造存储信封（storePath, body）；
 *   2. cr.channel.inbound.buildContext 组装上下文（reply.to 按方向分流）；
 *   3. cr.channel.inbound.run 驱动 agent turn —— 其 resolveTurn().delivery.deliver
 *      把 agent 的回复交给 deliverOutbound 做进程内出站路由。
 *
 * channelRuntime 必须已在 register 期由 setRuntime 注入（见 index.ts），否则抛错。
 */
export async function dispatchAttpInbound(
  b: AttpInboundBody,
  runtime: AttpRuntime,
): Promise<void> {
  if (!runtime.channelRuntime) {
    throw new Error("channelRuntime not captured (setRuntime not run yet)");
  }
  const cfg = runtime.cfg as any;
  const cr = runtime.channelRuntime;
  const sid = b.session_id;
  // reply 目标按方向分流：U2A 回浏览器 WS（attp:<sid>），A2A 回远端 agent（did:）。
  const replyTo = b.direction === "A2A" ? b.sender_did : `attp:${sid}`;
  const fromLabel = `attp:${sid}`;
  console.log(
    `[attp/inbound] dispatch ${b.direction} sid=${sid} sender=${b.sender_did} content="${String(b.content).slice(0, 60)}"`,
  );

  // 1. 路由解析 + 信封构造
  const { route, buildEnvelope } = resolveInboundRouteEnvelopeBuilderWithRuntime({
    cfg,
    channel: "attp",
    accountId: DEFAULT_ACCOUNT_ID,
    peer: { kind: "direct", id: sid },
    runtime: cr.channel,
    sessionStore: cfg?.session?.store,
  });
  const { storePath, body } = buildEnvelope({
    channel: "ATTP",
    from: fromLabel,
    timestamp: Date.now(),
    body: b.content,
  });

  // 2. 上下文（reply.to 按方向）
  // openclaw 的 sessionId 只给 provider 做缓存、不暴露给 LLM；而 MCP send_message 工具
  // 续接溯源链需要显式 session_id（并发安全）。故把 session_id 注入 agent 可见输入
  // （bodyForAgent），由 agent 在调用 send_message 时传入。rawBody/body 保持干净。
  const bodyForAgent = `[attp_session_id=${sid}]\n${b.content}`;
  const ctxPayload = cr.channel.inbound.buildContext({
    channel: "attp",
    accountId: DEFAULT_ACCOUNT_ID,
    from: fromLabel,
    sender: { id: b.sender_did, name: b.sender_did },
    conversation: { kind: "direct", id: sid },
    route: { agentId: route.agentId, accountId: DEFAULT_ACCOUNT_ID, routeSessionKey: route.sessionKey },
    reply: { to: replyTo },
    message: { rawBody: b.content, body, bodyForAgent, commandBody: b.content },
  });

  // 3. 驱动 turn —— delivery.deliver 走进程内 deliverOutbound
  await cr.channel.inbound.run({
    channel: "attp",
    accountId: DEFAULT_ACCOUNT_ID,
    raw: b,
    adapter: {
      ingest: () => ({
        id: sid,
        timestamp: Date.now(),
        rawText: b.content,
        textForAgent: b.content,
        textForCommands: b.content,
        raw: b,
      }),
      resolveTurn: () => ({
        cfg,
        channel: "attp",
        accountId: DEFAULT_ACCOUNT_ID,
        agentId: route.agentId,
        routeSessionKey: route.sessionKey,
        storePath,
        ctxPayload,
        recordInboundSession: cr.channel.session?.recordInboundSession,
        dispatchReplyWithBufferedBlockDispatcher: cr.channel.reply?.dispatchReplyWithBufferedBlockDispatcher,
        delivery: {
          deliver: async (payload: any) => {
            const text = extractReplyText(payload);
            if (!text) return;
            if (b.direction === "A2A") {
              // A2A 入站：不自动反向回复（对齐设计——发送方发完即无后续）。
              // 接收者 agent 是否回复完全由其提示词决定：若要回复，agent 自行调用
              // ATTP MCP send_message 工具发起一条新 A2A 消息。这里仅记录其文本输出。
              console.log(
                `[attp/inbound] A2A agent 产出文本（不自动回送；如需回复由 agent 经 MCP send_message 工具发起）: "${String(text).slice(0, 60)}"`,
              );
              return;
            }
            // U2A：agent 回复走 A2U（NodeMessage 广播给本会话浏览器 WS）
            console.log(
              `[attp/inbound] reply -> ${replyTo}: "${String(text).slice(0, 60)}"`,
            );
            await deliverOutbound(replyTo, text);
          },
          onError: (err: unknown) => console.error("[attp/inbound] reply delivery error:", err),
        },
        replyPipeline: {},
        record: {},
      }),
    },
  });
}
