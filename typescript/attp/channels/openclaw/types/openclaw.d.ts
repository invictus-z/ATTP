/**
 * Local type shim for the openclaw plugin-sdk.
 *
 * `@openclaw/plugin-sdk` is a private workspace package (version "0.0.0-private")
 * and the published `openclaw` package excludes most .d.ts, so an external plugin
 * cannot install real types today. These declarations mirror the DOCUMENTED surface
 * (docs/plugins/sdk-channel-plugins.md, sdk-channel-inbound.md, sdk-entrypoints.md)
 * loosely (`any` at SDK seams). openclaw resolves `openclaw/plugin-sdk/*` from its
 * own installation at runtime. Replace this shim with real types once openclaw
 * publishes a public plugin-sdk types package.
 */
declare module "openclaw/plugin-sdk/channel-core" {
  export interface OpenClawConfig {
    channels?: Record<string, any>;
    gateway?: { port?: number | string };
    agents?: any;
    [key: string]: any;
  }
  export function defineChannelPluginEntry(opts: any): any;
  export function defineSetupPluginEntry(plugin: any): any;
  export function createChatChannelPlugin(opts: any): any;
  export function createChannelPluginBase(opts: any): any;
}

declare module "openclaw/plugin-sdk/account-id" {
  export const DEFAULT_ACCOUNT_ID: string;
}

declare module "openclaw/plugin-sdk/channel-plugin-common" {
  import type { OpenClawConfig } from "openclaw/plugin-sdk/channel-core";
  export interface OpenClawPluginApi {
    config: OpenClawConfig;
    registerHttpRoute(opts: {
      path: string;
      auth?: string;
      /** "prefix" matches URL path prefixes; default/exact matches the full path. */
      match?: "prefix" | "exact";
      handler: (req: any, res: any) => Promise<boolean | void> | boolean | void;
      /** WebSocket upgrade handler (see feishu/googlechat/canvas patterns). */
      handleUpgrade?: (req: any, socket: any, head: any) => void;
    }): void;
    registerTool(
      tool: {
        name: string;
        label?: string;
        description?: string;
        parameters: any;
        execute: (args: any, ctx: any) => Promise<any> | any;
      },
      meta?: { name: string },
    ): void;
  }
}

declare module "openclaw/plugin-sdk/channel-inbound" {
  export function buildChannelInboundEventContext(params: any): Promise<any>;
  export function runChannelInboundEvent(params: any): Promise<any>;
}

declare module "openclaw/plugin-sdk/inbound-envelope" {
  export function resolveInboundRouteEnvelopeBuilderWithRuntime(params: any): {
    route: { agentId: string; accountId?: string; sessionKey: string; mainSessionKey?: string };
    buildEnvelope: (p: any) => { storePath: string; body: string };
  };
}
