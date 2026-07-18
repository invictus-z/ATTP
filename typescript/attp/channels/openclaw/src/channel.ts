/**
 * openclaw 渠道插件本体 —— Plan 4 三端口改造版。
 *
 * 即 `attpPlugin`：base（配置/账户发现）+ outbound（agent 回复 → deliverOutbound）
 * + gateway（startAccount 拉起 ATTP 三端口服务并阻塞至 abortSignal）。
 *
 * 相对 Plan 3 时代的 gateway-routes 设计（WebUI/A2A 走 openclaw gateway 端口、
 * send_message 走 registerTool）：
 *   - 不再在 openclaw gateway 上注册 HTTP 路由 / 工具；
 *   - startAccount 在进程内拉起 host-agnostic 的三端口服务：
 *       (1) attp-server：WebUI 端口（NodeMessage WS + 可选静态）
 *                          + Agent Server 端口（DID-wba A2A receive + ad.json/openrpc）；
 *       (2) mcp-node   ：MCP tools 端口（send_message over SSE）。
 *     两端服务各自独立的网络身份，让 ATTP 在 openclaw 内仍保留三端口拓扑。
 *   - 入站消息经 attp-server 的 onInbound → dispatchAttpInbound 驱动 agent turn；
 *   - 出站仍由 deliverOutbound 按 `attp:<sid>` / `did:<peer>` 前缀分流。
 */

