/**
 * A2A 客户端 — 远程 agent 发现与消息发送。
 *
 * 从 python/attp/app/client.py 的 send_to_agent + anp.openanp.client.agent
 * (RemoteAgent.discover / RemoteAgent.call) 翻译而来。
 *
 *   - discoverAgent : 拉取 ad.json → OpenRPC → 抽取 receive_message 的 rpcUrl
 *   - sendMessage   : 构造 NodeMessage（镜像 client.py 的 hop 构造 + Phase-1 回传）
 *                     → 用 DID-wba 签名 → JSON-RPC POST 给对端 receive_message
 *
 * Plan 2, Task 4。
 */

import { randomUUID } from "node:crypto";
import { NodeMessage, RecordedHop } from "../core/message/event.js";
import { sendBackMessage } from "../core/message/back-sender.js";
import { generateHttpSignatureHeaders } from "./did-wba.js";
import type { AnyKey } from "../core/authentication/keys.js";

// ---------------------------------------------------------------------------
// 发现结果
// ---------------------------------------------------------------------------

export interface DiscoveredAgent {
  /** 对端 agent 的 DID（ad.did）。 */
  did: string;
  /** receive_message JSON-RPC 端点（method.servers[0].url）。 */
  rpcUrl: string;
  /** 对端 agent 名称（ad.name），可选。 */
  name?: string;
}

// ---------------------------------------------------------------------------
// discoverAgent
// ---------------------------------------------------------------------------

interface AdInterface {
  type?: string;
  protocol?: string;
  url?: string;
}

interface AdDocument {
  /** 规范字段（openclaw 自产 ad.json 用 did）。 */
  did?: string;
  /** anp 框架字段（nanobot 等 Python agent 把 DID 放在 identifier）。 */
  identifier?: string;
  name?: string;
  interfaces?: AdInterface[];
}

interface OpenRpcMethod {
  name?: string;
  servers?: { url?: string }[];
}

interface OpenRpcDocument {
  openrpc?: string;
  methods?: OpenRpcMethod[];
  /** 顶层 servers（nanobot 的 interface.json 只在此处声明 rpc 端点）。 */
  servers?: { url?: string }[];
}

function nonOk(res: { ok?: boolean; status: number; statusText?: string }, url: string): Error {
  return new Error(
    `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""} fetching ${url}`,
  );
}

/**
 * 发现远程 agent：fetch adUrl → 找到首个 StructuredInterface+openrpc 的 url
 * → fetch OpenRPC → 找到 receive_message 方法 → 返回其 rpcUrl。
 *
 * 简化自 agent.py:90-182：ATTP 只通过 receive_message 发送，故只抽取该端点。
 */
export async function discoverAgent(adUrl: string): Promise<DiscoveredAgent> {
  // 1. fetch ad.json
  const adResp = await fetch(adUrl);
  if (!adResp.ok) throw nonOk(adResp, adUrl);
  const ad = (await adResp.json()) as AdDocument;

  // 兼容两种 DID 字段：openclaw 自产用 did；anp 框架（nanobot 等）用 identifier。
  const did = ad.did ?? ad.identifier;
  if (!did) throw new Error(`ad.json at ${adUrl} has no 'did'/'identifier' field`);

  // 2. 找到首个 StructuredInterface + openrpc 接口 URL
  const interfaces = Array.isArray(ad.interfaces) ? ad.interfaces : [];
  const interfaceEntry = interfaces.find(
    (i) => i && i.type === "StructuredInterface" && i.protocol === "openrpc" && i.url,
  );
  if (!interfaceEntry || !interfaceEntry.url) {
    throw new Error(`No OpenRPC interface URL found at ${adUrl}`);
  }

  // 3. fetch OpenRPC 文档
  const rpcResp = await fetch(interfaceEntry.url);
  if (!rpcResp.ok) throw nonOk(rpcResp, interfaceEntry.url);
  const openrpc = (await rpcResp.json()) as OpenRpcDocument;

  // 4. 找到 receive_message 方法 → rpc 端点。
  //    兼容两种 servers 位置：openclaw 自产 openrpc 在方法内声明；anp 框架
  //    （nanobot 的 interface.json）只在顶层声明。方法内优先，回退顶层。
  const methods = Array.isArray(openrpc.methods) ? openrpc.methods : [];
  const method = methods.find((m) => m && m.name === "receive_message");
  if (!method) {
    throw new Error(
      `No 'receive_message' method in OpenRPC at ${interfaceEntry.url}`,
    );
  }
  const methodServers = Array.isArray(method.servers) ? method.servers : [];
  const topServers = Array.isArray(openrpc.servers) ? openrpc.servers : [];
  const rpcUrl = methodServers[0]?.url ?? topServers[0]?.url;
  if (!rpcUrl) {
    throw new Error(
      `'receive_message' has no servers[0].url (method or top-level) at ${interfaceEntry.url}`,
    );
  }

  return { did, rpcUrl, name: ad.name };
}

// ---------------------------------------------------------------------------
// sendMessage
// ---------------------------------------------------------------------------

