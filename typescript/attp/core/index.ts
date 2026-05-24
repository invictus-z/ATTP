/**
 * ATTP Core — TypeScript 版
 *
 * 从 python/attp/core 翻译而来，面向 User 客户端使用。
 * 包含消息类型、签名验签、哈希计算和会话管理。
 */

// 消息
export { RecordedHop, NodeMessage, BackMessage } from './message';

// 认证
export { KeyStore } from './authentication';
export { signHash, verifySignature } from './authentication';

// 溯源
export { calculateGenesisHash, calculateHopHash } from './provenance';

// 会话
export { BehaviorEntry, type FieldType } from './sessions';
export { UserSession, UserSessionManager, type HopMetadata } from './sessions';