import {
  createChannelPluginBase,
  createChatChannelPlugin,
  type OpenClawConfig,
} from "openclaw/plugin-sdk/channel-core";
import { DEFAULT_ACCOUNT_ID } from "openclaw/plugin-sdk/account-id";

import { readAttpConfig } from "./config.js";
import { supervisePython } from "./supervisor.js";

/**
 * Per-account runtime state. Populated by registerFull() in index.ts (which knows
 * the gateway port + generated webhook token) and consumed by the gateway/outbound
 * adapters here. openclaw guarantees registerFull runs before startAccount.
 */
export interface AttpRuntimeState {
  token: string;
  webhookUrl: string; // http://127.0.0.1:<gatewayPort>/attp/inbound
  webAppPort: number; // ATTP WebApp port for POST /openclaw/reply
  /** Captured in startAccount; the channel-inbound runtime (inbound/session/reply). */
  channelRuntime?: any;
  cfg?: any;
}

export const runtimeState: Record<string, AttpRuntimeState> = {};

const READY_POLL_ATTEMPTS = 30;
const READY_POLL_INTERVAL_MS = 500;

async function waitForWebAppReady(webAppPort: number, log: (m: string) => void): Promise<boolean> {
  for (let i = 0; i < READY_POLL_ATTEMPTS; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${webAppPort}/api/status`);
      const j: any = r.ok ? await r.json() : {};
      if (j.status === "active") return true;
    } catch {
      /* keep polling — adapter still starting */
    }
    await new Promise<void>((res) => setTimeout(res, READY_POLL_INTERVAL_MS));
  }
  log(`[attp] WebApp /api/status not active after ${READY_POLL_ATTEMPTS} polls`);
  return false;
}

// Build the chat-style plugin (config/setup/outbound), then ATTACH the gateway
// adapter explicitly. createChatChannelPlugin only forwards base/security/pairing/
// threading/outbound, so a `gateway` sibling would be silently dropped — spreading
// the result and adding `gateway` guarantees openclaw sees startAccount/stopAccount.
const chatPlugin = createChatChannelPlugin({
  base: createChannelPluginBase({
    id: "attp",
    config: {
      listAccountIds: () => [DEFAULT_ACCOUNT_ID],
      resolveAccount: (cfg: OpenClawConfig, accountId?: string | null) => {
        const c = readAttpConfig(cfg);
        return { accountId: accountId ?? DEFAULT_ACCOUNT_ID, ...c };
      },
      inspectAccount: (cfg: OpenClawConfig) => {
        const section = (cfg.channels as Record<string, any>)?.["attp"] ?? {};
        return {
          enabled: Boolean(section.pythonPath),
          configured: Boolean(section.pythonPath && section.configPath),
        };
      },
    },
    setup: {
      applyAccountConfig: ({ cfg, input }: { cfg: OpenClawConfig; input: Record<string, unknown> }) => ({
        ...cfg,
        channels: {
          ...(cfg.channels as object),
          attp: { ...(cfg.channels as Record<string, any>)?.["attp"], ...input },
        },
      }),
    },
  }),

  outbound: {
    attachedResults: {
      channel: "attp",
      // openclaw agent normal reply -> ATTP WebApp.send_message_to_user (A2U).
      // Session mapping: outbound `to` = "attp:<session_id>".
      sendText: async (params: { to: string; text: string }) => {
        const sid = String(params.to).replace(/^attp:/, "");
        const st = runtimeState[DEFAULT_ACCOUNT_ID];
        if (!st) throw new Error("attp channel not started (no runtime state)");
        const url = `http://127.0.0.1:${st.webAppPort}/openclaw/reply`;
        const r = await fetch(url, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            authorization: `Bearer ${st.token}`,
          },
          body: JSON.stringify({ session_id: sid, content: params.text }),
        });
        if (!r.ok) throw new Error(`/openclaw/reply HTTP ${r.status}`);
        return { messageId: sid };
      },
    },
  },
});

export const attpPlugin = {
  ...chatPlugin,
  gateway: {
    startAccount: async (ctx: any) => {
      const c = readAttpConfig(ctx.cfg as OpenClawConfig);
      const st = runtimeState[DEFAULT_ACCOUNT_ID];
      if (!st) {
        throw new Error("attp inbound route not registered before startAccount");
      }
      // channelRuntime + cfg are captured at register time via defineChannelPluginEntry's
      // setRuntime(api.runtime) + registerFull(api) — see index.ts. ctx.channelRuntime is
      // intentionally NOT used (it stays undefined without a runtime resolver).

      const args = [
        "-m", "attp.channels.openclaw",
        "--config", c.configPath,
        "--webhook", st.webhookUrl,
        "--token", st.token,
      ];
      // ctx.log is a ChannelLogSink object (.info/.warn/.error), not a function.
      // Be defensive: never let logging throw (it runs in stream handlers).
      const log = (m: string) => {
        try {
          const lg: any = ctx.log;
          if (lg && typeof lg.info === "function") lg.info(`[attp] ${m}`);
          else if (typeof lg === "function") lg(`[attp] ${m}`);
          else console.error("[attp]", m);
        } catch {
          /* swallow */
        }
      };

      // Spawn + supervise concurrently; abortSignal drives graceful stop.
      const supervise = supervisePython({
        pythonPath: c.pythonPath,
        args,
        abortSignal: ctx.abortSignal as AbortSignal,
        log,
        onFailed: () =>
          ctx.setStatus?.({ phase: "failed", detail: "ATTP process exhausted restart retries" }),
      });

      await waitForWebAppReady(c.webAppPort, log);
      ctx.setStatus?.({ phase: "running" });

      // Block for the channel lifetime; resolves when abortSignal fires.
      await supervise;
    },

    stopAccount: async () => {
      // ctx.abortSignal from startAccount drives supervisePython to SIGTERM the child.
    },
  },
};
