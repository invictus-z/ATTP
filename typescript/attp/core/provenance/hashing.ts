/**
 * 哈希计算：genesis 标识哈希和每跳签名哈希。
 *
 * 从 python/attp/core/provenance/hashing.py 翻译而来。
 * 使用 Web Crypto API (crypto.subtle.digest) 实现 SHA-256，
 * 保证输出与 Python 端 hashlib.sha256 完全一致。
 */

/**
 * 计算 JSON 对象的 SHA-256 哈希。
 * 使用 JSON.stringify + sort_keys 语义：先对键排序再序列化。
 */
async function sha256Sorted(obj: Record<string, unknown>): Promise<string> {
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
 * 计算创世标识的 SHA-256 哈希，用于防篡改验证。
 */
export async function calculateGenesisHash(
  sessionId: string,
  protocolNodeAddress: string,
): Promise<string> {
  return sha256Sorted({
    session_id: sessionId,
    protocol_node_address: protocolNodeAddress,
  });
}

/**
 * 计算单跳消息字段的 SHA-256 哈希，用于身份验证签名。
 */
export async function calculateHopHash(
  content: string,
  nodeDid: string,
  targetDid: string,
  hopCount: number,
  timestamp: number,
  sessionId: string,
  protocolNodeAddress: string,
): Promise<string> {
  return sha256Sorted({
    content,
    node_did: nodeDid,
    target_did: targetDid,
    hop_count: hopCount,
    timestamp,
    session_id: sessionId,
    protocol_node_address: protocolNodeAddress,
  });
}