import {
  createChatChannelPlugin,
  createChannelPluginBase,
  type OpenClawConfig,
} from "openclaw/plugin-sdk/channel-core";
import { DEFAULT_ACCOUNT_ID } from "openclaw/plugin-sdk/account-id";
import { loadPrivateKeyPem } from "../../../core/authentication/keys.js";
import { AgentTracer } from "../../../core/agent-tracer.js";
import { startAttpServer, type AttpServerHandle } from "../../../app/attp-server.js";
import { startMcpNode, type McpNodeHandle } from "../../../app/mcp-node.js";
import { readChannelConfig } from "./config.js";
import { runtime } from "./runtime.js";
import { dispatchAttpInbound } from "./inbound.js";
import { readFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

/** 展开 `~` / `~/` 为用户 home 目录；其余路径原样返回。 */
const expandHome = (p: string): string => {
  if (!p) return p;
  if (p === "~") return os.homedir();
  if (p.startsWith("~/") || p.startsWith("~\\")) {
    return path.join(os.homedir(), p.slice(1));
  }
  return p;
};

/** 读 UTF-8 文本文件（兼容 ~ 展开）。 */
function readFileSyncUtf8(p: string): string {
  return readFileSync(expandHome(p), "utf8");
}

// base + outbound：createChatChannelPlugin 只转发 base/security/pairing/threading/outbound，
// 故把 gateway 作为兄弟字段显式附加（老版同款手法）。
const chatPlugin = createChatChannelPlugin({
  base: createChannelPluginBase({
    id: "attp",
    config: {
      listAccountIds: () => [DEFAULT_ACCOUNT_ID],
      resolveAccount: (_cfg: OpenClawConfig, accountId?: string | null) => ({
        accountId: accountId ?? DEFAULT_ACCOUNT_ID,
      }),
      inspectAccount: (cfg: OpenClawConfig) => {
        const section = (cfg as any).channels?.attp ?? {};
        return {
          enabled: Boolean(section.config_path),
          configured: Boolean(section.config_path),
        };
      },
    },
  }),

  outbound: {
    attachedResults: {
      channel: "attp",
      // openclaw agent 的主动/工具回复（outbound.attachedResults.sendText）→ in-process 路由。
      // 动态 import 以避免 channel.ts 被模块图过早拉入 app/client（及其 crypto 依赖）。
      sendText: async ({ to, text }: { to: string; text: string }) => {
        const { deliverOutbound } = await import("./outbound.js");
        return deliverOutbound(to, text);
      },
    },
  },
});

// 三端口服务的当前句柄（由 startAccount 注入、stopAccount/abort 清理）。
let serverHandle: AttpServerHandle | undefined;
let mcpHandle: McpNodeHandle | undefined;

export const attpPlugin = {
  ...chatPlugin,
  gateway: {
    /**
     * 启动账户：装载身份 → 拉起 attp-server（WebUI + Agent Server）+ mcp-node
     * → 阻塞至 abortSignal 触发，再 best-effort 关闭两端服务。
     *
     * attp-server 启动时把 WsHub 写入 runtime.hub（A2U 出站依赖）；
     * mcp-node 的 send_message 工具 lazy 读取 runtime 身份，故启动顺序无强约束。
     */
    startAccount: async (ctx: any) => {
      // ctx.log 是 ChannelLogSink 对象（.info/.warn/.error），非函数；防御式封装，绝不因日志抛错。
      const log = (msg: string) => {
        try {
          const lg: any = ctx.log;
          if (lg && typeof lg.info === "function") lg.info(`[attp] ${msg}`);
          else if (typeof lg === "function") lg(`[attp] ${msg}`);
          else console.log(`[attp] ${msg}`);
        } catch {
          /* swallow */
        }
      };
      try {
        const ch = await readChannelConfig(ctx.cfg);
        if (!ch.enabled) {
          log("channel disabled (channels.attp.enabled=false); skipping");
          return;
        }
        const a = ch.agent;

        runtime.agentConfig = a;
        runtime.sessionTraces = new Map();
        log(`loading identity did=${a.did} key=${a.didKeyPath}`);
        runtime.privateKey = await loadPrivateKeyPem(readFileSyncUtf8(a.didKeyPath));
        runtime.didDocument = JSON.parse(readFileSyncUtf8(a.didDocPath));
        runtime.tracer = new AgentTracer();
        runtime.abortSignal = ctx.abortSignal;

        // 预发现 nodeAds：读取每个 ad.json 的 DID（did/identifier）→ 建立 DID→adUrl 注册表。
        // A2A 发送（outbound / MCP send_message）优先命中此表，避免对本地/未托管 DID
        // 走 didToAdUrl 推导出不可达 URL（如 nanobot 只在 localhost 提供服务）。
        // best-effort：单个 nodeAds 不可达不阻断启动。
        runtime.peerRegistry = new Map();
        const nodeAds = a.nodeAds ?? [];
        if (nodeAds.length > 0) log(`pre-discovering ${nodeAds.length} nodeAds(s)`);
        for (const adUrl of nodeAds) {
          try {
            const resp = await fetch(adUrl);
            if (!resp.ok) {
              log(`nodeAds ${adUrl} -> HTTP ${resp.status}, skipped`);
              continue;
            }
            const ad = await resp.json();
            const peerDid: string | undefined = ad?.did ?? ad?.identifier;
            if (peerDid) {
              runtime.peerRegistry.set(peerDid, adUrl);
              log(`peer ${peerDid} -> ${adUrl}`);
            } else {
              log(`nodeAds ${adUrl} has no did/identifier, skipped`);
            }
          } catch (e) {
            log(`nodeAds ${adUrl} pre-discover failed: ${(e as Error).message}`);
          }
        }

        // 1) WebUI + Agent Server（NodeMessage WS + DID-wba A2A + ad.json/openrpc 发现）
        log(
          `starting WebUI :${a.webAppPort} + Agent Server :${a.agentServerPort} (publicAgentUrl=${a.publicAgentUrl})`,
        );
        const server = await startAttpServer({
          webPort: a.webAppPort,
          agentPort: a.agentServerPort,
          publicAgentUrl: a.publicAgentUrl,
          runtime,
          onInbound: (m) => dispatchAttpInbound(m, runtime),
        });
        serverHandle = server;

        // 2) MCP tools node（send_message over SSE）
        log(`starting MCP node :${a.toolPort}`);
        const mcp = await startMcpNode(runtime, a.toolPort);
        mcpHandle = mcp;

        ctx.setStatus?.({ phase: "running" });
        log(
          `running: WebUI :${server.webPort} / AgentServer :${server.agentPort} / MCP :${mcp.port}`,
        );

        // 阻塞至 abortSignal；之后 best-effort 关闭两端服务。
        await new Promise<void>((resolve) => {
          ctx.abortSignal?.addEventListener("abort", () => resolve(), { once: true });
        });
        log("abort signal received; closing servers");
        await Promise.allSettled([server.close(), mcp.close()]);
        serverHandle = undefined;
        mcpHandle = undefined;
      } catch (e) {
        log(`startAccount FAILED: ${(e as Error).message}`);
        ctx.setStatus?.({ phase: "failed", detail: (e as Error).message });
        throw e;
      }
    },

    /**
     * 停止账户：abortSignal 已在 startAccount 尾部驱动服务关闭；这里只清 runtime 引用。
     */
    stopAccount: async () => {
      runtime.hub = undefined;
      runtime.tracer = undefined;
      runtime.privateKey = undefined;
      runtime.didDocument = undefined;
    },
  },
};
