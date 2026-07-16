/**
 * A2A 收端 — 解析 + 验签 receive_message 请求。
 *
 * 从 python/attp/app/server.py 的 `receive_message` 处理器翻译而来。
 * Python 端通过 anp.openanp 的 @interface 装饰器自动完成 DID-wba 验签；
 * TS 侧将其拆为两个纯函数，便于宿主（openclaw / nanobot）自行接入：
 *
 *   - parseInboundRequest : 解析 JSON-RPC receive_message 体，抽取业务字段
 *   - verifyInbound       : 从 Signature-Input 的 keyid 反查发送方 DID →
 *                            解析 DID 文档 → 校验 RFC 9421 签名
 *
 * 接收侧的 JSON-RPC params 形状镜像 Task 4 (client.ts) 的 sendMessage：
 *   { sender_did, content, message_type, metadata: { NodeMessage, nonce?, protocol_url? } }
 *
 * Plan 2, Task 5。
 */

import { verifyHttpMessageSignature } from "./did-wba.js";

// ---------------------------------------------------------------------------
// 头部查找（大小写不敏感；did-wba.ts 内的同名助手未导出，此处内联一份）
// ---------------------------------------------------------------------------

function getHeaderCaseInsensitive(
  headers: Record<string, string>,
  name: string,
): string | undefined {
  const lower = name.toLowerCase();
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === lower) return headers[key];
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// parseInboundRequest
// ---------------------------------------------------------------------------

/**
 * 解析 receive_message 请求体后抽取出的业务字段。
 *
 * nodeMessage 保留为原始 dict（即 metadata.NodeMessage），
 * 调用方可按需用 NodeMessage.fromDict 进一步解析。
 * nonce / protocolUrl 同时回退到 NodeMessage 内同名字段，
 * 便于 Phase-1 回传回调直接使用。
 */
export interface InboundParsed {
  senderDid: string;
  content: string;
  messageType: string;
  /** metadata.NodeMessage 原始 dict（snake_case）。 */
  nodeMessage: any;
  /** metadata.nonce 或 NodeMessage.nonce。 */
  nonce?: string;
  /** metadata.protocol_url 或 NodeMessage.protocol_url。 */
  protocolUrl?: string;
  /** JSON-RPC 请求 id（响应需原样回显；扁平/缺省时为 undefined）。 */
  id?: any;
}

/**
 * 解析 receive_message 的 JSON-RPC 请求体并抽取业务字段。
 *
 * 同时兼容两种形状：
 *   - JSON-RPC 规范形式（canonical）：
 *       { jsonrpc, method:"receive_message", params:{ sender_did, content, message_type,
 *         metadata:{ NodeMessage, nonce?, protocol_url? } }, id }
 *   - 扁平形式（无 params 包装）：参数直接置于顶层。
 */
export function parseInboundRequest(bodyStr: string): InboundParsed {
  const body = JSON.parse(bodyStr) as any;
  // JSON-RPC 规范形式把参数放在 params；扁平形式则直接在顶层。
  const params = (body && body.params && typeof body.params === "object")
    ? body.params
    : body;
  const metadata = (params && params.metadata) || {};
  const nodeMessage = metadata.NodeMessage;

  return {
    senderDid: params.sender_did,
    content: params.content,
    // 规范键名 message_type（与 Python 端 @interface receive_message 形参一致）；
    // 同时容忍旧发送方仍写 type 的情况，作为非规范回退。
    messageType: params.message_type ?? params.type,
    nodeMessage,
    // 优先取 metadata 顶层；缺省时回退到 NodeMessage 内同名字段。
    nonce: metadata.nonce ?? nodeMessage?.nonce,
    protocolUrl: metadata.protocol_url ?? nodeMessage?.protocol_url,
    id: body?.id,
  };
}

// ---------------------------------------------------------------------------
// verifyInbound
// ---------------------------------------------------------------------------

export interface VerifyInboundParams {
  /** HTTP 方法（如 "POST"）。 */
  method: string;
  /** 完整请求 URL（@target-uri）。 */
  url: string;
  /** 请求头（键大小写不敏感查找）。 */
  headers: Record<string, string>;
  /** 原始请求体字节（用于 Content-Digest 校验）。 */
  body: Uint8Array<ArrayBuffer>;
  /**
   * 由发送方 DID 解析其 DID 文档。
   * 发送方 DID 从 Signature-Input 的 keyid（去掉 #fragment 前缀）取得。
   */
  resolveDidDoc: (senderDid: string) => Promise<any>;
  /**
   * 可选：调用方已知发送方 DID 时显式传入；缺省时由 Signature-Input 的 keyid 推导。
   * 当头部无法揭示 keyid 时以此作为兜底。
   */
  senderDid?: string;
}

/**
 * 从 Signature-Input 头的 keyid 提取发送方 DID。
 *
 * keyid 形如 `did:wba:h:agent#key-1`，其 `#` 前缀即为发送方 DID。
 * 找不到时返回 undefined。
 */
function extractSenderDidFromHeaders(
  headers: Record<string, string>,
): string | undefined {
  const sigInput = getHeaderCaseInsensitive(headers, "Signature-Input");
  if (!sigInput) return undefined;
  const match = /keyid="([^"]+)"/.exec(sigInput);
  if (!match) return undefined;
  const keyid = match[1];
  const hashIdx = keyid.indexOf("#");
  return hashIdx >= 0 ? keyid.slice(0, hashIdx) : keyid;
}

/**
 * 校验入站 A2A 请求的 DID-wba HTTP Message Signature。
 *
 * 流程：
 *   1. 确定发送方 DID —— 优先显式入参，否则从 Signature-Input 的 keyid 推导；
 *      两者都无则返回 false（无法解析 DID 文档）。
 *   2. resolveDidDoc(senderDid) 取得发送方 DID 文档。
 *   3. verifyHttpMessageSignature 校验 RFC 9421 签名。
 *
 * 失败一律返回 false（不抛），便于宿主统一做 401 处理。
 */
export async function verifyInbound(p: VerifyInboundParams): Promise<boolean> {
  try {
    const senderDid = p.senderDid ?? extractSenderDidFromHeaders(p.headers);
    if (!senderDid) {
      console.warn("[attp/verify] reject: no senderDid (Signature-Input keyid 解析失败)");
      return false;
    }

    let didDoc: any;
    try {
      didDoc = await p.resolveDidDoc(senderDid);
    } catch (e) {
      console.warn(
        `[attp/verify] reject: DID 文档解析失败 for ${senderDid}: ${(e as Error).message}`,
      );
      return false;
    }
    if (!didDoc) {
      console.warn(`[attp/verify] reject: 空的 DID 文档 for ${senderDid}`);
      return false;
    }

    const [ok, reason] = await verifyHttpMessageSignature(
      didDoc,
      p.method,
      p.url,
      p.headers,
      p.body,
    );
    if (!ok) {
      console.warn(
        `[attp/verify] reject: 签名校验失败 for ${senderDid}: ${reason}`,
      );
    }
    return ok;
  } catch (e) {
    console.warn(`[attp/verify] reject: 意外异常: ${(e as Error).message}`);
    return false;
  }
}
