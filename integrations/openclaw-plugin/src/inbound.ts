import type { OpenClawPluginApi } from "openclaw/plugin-sdk/channel-plugin-common";
import { DEFAULT_ACCOUNT_ID } from "openclaw/plugin-sdk/account-id";
import { resolveInboundRouteEnvelopeBuilderWithRuntime } from "openclaw/plugin-sdk/inbound-envelope";
import { runtimeState } from "./channel.js";

interface AttpInboundBody {
  session_id: string;
  sender_did: string;
  content: string;
  direction: "U2A" | "A2A";
}

/**
 * Register POST /attp/inbound on the gateway HTTP server. ATTP (the Python adapter)
 * posts inbound messages here — both U2A (user via WebApp) and A2A (remote agent via
 * ATTPServer). We dispatch each through openclaw's channel-inbound runtime so the
 * gateway agent handles it; the agent's reply is delivered back via delivery.deliver
 * -> POST /openclaw/reply -> WebApp.send_message_to_user.
 *
 * Pattern ported from extensions/googlechat/src/monitor.ts (buildContext + run + a
 * resolveTurn that routes + delivers). ctx.channelRuntime is captured in
 * gateway.startAccount (see channel.ts) and stored in runtimeState.
 */
export function registerAttpInboundRoute(api: OpenClawPluginApi, token: string): void {
  api.registerHttpRoute({
    path: "/attp/inbound",
    auth: "plugin", // plugin-managed auth: we verify the bearer token ourselves
    handler: async (req, res) => {
      const auth = (req.headers as Record<string, string | undefined>).authorization ?? "";
      if (token && auth !== `Bearer ${token}`) {
        res.statusCode = 401;
        res.end("unauthorized");
        return true;
      }
      let body: AttpInboundBody;
      try {
        body = await readJson(req);
      } catch {
        res.statusCode = 400;
        res.end("invalid json");
        return true;
      }
      const st = runtimeState[DEFAULT_ACCOUNT_ID];
      // Acknowledge immediately (ATTP drops on failure anyway); log dispatch errors.
      void dispatchAttpInbound(body, st)
        .catch((e) => console.error("[attp] inbound dispatch failed:", e));
      res.statusCode = 200;
      res.end("ok");
      return true;
    },
  });
}

async function readJson(req: any): Promise<AttpInboundBody> {
  const chunks: Buffer[] = [];
  for await (const chunk of req as AsyncIterable<Buffer>) {
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as AttpInboundBody;
}

async function postReply(webAppPort: number, token: string, sessionId: string, text: string): Promise<void> {
  const r = await fetch(`http://127.0.0.1:${webAppPort}/openclaw/reply`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({ session_id: sessionId, content: text }),
  });
  if (!r.ok) console.error(`[attp] /openclaw/reply HTTP ${r.status}`);
}

/** Best-effort reply-text extraction from an openclaw reply payload (block/final). */
function extractReplyText(payload: any): string | undefined {
  if (!payload) return undefined;
  if (typeof payload === "string") return payload;
  return payload.text ?? payload.body ?? payload.content ?? payload.rawText ?? undefined;
}

export async function dispatchAttpInbound(
  b: AttpInboundBody,
  st: { channelRuntime?: any; cfg?: any; webAppPort: number; token: string } | undefined,
): Promise<void> {
  if (!st?.channelRuntime) {
    throw new Error("channelRuntime not captured (gateway.startAccount not run yet)");
  }
  const cfg = st.cfg as any;
  const cr = st.channelRuntime;
  const sid = b.session_id;
  const fromLabel = `attp:${sid}`;

  // Resolve route (agentId + routeSessionKey) + envelope (storePath, body) from bindings.
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

  const ctxPayload = cr.channel.inbound.buildContext({
    channel: "attp",
    accountId: DEFAULT_ACCOUNT_ID,
    from: fromLabel,
    sender: { id: b.sender_did, name: b.sender_did },
    conversation: { kind: "direct", id: sid },
    route: { agentId: route.agentId, accountId: DEFAULT_ACCOUNT_ID, routeSessionKey: route.sessionKey },
    reply: { to: fromLabel },
    message: { rawBody: b.content, body, bodyForAgent: b.content, commandBody: b.content },
  });

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
            if (text) await postReply(st.webAppPort, st.token, sid, text);
          },
          onError: (err: unknown) => console.error("[attp] reply delivery error:", err),
        },
        replyPipeline: {},
        record: {},
      }),
    },
  });
}
