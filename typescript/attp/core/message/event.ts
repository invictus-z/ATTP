/**
 * 消息格式规范化 — RecordedHop / NodeMessage / BackMessage。
 *
 * 从 python/attp/core/message/event.py 翻译而来。
 * 序列化格式 (to_dict/from_dict) 与 Python 端完全一致，
 * 确保跨语言通信时的数据兼容性。
 */

import { signHash, verifySignature } from '../authentication/signatures';
import type { AnyKey } from '../authentication/keys';
import { calculateHopHash } from '../provenance/hashing';

// ---------------------------------------------------------------------------
// RecordedHop — 单跳记录
// ---------------------------------------------------------------------------

/**
 * 单跳记录内容，嵌入在 NodeMessage 和 BackMessage 中。
 *
 * sigContent 是对其余字段哈希后的签名，
 * 由发送方私钥签署，用于内容完整性验证。
 */
export class RecordedHop {
  sessionId: string;
  senderDid: string;
  targetDid: string;
  content: string;  // 结构化 JSON 字符串
  timestamp: number;
  hopCount: number[];  // [大跳数, 小跳数]
  sigContent: string;

  constructor(data: {
    sessionId: string;
    senderDid: string;
    targetDid: string;
    content: string;
    timestamp: number;
    hopCount: number[];
    sigContent?: string;
  }) {
    this.sessionId = data.sessionId;
    this.senderDid = data.senderDid;
    this.targetDid = data.targetDid;
    this.content = data.content;
    this.timestamp = data.timestamp;
    this.hopCount = data.hopCount;
    this.sigContent = data.sigContent ?? '';
  }

  /** 计算除 sigContent 外所有字段的 SHA-256 哈希（委托给 calculateHopHash，DRY）。 */
  async contentHash(): Promise<string> {
    return calculateHopHash({
      content: this.content,
      senderDid: this.senderDid,
      targetDid: this.targetDid,
      hopCount: this.hopCount,
      timestamp: this.timestamp,
      sessionId: this.sessionId,
    });
  }

  toDict(): Record<string, unknown> {
    return {
      session_id: this.sessionId,
      sender_did: this.senderDid,
      target_did: this.targetDid,
      content: this.content,
      timestamp: this.timestamp,
      hop_count: this.hopCount,
      sig_content: this.sigContent,
    };
  }

  static fromDict(data: Record<string, unknown>): RecordedHop {
    return new RecordedHop({
      sessionId: data['session_id'] as string,
      senderDid: data['sender_did'] as string,
      targetDid: data['target_did'] as string,
      content: data['content'] as string,
      timestamp: data['timestamp'] as number,
      hopCount: data['hop_count'] as number[],
      sigContent: (data['sig_content'] as string) ?? '',
    });
  }
}

// ---------------------------------------------------------------------------
// NodeMessage — 节点间转发消息 (A → B)
// ---------------------------------------------------------------------------

/**
 * 转发消息：A 向 B 发送。
 *
 * protocolUrl: 协议节点地址
 * nonce:       唯一标识，用于匹配回传消息
 * recordedHop: 单跳记录内容
 */
export class NodeMessage {
  protocolUrl: string;
  nonce: string;
  recordedHop: RecordedHop;

  constructor(data: {
    protocolUrl: string;
    nonce: string;
    recordedHop: RecordedHop;
  }) {
    this.protocolUrl = data.protocolUrl;
    this.nonce = data.nonce;
    this.recordedHop = data.recordedHop;
  }

  /** 发送方私钥对 recordedHop 内容签名，写入 sigContent。 */
  async signContent(privateKey: AnyKey): Promise<void> {
    const hash = await this.recordedHop.contentHash();
    this.recordedHop.sigContent = await signHash(hash, privateKey);
  }

