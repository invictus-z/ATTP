/**
 * 工具桥 —— 把 ATTP 的 A2A 发送能力暴露成 openclaw 风格的 tool 执行体。
 *
 * openclaw 的 tool 注册（Plan 3 时代的 channels/openclaw/src/tools.ts，已在 Plan 4
 * 三端口改造中删除——MCP 工具改由 app/mcp-node.ts 提供）需要一个
 * 与宿主无关、无运行时状态的纯函数：给定运行时 agent 的 didDocument / privateKey /
 * senderDid 与对端 adUrl，完成「发现 + 发送」并返回 openclaw 约定的 tool result
 * 形状。本模块即该桥：
 *
 *   - 入参 SendMessageArgs：对端 adUrl + 目标 DID + content + 本机身份材料
 *   - 出参 ToolResult：openclaw tool result（content[].text + details 元数据）
 *
 * 本函数只是 discoverAgent + sendMessage 的薄封装，不引入新的业务逻辑——
 * 真正的 hop 构造、DID-wba 签名、JSON-RPC POST 都在 client.ts 内完成。
 *
 * Plan 2, Task 7。
 */

import { discoverAgent, sendMessage } from "./client.js";
import type { AnyKey } from "../core/authentication/keys.js";
import type { RecordedHop } from "../core/message/event.js";

/**
 * executeSendMessage 的入参。
 *
 * didDocument / privateKey / senderDid 来自运行时 agent（由 channel 插件
 * 从 AgentConfig 装载后注入），targetDid / adUrl / content 描述本次投递。
 */
export interface SendMessageArgs {
  /** 目标 agent 的 DID。 */
  targetDid: string;
  /** 目标 ad.json URL（对端 DID 文档发现入口）。 */
  adUrl: string;
  /** 消息内容。 */
  content: string;
  /** 本机 DID 文档（用于 DID-wba 签名）。 */
  didDocument: any;
  /** 本机私钥（LoadedKey / AnyKey）。 */
  privateKey: AnyKey;
  /** 发送方 DID（本机 agent）。 */
  senderDid: string;
  /** 消息类型，默认 "agent_request"。 */
  messageType?: string;
  /** 协议节点 URL；提供时触发 Phase-1 回传（best-effort）。 */
  protocolUrl?: string;
  /**
   * 预构造+签名的 RecordedHop（续链用，由调用方经 AgentTracer.appendHop 生成）。
   * 提供时透传给 sendMessage 续链；缺省时 sendMessage 构造 genesis。
   */
  recordedHop?: RecordedHop;
}

/**
 * openclaw tool result 形状。
 *
 * content 为文本块数组（与 openclaw / MCP tool 返回一致），
 * details 携带供宿主后续使用的结构化元数据（目标 DID、实际 rpcUrl）。
 */
export interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, unknown>;
}

/**
 * 执行 send_message 工具：发现对端 → 发送 A2A 消息 → 返回 openclaw tool result。
 *
 * 流程：
 *   1. discoverAgent(adUrl)：拉 ad.json + openrpc.json，得到 receive_message 的 rpcUrl
 *   2. sendMessage(...)：构造 NodeMessage + DID-wba 签名 + JSON-RPC POST
 *   3. 返回 { content:[{type:"text", text:`sent to <targetDid>`}], details:{ targetDid, rpcUrl } }
 */
export async function executeSendMessage(
  a: SendMessageArgs,
): Promise<ToolResult> {
  const peer = await discoverAgent(a.adUrl);
  await sendMessage({
    rpcUrl: peer.rpcUrl,
    didDocument: a.didDocument,
    privateKey: a.privateKey,
    senderDid: a.senderDid,
    targetDid: a.targetDid,
    content: a.content,
    messageType: a.messageType ?? "agent_request",
    protocolUrl: a.protocolUrl,
    recordedHop: a.recordedHop,
  });
  return {
    content: [{ type: "text", text: `sent to ${a.targetDid}` }],
    details: {
      targetDid: a.targetDid,
      rpcUrl: peer.rpcUrl,
    },
  };
}
