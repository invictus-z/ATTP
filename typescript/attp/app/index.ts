/**
 * app 层聚合出口 —— host-agnostic Agent SDK 的对外门面。
 *
 * 这里只做 re-export，便于 Plan 3 的 channel 插件（channels/openclaw/src/...）
 * 用一条 import 拿到完整的 app 层 API：
 *
 *   import { loadAgentConfig, discoverAgent, sendMessage, executeSendMessage, ... } from "@attp/app";
 *
 * 注意：channel 插件通过源码树内的 **相对路径** 引用本层，不经过 package.json 的
 * subpath exports——故此处不新增 package.json 子路径导出。app/index.ts 仅作为
 * app 层内部的聚合点与类型 barrel。
 *
 *   - config   : AgentConfig 字段选取器
 *   - did-wba  : RFC 9421 HTTP Message Signatures（签/验）+ RFC 9530 Content-Digest
 *   - client   : A2A 发送（discoverAgent + sendMessage）
 *   - server   : A2A 收端（parseInboundRequest + verifyInbound）
 *   - web      : WebSocket hub（WsHub + parseInboundNodeMessage + nodeMessageFrame）
 *   - tools    : openclaw 风格 tool 执行体（executeSendMessage）
 *
 * Plan 2, Task 7。
 */

export { loadAgentConfig, type AgentConfig } from "./config.js";
export {
  generateHttpSignatureHeaders,
  verifyHttpMessageSignature,
  buildContentDigest,
  verifyContentDigest,
} from "./did-wba.js";
export {
  discoverAgent,
  sendMessage,
  type DiscoveredAgent,
  type SendMessageParams,
} from "./client.js";
export {
  parseInboundRequest,
  verifyInbound,
  type InboundParsed,
  type VerifyInboundParams,
} from "./server.js";
export { WsHub, parseInboundNodeMessage, nodeMessageFrame, type WsLike, type InboundNodeMessage } from "./web.js";
export {
  executeSendMessage,
  type SendMessageArgs,
  type ToolResult,
} from "./tools.js";
