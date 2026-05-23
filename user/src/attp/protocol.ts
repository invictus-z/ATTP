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
import { isSecp256k1Key, isEd25519Key, type SignableKey } from './key_helper';
import { signAsync as secpSignAsync } from '@noble/secp256k1';
import { secp256k1 } from '@noble/curves/secp256k1.js';
import { ed25519 as ed25519Curve } from '@noble/curves/ed25519.js';

// ---- 统一签名函数（支持 CryptoKey + secp256k1 + Ed25519） ----

/**
 * 使用 SignableKey 签名。
 *
 * CryptoKey → 走 Web Crypto API（@attp/core signHash）
 * Secp256k1PrivateKey → 走 @noble/secp256k1，输出 DER 格式（兼容 Python cryptography 库）
 * Ed25519PrivateKey → 走 @noble/ed25519，输出原始 64 字节（兼容 Python cryptography 库）
 */
async function signWithKey(hash: string, privateKey: SignableKey): Promise<string> {
  if (isSecp256k1Key(privateKey)) {
    // secp256k1 签名：signAsync 返回 compact (r||s, 64 bytes)
    // Python cryptography 库期望 DER 编码，需转换
    const msgBytes = new TextEncoder().encode(hash);
    const msgHash = await crypto.subtle.digest('SHA-256', msgBytes);
    const sigBytes: Uint8Array = await secpSignAsync(new Uint8Array(msgHash), privateKey.rawBytes);
    const derSig = secp256k1.Signature.fromBytes(sigBytes).toBytes('der');
    return arrayBufferToBase64(derSig.buffer as ArrayBuffer);
  }
  if (isEd25519Key(privateKey)) {
    // Ed25519 签名：直接对 hash 字符串的字节签名（与 Python sign_hash 一致）
    const msgBytes = new TextEncoder().encode(hash);
    const sigBytes = ed25519Curve.sign(msgBytes, privateKey.rawBytes);
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
    hopCount: [0, 0],
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
    console.log(`[DEBUG-CONN][sendBackMessage] POST → ${url}`);
    console.log(`[DEBUG-CONN][sendBackMessage]     protocolUrl="${protocolUrl}", nodeDid="${userDid}", nonce="${nonce}"`);
    const result = await apiFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(backMessage.toDict()),
    });

    if (!result.ok) {
      console.warn(`[DEBUG-CONN][sendBackMessage] ✗ POST ${url} → FAIL: HTTP ${result.status}, error="${result.error}"`);
    } else {
      console.log(`[DEBUG-CONN][sendBackMessage] ✓ POST ${url} → OK`);
    }

    return result.ok;
  } catch (e) {
    console.error('[ATTP] sendBackMessage error:', e);
    return false;
  }
}

// ---- 解析收到的 ATTP 消息 ----

/**
 * 从 WS 收到的消息中解析 NodeMessage。
 *
 * Agent 返回的消息现在直接是 NodeMessage dict（不再有外层包装）。
 */
export function parseIncomingNodeMessage(data: any): NodeMessage | null {
  try {
    return NodeMessage.fromDict(data)
  } catch {
    return null
  }
}
