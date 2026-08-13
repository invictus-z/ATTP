/**
 * Agent-side tracer facade — 组合 KeyStore + ChainManager。
 *
 * 从 python/attp/core/agent_tracer.py 忠实移植。
 *
 * Agent 侧仅使用 appendHop + cachePublicKey：
 *   - Python 的 load_private_key 在 TS 端不需要——openclaw 通道在启动时
 *     调用 loadPrivateKeyPem 一次性加载私钥，并将 LoadedKey 直接传给 appendHop。
 *   - 因此此处不暴露 load_private_key（避免误导；openclaw 直接持有 LoadedKey）。
 */

import { KeyStore, type LoadedKey, type AnyKey } from "./authentication/keys.js";
import { ChainManager, type ChainHopMetadata } from "./provenance/chain.js";

/**
 * 轻量级 facade：Agent 侧溯源操作。
 *
 * 组合 KeyStore（公钥缓存）与 ChainManager（跳构造），不持有任何持久化存储。
 * 镜像 Python AgentTracer：构造时创建独立 KeyStore 并将其注入 ChainManager。
 */
export class AgentTracer {
  readonly keys: KeyStore;
  readonly chain: ChainManager;

  constructor() {
    // 使用构造体而非字段初始化器：先建 keys 再注入 chain，语义与 Python __init__ 一致，
    // 同时规避在字段初始化器中引用 this.keys 的初始化顺序歧义。
    this.keys = new KeyStore();
    this.chain = new ChainManager(this.keys);
  }

  /**
   * 注入公钥到缓存（验签前调用）。
   * 委托给内部 KeyStore。
   */
  cachePublicKey(did: string, key: LoadedKey): void {
    this.keys.cachePublicKey(did, key);
  }

  /**
   * 追加一跳：计算哈希、签名、写入 recordedHop，返回新的 metadata。
   *
   * 调用方传入已加载的私钥（openclaw 启动时加载一次）。
   * 委托给内部 ChainManager。
   */
  appendHop(
    metadata: ChainHopMetadata,
    content: string,
    senderDid: string,
    targetDid: string,
    privateKey: AnyKey,
    behaviorType?: string,
  ): Promise<ChainHopMetadata> {
    return this.chain.appendHop(
      metadata,
      content,
      senderDid,
      targetDid,
      privateKey,
      behaviorType,
    );
  }
}