  /** 验证 recordedHop.sigContent 是否由对应公钥签署。 */
  async verifyContent(publicKey: AnyKey): Promise<boolean> {
    if (!this.recordedHop.sigContent) return false;
    const hash = await this.recordedHop.contentHash();
    return verifySignature(hash, this.recordedHop.sigContent, publicKey);
  }

  toDict(): Record<string, unknown> {
    return {
      protocol_url: this.protocolUrl,
      nonce: this.nonce,
      recorded_hop: this.recordedHop.toDict(),
    };
  }

  static fromDict(data: Record<string, unknown>): NodeMessage {
    return new NodeMessage({
      protocolUrl: data['protocol_url'] as string,
      nonce: data['nonce'] as string,
      recordedHop: RecordedHop.fromDict(data['recorded_hop'] as Record<string, unknown>),
    });
  }
}

// ---------------------------------------------------------------------------
// BackMessage — 节点回传消息
// ---------------------------------------------------------------------------

/** 计算 nodeDid + nonce 的身份哈希。 */
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
 * 节点回传消息：节点（A 或 B）向协议节点回传。
 *
 * protocolUrl:  协议节点地址
 * nodeDid:      回传节点的 DID 身份
 * nonce:        唯一标识，用于匹配回传消息
 * sigIdentity:  nodeDid + nonce 的私钥签名，用于身份确认
 * recordedHop:  单跳记录内容
 */
export class BackMessage {
  protocolUrl: string;
  nodeDid: string;
  nonce: string;
  sigIdentity: string;
  recordedHop: RecordedHop;

  constructor(data: {
    protocolUrl: string;
    nodeDid: string;
    nonce: string;
    sigIdentity?: string;
    recordedHop: RecordedHop;
  }) {
    this.protocolUrl = data.protocolUrl;
    this.nodeDid = data.nodeDid;
    this.nonce = data.nonce;
    this.sigIdentity = data.sigIdentity ?? '';
    this.recordedHop = data.recordedHop;
  }

  // -- 身份签名 --

  /** 使用回传节点私钥对 nodeDid+nonce 签名，写入 sigIdentity。 */
  async signIdentity(privateKey: AnyKey): Promise<void> {
    this.sigIdentity = await signHash(
      await identityHash(this.nodeDid, this.nonce),
      privateKey,
    );
  }

  /** 验证 sigIdentity 是否合法。 */
  async verifyIdentity(publicKey: AnyKey): Promise<boolean> {
    if (!this.sigIdentity) return false;
    return verifySignature(
      await identityHash(this.nodeDid, this.nonce),
      this.sigIdentity,
      publicKey,
    );
  }

  // -- 内容签名（发送方签名，由 recordedHop.sigContent 承载）--

  /** 使用发送方私钥对 recordedHop 内容签名。 */
  async signContent(privateKey: AnyKey): Promise<void> {
    const hash = await this.recordedHop.contentHash();
    this.recordedHop.sigContent = await signHash(hash, privateKey);
  }

  /** 验证 recordedHop 内容签名（发送方签名）。 */
  async verifyContent(publicKey: AnyKey): Promise<boolean> {
    if (!this.recordedHop.sigContent) return false;
    const hash = await this.recordedHop.contentHash();
    return verifySignature(hash, this.recordedHop.sigContent, publicKey);
  }

  toDict(): Record<string, unknown> {
    return {
      protocol_url: this.protocolUrl,
      node_did: this.nodeDid,
      nonce: this.nonce,
      sig_identity: this.sigIdentity,
      recorded_hop: this.recordedHop.toDict(),
    };
  }

  static fromDict(data: Record<string, unknown>): BackMessage {
    return new BackMessage({
      protocolUrl: data['protocol_url'] as string,
      nodeDid: data['node_did'] as string,
      nonce: data['nonce'] as string,
      sigIdentity: (data['sig_identity'] as string) ?? '',
      recordedHop: RecordedHop.fromDict(data['recorded_hop'] as Record<string, unknown>),
    });
  }
}