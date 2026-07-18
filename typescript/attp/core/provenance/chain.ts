/**
 * 核心链逻辑：追加跳。
 *
 * 从 python/attp/core/provenance/chain.py 的 append_hop 翻译而来。
 *
 * 范围说明（Plan 1 Task 5）：
 *   仅移植 append_hop —— TS agent 端唯一使用的链方法（见 client.py:232、
 *   server.py、mcp_tool_bridge.py:424、web/app.py:216,292）。
 *   validate_hop / verify_back_propagation 是 ProtocolNode 侧的双回传篡改检测，
 *   由 protocol_node/engine/middleware.py 调用；ProtocolNode 保持 Python 不移植，
 *   故此处不引入（YAGNI —— 无死代码）。
 */

import { calculateHopHash } from './hashing';
import { signHash } from '../authentication/signatures';
import { KeyStore } from '../authentication/keys';
import type { LoadedKey } from '../authentication/keys';
import { RecordedHop } from '../message/event';

/**
 * 链元数据：镜像 Python 的 metadata dict（recorded_hop / Session_ID）。
 *
 * - recordedHop: 上一跳记录（存在则续链）。
 * - sessionId:   创世跳（无 recordedHop 时）的会话标识。
 */
export interface ChainHopMetadata {
  recordedHop?: RecordedHop;
  sessionId?: string;
}

/**
 * 管理消息跳的追加。
 *
 * 持有 KeyStore 用于公钥缓存（镜像 Python ChainManager 的组合关系）；
 * appendHop 本身不严格需要 KeyStore，但保留以便 Task 8 的 AgentTracer 复用。
 */
export class ChainManager {
  private _keyStore: KeyStore;

  constructor(keyStore?: KeyStore) {
    this._keyStore = keyStore ?? new KeyStore();
  }

  /**
   * 追加一跳：计算 hop 哈希、签名、写入 recordedHop，返回新的 metadata。
   *
   * 逻辑与 Python append_hop 逐行对齐：
   *   - 拷贝 metadata（不修改入参）。
   *   - 若存在 recordedHop：sessionId 继承自该跳；behaviorType === "A2A"
   *     时 hop_count = [prev[0]+1, 0]，否则 [prev[0], prev[1]+1]。
   *   - 否则（创世）：sessionId 取 metadata.sessionId，hop_count = [0, 0]。
   *   - timestamp = Date.now()/1000（秒·浮点，对齐 Python time.time()）。
   *   - hopHash = calculateHopHash(...)；signature = signHash(hopHash, privateKey)。
   *   - 构造 RecordedHop 并写入新 metadata.recordedHop。
   *
   * @param metadata    链元数据（不被修改）。
   * @param content     本跳内容（结构化 JSON 字符串）。
   * @param senderDid   发送方 DID。
   * @param targetDid   目标方 DID。
   * @param privateKey  发送方私钥（已加载的 LoadedKey）。
   * @param behaviorType 行为类型："A2A" 触发大跳计数 +1，其余触发小跳计数 +1。
   */
  async appendHop(
    metadata: ChainHopMetadata,
    content: string,
    senderDid: string,
    targetDid: string,
    privateKey: LoadedKey,
    behaviorType?: 'A2A' | 'intra' | string,
  ): Promise<ChainHopMetadata> {
    // 拷贝 metadata —— 与 Python 的 metadata.copy() 一致，不修改入参。
    const next: ChainHopMetadata = { ...metadata };

    let sessionId: string;
    let hopCount: number[];

    const prevHop = next.recordedHop;
    if (prevHop) {
      sessionId = prevHop.sessionId;
      const prev = prevHop.hopCount;
      if (behaviorType === 'A2A') {
        hopCount = [prev[0] + 1, 0];
      } else {
        hopCount = [prev[0], prev[1] + 1];
      }
    } else {
      sessionId = next.sessionId ?? '';
      hopCount = [0, 0];
    }

    const timestamp = Date.now() / 1000;
    const hopHash = await calculateHopHash({
      content,
      senderDid,
      targetDid,
      hopCount,
      timestamp,
      sessionId,
    });
    const signature = await signHash(hopHash, privateKey);

    const newHop = new RecordedHop({
      sessionId,
      senderDid,
      targetDid,
      content,
      timestamp,
      hopCount,
      sigContent: signature,
    });

    next.recordedHop = newHop;
    return next;
  }
}
