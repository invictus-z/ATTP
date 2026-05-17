/**
 * ATTP 协议消息构造与发送 — User 端核心逻辑。
 *
 * 职责：
 *   - 构造签名后的 NodeMessage（Phase 1：随 WS 消息发送给 Agent）
 *   - 构造签名后的 BackMessage 并 HTTP POST 到协议节点（Phase 2：回传）
 *   - 解析收到的 ATTP 格式消息
 */

import { RecordedHop, NodeMessage, BackMessage } from '@attp/core';
import { apiFetch } from '../transport';

// ---- Nonce 生成 ----

function generateNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ---- Phase 1: 构造 NodeMessage ----

export interface BuildNodeMessageParams {
  sessionId: string;
  userDid: string;
  targetDid: string;
  content: string;
  protocolUrl: string;
  privateKey: CryptoKey;
}

export interface BuildNodeMessageResult {
  nodeMessage: NodeMessage;
  nonce: string;
  recordedHop: RecordedHop;
}

/**
 * 构造签名后的 NodeMessage。
 *
 * 流程：
 *   1. 创建 RecordedHop
 *   2. 使用私钥签名 contentHash → sigContent
 *   3. 组装 NodeMessage（protocolUrl + nonce + recordedHop）
 *
 * @returns NodeMessage 对象、nonce 和 recordedHop（供后续 BackMessage 使用）
 */
export async function buildNodeMessage(
  params: BuildNodeMessageParams,
): Promise<BuildNodeMessageResult> {
  const { sessionId, userDid, targetDid, content, protocolUrl, privateKey } = params;

  const nonce = generateNonce();

  const recordedHop = new RecordedHop({
    sessionId,
    senderDid: userDid,
    targetDid,
    content,
    timestamp: Date.now(),
    hopCount: 0,
  });

  // 签名 content hash
  const hash = await recordedHop.contentHash();
  const { signHash } = await import('@attp/core');
  recordedHop.sigContent = await signHash(hash, privateKey);

  const nodeMessage = new NodeMessage({
    protocolUrl,
    nonce,
    recordedHop,
  });

  return { nodeMessage, nonce, recordedHop };
}

// ---- Phase 2: 发送 BackMessage ----

export interface SendBackMessageParams {
  protocolUrl: string;
  userDid: string;
  nonce: string;
  recordedHop: RecordedHop;
  privateKey: CryptoKey;
}

/**
 * 构造签名后的 BackMessage 并 POST 到协议节点的 /record 端点。
 *
 * 流程：
 *   1. 创建 BackMessage（复用 Phase 1 的 nonce 和 recordedHop）
 *   2. 签名 identityHash(nodeDid, nonce) → sigIdentity
 *   3. HTTP POST 到 {protocolUrl}/record
 *
 * 该函数为异步执行，不阻塞 UI。
 */
export async function sendBackMessage(params: SendBackMessageParams): Promise<boolean> {
  const { protocolUrl, userDid, nonce, recordedHop, privateKey } = params;

  try {
    const backMessage = new BackMessage({
      protocolUrl,
      nodeDid: userDid,
      nonce,
      recordedHop,
    });

    // 签名身份哈希
    await backMessage.signIdentity(privateKey);

    // HTTP POST 到协议节点
    const url = `${protocolUrl.replace(/\/+$/, '')}/record`;
    const result = await apiFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(backMessage.toDict()),
    });

    if (!result.ok) {
      console.warn('[ATTP] BackMessage POST failed:', result.status, result.error);
    }

    return result.ok;
  } catch (e) {
    console.error('[ATTP] sendBackMessage error:', e);
    return false;
  }
}

// ---- 解析收到的 ATTP 消息 ----

/**
 * 从 WS 收到的消息中解析 NodeMessage（如果存在）。
 *
 * Agent 返回的消息中可能在 metadata 字段包含 NodeMessage。
 */
export function parseIncomingNodeMessage(data: any): NodeMessage | null {
  try {
    let nodeMsgData: any = null;

    // 尝试多种可能的字段位置
    if (data?.NodeMessage) {
      nodeMsgData = data.NodeMessage;
    } else if (data?.metadata?.NodeMessage) {
      nodeMsgData = data.metadata.NodeMessage;
    } else if (data?.node_message) {
      nodeMsgData = data.node_message;
    }

    if (!nodeMsgData || typeof nodeMsgData !== 'object') {
      return null;
    }

    return NodeMessage.fromDict(nodeMsgData);
  } catch {
    return null;
  }
}