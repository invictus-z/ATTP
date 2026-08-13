/**
 * 哈希计算：genesis 标识哈希和每跳签名哈希。
 *
 * 从 python/attp/core/provenance/hashing.py 翻译而来。
 * 使用 Web Crypto API (crypto.subtle.digest) 实现 SHA-256，
 * 保证输出与 Python 端 hashlib.sha256 完全一致（字节级相同）。
 *
 * 规范 JSON 规则（与 Python 端一致）：
 *   json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)
 * 对应 TS 实现：先对键排序，再 JSON.stringify（默认无空格，匹配 separators），
 * TextEncoder 默认 UTF-8 且不 ascii 转义（匹配 ensure_ascii=False）。
 */

/**
 * 计算规范 JSON 字符串：键排序 + 紧凑分隔符。
 * 与 Python `json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)` 字节一致。
 */
export function canonicalJson(obj: Record<string, unknown>): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(obj).sort()) {
    sorted[key] = obj[key];
  }
  return JSON.stringify(sorted);
}

/**
 * 计算对象规范 JSON 的 SHA-256 哈希（十六进制小写）。
 */
async function sha256Canonical(obj: Record<string, unknown>): Promise<string> {
  const raw = canonicalJson(obj);
  const buffer = new TextEncoder().encode(raw);
  const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * 计算创世标识的 SHA-256 哈希，用于防篡改验证。
 *
 * 字段集（与 Python 完全一致）：{ session_id, protocol_node_address }
 */
export async function calculateGenesisHash(
  sessionId: string,
  protocolNodeAddress: string,
): Promise<string> {
  return sha256Canonical({
    session_id: sessionId,
    protocol_node_address: protocolNodeAddress,
  });
}

/** calculateHopHash 输入参数（camelCase TS 字段 → snake_case JSON 键）。 */
export interface HopHashInput {
  content: string;
  senderDid: string;
  targetDid: string;
  hopCount: number[];
  timestamp: number;
  sessionId: string;
}

/**
 * 计算单跳消息字段的 SHA-256 哈希，用于身份验证签名。
 *
 * 字段集（与 Python 完全一致）：
 *   { content, sender_did, target_did, hop_count, timestamp, session_id }
 */
export async function calculateHopHash(input: HopHashInput): Promise<string> {
  return sha256Canonical({
    content: input.content,
    sender_did: input.senderDid,
    target_did: input.targetDid,
    hop_count: input.hopCount,
    timestamp: input.timestamp,
    session_id: input.sessionId,
  });
}
