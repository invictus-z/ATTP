import { defineChannelPluginEntry } from "openclaw/plugin-sdk/channel-core";
import { runtime } from "./src/runtime.js";
import { attpPlugin } from "./src/channel.js";

export default defineChannelPluginEntry({
  id: "attp",
  name: "ATTP",
  description: "ATTP agent-mesh channel (WebUI + cross-framework A2A + tools), native three-port in-process",
  plugin: attpPlugin,
  // openclaw calls setRuntime(api.runtime) at register time (before registerFull).
  // api.runtime exposes .channel.inbound.{buildContext,run}, .channel.session.*, .channel.reply.*
  // — needed by dispatchAttpInbound (driven from attp-server's onInbound).
  setRuntime(rt: any) {
    runtime.channelRuntime = rt;
  },
  // 三端口改造后：HTTP 路由（WebUI/A2A）与 send_message 工具改由 startAccount 期
  // 拉起的 attp-server / mcp-node 提供（独立端口、host-agnostic）；registerFull
  // 不再在 openclaw gateway 上注册任何路由或工具，仅记下配置根。
  registerFull(api: any) {
    runtime.cfg = api.config;
  },
});
