/**
 * ATTP 协议消息构造与发送 — User 端核心逻辑。
 *
 * 职责：
 *   - 构造签名后的 NodeMessage（Phase 1：随 WS 消息发送给 Agent）
 *   - 构造签名后的 BackMessage 并 HTTP POST 到协议节点（Phase 2：回传）
 *   - 解析收到的 ATTP 格式消息
 */

import { RecordedHop, NodeMessage, BackMessage, signHash as coreSignHash } from '@attp/core';
import { apiFetch } from '../transport';
import { isSecp256k1Key, type SignableKey } from './key_helper';
import { hashes as secpHashes, signAsync as secpSignAsync } from '@noble/secp256k1';
import { sha256 } from '@noble/hashes/sha2.js';

// @noble/secp256k1 v3 不内置 SHA-256，注入到 hashes.sha256
secpHashes.sha256 = sha256;

// ---- 统一签名函数（支持 CryptoKey + secp256k1） ----

/**
 * 使用 SignableKey 签名。
 *
 * CryptoKey → 走 Web Crypto API（@attp/core signHash）
 * Secp256k1PrivateKey → 走 @noble/secp256k1
 */
async function signWithKey(hash: string, privateKey: SignableKey): Promise<string> {
  if (isSecp256k1Key(privateKey)) {
    // secp256k1 签名（v3）：signAsync 返回 Uint8Array（64 bytes compact）
    const msgBytes = new TextEncoder().encode(hash);
    const msgHash = await crypto.subtle.digest('SHA-256', msgBytes);
    const sigBytes: Uint8Array = await secpSignAsync(new Uint8Array(msgHash), privateKey.rawBytes);
    return arrayBufferToBase64(sigBytes.buffer as ArrayBuffer);
  }
  // 标准 CryptoKey → 走 core signHash
  return coreSignHash(hash, privateKey);
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

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
  privateKey: SignableKey;
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

  // 签名 content hash（支持 CryptoKey 和 secp256k1）
  const hash = await recordedHop.contentHash();
  recordedHop.sigContent = await signWithKey(hash, privateKey);

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
  privateKey: SignableKey;
}

/** 计算 nodeDid + nonce 的身份哈希 */
async function identityHash(nodeDid: string, nonce: string): Promise<string> {
  const obj: Record<string, unknown> = { node_did: nodeDid, nonce };
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(obj).sort()) {
    sorted[key] = obj[key];
  }
  const raw = JSON.stringify(sorted);
  const buffer = new TextEncoder().encode(raw);
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
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

    // 签名身份哈希（支持 CryptoKey 和 secp256k1）
    const iHash = await identityHash(userDid, nonce);
    backMessage.sigIdentity = await signWithKey(iHash, privateKey);

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