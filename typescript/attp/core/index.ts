/**
 * ATTP Core — TypeScript 版
 *
 * 从 python/attp/core 翻译而来，面向 User 客户端使用。
 * 包含消息类型、签名验签、哈希计算和会话管理。
 */

// 消息
export { RecordedHop, NodeMessage, BackMessage } from './message';
export { sendBackMessage, BackPropagationError, type SendBackParams } from './message/back-sender';

// 认证
export { KeyStore } from './authentication';
export { signHash, verifySignature } from './authentication';
// 以下从具体模块文件导出，避免与上面的 barrel re-export 重复（signHash/verifySignature/KeyStore 已在上面）。
export { signRaw, verifyRaw, importPublicPem, importPublicJwk } from './authentication/signatures';
export { loadPrivateKeyPem, type LoadedKey, type AnyKey, type NobleKey } from './authentication/keys';
export {
  resolveDid,
  buildDidResolutionUrl,
  didBaseId,
  extractNodeType,
  clearDidCache,
  invalidateDid,
} from './authentication/did-resolver';

// 溯源
export { calculateGenesisHash, calculateHopHash } from './provenance';
export { canonicalJson } from './provenance/hashing';
export { ChainManager, type ChainHopMetadata } from './provenance/chain';

// AgentTracer 门面（组合 KeyStore + ChainManager）
export { AgentTracer } from './agent-tracer';

// 会话
export { BehaviorEntry, type FieldType } from './sessions';
export { UserSession, UserSessionManager, type HopMetadata } from './sessions';