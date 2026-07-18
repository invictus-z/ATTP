import type { WsHub } from "../../../app/web.js";
import type { AgentTracer } from "../../../core/agent-tracer.js";
import type { LoadedKey } from "../../../core/authentication/keys.js";
import type { AgentConfig } from "../../../app/config.js";

/** 单会话溯源轨迹：U2A/A2A 入站时存；A2U/A2A-out 出站时 appendHop 续链用。 */
export interface SessionTrace {
  protocolUrl: string;
  /** snake_case recorded_hop dict（NodeMessage.recorded_hop）。 */
  recordedHop: any;
}

/** 进程内单账户共享状态：register 期注入 channelRuntime + cfg；startAccount 期注入 hub/tracer/key/身份。 */
export interface AttpRuntime {
  channelRuntime?: any;
  cfg?: any;
  agentConfig?: AgentConfig;
  /** WsHub 由 attp-server 启动时注入（同时挂在 server handle 上）。 */
  hub?: WsHub;
  tracer?: AgentTracer;
  privateKey?: LoadedKey;
  didDocument?: any;
  abortSignal?: AbortSignal;
  /** 每 session 的溯源轨迹：入站时 set，出站续链时读 + 更新。startAccount 期初始化为 new Map()。 */
  sessionTraces?: Map<string, SessionTrace>;
  /**
   * 已知对端 DID → ad.json URL 映射：startAccount 期由 nodeAds 预发现填充。
   * A2A 发送（outbound / MCP send_message）优先命中此表，未命中再回退 didToAdUrl 推导。
   */
  peerRegistry?: Map<string, string>;
}

export const runtime: AttpRuntime = {};
