import { randomBytes } from "node:crypto";
import { defineChannelPluginEntry } from "openclaw/plugin-sdk/channel-core";
import { DEFAULT_ACCOUNT_ID } from "openclaw/plugin-sdk/account-id";

import { attpPlugin, runtimeState } from "./src/channel.js";
import { registerAttpInboundRoute } from "./src/inbound.js";

export default defineChannelPluginEntry({
  id: "attp",
  name: "ATTP",
  description: "ATTP agent-mesh channel (WebUI + cross-framework A2A + tools)",
  plugin: attpPlugin,
  // openclaw calls setRuntime(api.runtime) at register time (before registerFull).
  // api.runtime is the PluginRuntime exposing .channel.inbound.{buildContext,run},
  // .channel.session.recordInboundSession, .channel.reply.* — needed by the webhook
  // handler to dispatch inbound turns. ctx.channelRuntime stays undefined without this.
  setRuntime(runtime: any) {
    if (!runtimeState[DEFAULT_ACCOUNT_ID]) {
      runtimeState[DEFAULT_ACCOUNT_ID] = { token: "", webhookUrl: "", webAppPort: 8001 };
    }
    runtimeState[DEFAULT_ACCOUNT_ID].channelRuntime = runtime;
  },
  registerFull(api: any) {
    const cfg = api.config as Record<string, any>;
    const gatewayPort = cfg?.gateway?.port ?? 18789;
    const webAppPort = cfg?.channels?.attp?.webAppPort ?? 8001;
    const token = randomBytes(16).toString("hex");

    runtimeState[DEFAULT_ACCOUNT_ID] = {
      ...(runtimeState[DEFAULT_ACCOUNT_ID] ?? {}),
      token,
      webhookUrl: `http://127.0.0.1:${gatewayPort}/attp/inbound`,
      webAppPort: Number(webAppPort),
      cfg,
    };

    registerAttpInboundRoute(api, token);
  },
});