export interface SendMessageParams {
  /** receive_message 的 JSON-RPC 端点（来自 discoverAgent.rpcUrl）。 */
  rpcUrl: string;
  /** 本机 DID 文档（用于 DID-wba 签名）。 */
  didDocument: any;
  /** 本机私钥（LoadedKey / AnyKey）。 */
  privateKey: AnyKey;
  /** 发送方 DID（本机 agent）。 */
  senderDid: string;
  /** 目标 DID（对端 agent）。 */
  targetDid: string;
  /** 消息内容。 */
  content: string;
  /** 消息类型，默认 "agent_request"。 */
  messageType?: string;
  /** 协议节点地址；提供时触发 Phase-1 回传（best-effort）+ 写入 NodeMessage.protocol_url。 */
  protocolUrl?: string;
  /**
   * 预构造的 RecordedHop（续链时由调用方经 AgentTracer.appendHop 生成并签名）。
   * 提供时直接使用（跳过 genesis 构造）——session_id / hop_count / sig 都取自它；
   * 缺省时本函数构造 genesis hop（[0,0]，session_id 现场生成，未签名）。
   */
  recordedHop?: RecordedHop;
  /** 预留：外部 AgentTracer（当前未使用，hop 由本函数直接构造）。 */
  agentTracer?: any;
}

/** 生成 uuid4 hex（无连字符），对齐 Python 的 uuid.uuid4().hex。 */
function uuidHex(): string {
  return randomUUID().replace(/-/g, "");
}

/**
 * 向远程 agent 发送消息（JSON-RPC receive_message）。
 *
 * 镜像 client.py:198-293 的 send_to_agent：
 *   1. 构造 RecordedHop（对应 append_hop 的无前驱分支：hop_count=[0,0]、
 *      timestamp=now、session_id 现场生成）；
 *   2. 包装 NodeMessage 并用发送方私钥签名（nodeMsg.signContent）；
 *   3. 若提供 protocolUrl，先做 Phase-1 回传（best-effort，失败不阻断）；
 *   4. 用 DID-wba HTTP Message Signatures 签名后 POST JSON-RPC。
 *
 * 时序与 Python 一致：先回传协议节点，再发给对端 B。
 */
export async function sendMessage(p: SendMessageParams): Promise<any> {
  const messageType = p.messageType ?? "agent_request";
  const protocolUrl = p.protocolUrl ?? "";

  // ---- 1. RecordedHop：续链（调用方预构造+签名）或 genesis（无前驱）----
  const nonce = uuidHex();
  const recordedHop =
    p.recordedHop ??
    new RecordedHop({
      sessionId: uuidHex(),
      senderDid: p.senderDid,
      targetDid: p.targetDid,
      content: p.content,
      timestamp: Date.now() / 1000,
      hopCount: [0, 0],
    });

  // ---- 2. NodeMessage + 发送方私钥签名 ----
  const nodeMsg = new NodeMessage({
    protocolUrl,
    nonce,
    recordedHop,
  });
  await nodeMsg.signContent(p.privateKey);

  // ---- 3. Phase-1 回传（best-effort，非阻断）----
  // 对齐 client.py:260-269：仅当 protocolUrl 非空时回传；失败只记录不抛出。
  if (protocolUrl) {
    try {
      await sendBackMessage({
        protocolUrl,
        nodeDid: p.senderDid,
        nonce,
        recordedHop,
        privateKey: p.privateKey,
      });
    } catch (e) {
      // best-effort：回传失败不阻断 A2A 发送（与 Python 一致地降级）
      // 注：client.py 在回传失败时返回错误串；此处保持发送流程继续，
      // 因为 TS 端 sendMessage 是无状态函数，向上抛出会丢失 A2A 语义。
      console.warn(
        `[attp/client] Phase-1 back-propagation to ${protocolUrl} failed:`,
        (e as Error).message,
      );
    }
  }

  // ---- 4. JSON-RPC receive_message 请求体 ----
  // 注意：params.message_type 必须与 Python 端 @interface receive_message 的形参名
  // (sender_did, content, message_type, metadata) 一致，否则 Python 因缺少必填的
  // message_type 形参而返回 JSON-RPC 错误（TS→Python A2A 跨语言兼容要点）。
  const rpcBody = {
    jsonrpc: "2.0",
    method: "receive_message",
    params: {
      sender_did: p.senderDid,
      content: p.content,
      message_type: messageType,
      metadata: {
        NodeMessage: nodeMsg.toDict(),
      },
    },
    id: 1,
  };

  const bodyBytes = new TextEncoder().encode(JSON.stringify(rpcBody));
  const authHeaders = await generateHttpSignatureHeaders({
    didDocument: p.didDocument,
    requestUrl: p.rpcUrl,
    requestMethod: "POST",
    body: bodyBytes,
    privateKey: p.privateKey,
  });

  // ---- 5. POST ----
  const resp = await fetch(p.rpcUrl, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...authHeaders,
    },
    body: JSON.stringify(rpcBody),
  });
  if (!resp.ok) {
    throw new Error(
      `receive_message request to ${p.rpcUrl} failed: HTTP ${resp.status}${resp.statusText ? ` ${resp.statusText}` : ""}`,
    );
  }
  return resp.json();
}
