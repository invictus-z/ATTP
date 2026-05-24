/**
 * UserSession / UserSessionManager — 用户端会话管理。
 *
 * 面向 User 客户端，管理 ATTP 协议层的会话元数据：
 *   - session_id / protocol_node_address / hop 元数据
 *   - 用户身份 (userDid) 和密钥标识
 *
 * 参考 Python 端 AppSession 的结构，但针对用户端场景简化。
 */

/** Hop 记录的元数据结构 */
export interface HopMetadata {
  Hop_Count: number;
  Timestamp: number;
  Signature: string;
  Content: string;
  node_did: string;
  target_did: string;
  session_id?: string;
  protocol_node_address?: string;
}

/** 追踪相关元数据的键集合 */
const TRACE_KEYS = ['Hop', 'Session_ID', 'Protocol_Node_Address'] as const;

/**
 * UserSession — 用户端单个会话的协议层状态容器。
 */
export class UserSession {
  /** 会话标识（通常是 chatId） */
  key: string;
  /** ATTP 协议层元数据 */
  metadata: Record<string, unknown>;
  /** 最后更新时间（Unix 时间戳，秒） */
  updatedAt: number;

  constructor(data: { key: string; metadata?: Record<string, unknown>; updatedAt?: number }) {
    this.key = data.key;
    this.metadata = data.metadata ?? {};
    this.updatedAt = data.updatedAt ?? Date.now() / 1000;
  }

  // -- 追踪路由元数据 --

  /** 提取追踪相关的元数据。 */
  getTraceMetadata(): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const k of TRACE_KEYS) {
      if (k in this.metadata) {
        result[k] = this.metadata[k];
      }
    }
    return result;
  }

  /** 合并追踪元数据。 */
  setTraceMetadata(traceData: Record<string, unknown>): void {
    for (const k of TRACE_KEYS) {
      if (k in traceData) {
        this.metadata[k] = traceData[k];
      }
    }
    this.updatedAt = Date.now() / 1000;
  }

  // -- 便捷访问器 --

  get sessionId(): string | undefined {
    return this.metadata['Session_ID'] as string | undefined;
  }

  set sessionId(value: string | undefined) {
    if (value !== undefined) this.metadata['Session_ID'] = value;
  }

  get protocolNodeAddress(): string | undefined {
    return this.metadata['Protocol_Node_Address'] as string | undefined;
  }

  set protocolNodeAddress(value: string | undefined) {
    if (value !== undefined) this.metadata['Protocol_Node_Address'] = value;
  }

  get hop(): HopMetadata | undefined {
    return this.metadata['Hop'] as HopMetadata | undefined;
  }

  get hopCount(): number {
    return this.hop?.Hop_Count ?? -1;
  }

  /** 用户 DID 标识 */
  get userDid(): string | undefined {
    return this.metadata['user_did'] as string | undefined;
  }

  set userDid(value: string | undefined) {
    if (value !== undefined) this.metadata['user_did'] = value;
  }

  /** 密钥标识（用于从 KeyStore 查找私钥） */
  get keyId(): string | undefined {
    return this.metadata['key_id'] as string | undefined;
  }

  set keyId(value: string | undefined) {
    if (value !== undefined) this.metadata['key_id'] = value;
  }

  // -- hop_count 管理 --

  /** 当前 hop_count */
  get currentHopCount(): number[] {
    const stored = this.metadata['current_hop_count'] as number[];
    if (Array.isArray(stored) && stored.length === 2) {
      return stored;
    }
    return [0, 0];  // 默认值
  }
  
  /** 递增 hop_count 并返回新值 */
  incrementHopCount(): number[] {
    const current = this.currentHopCount;
    const newHopCount = [current[0], current[1] + 1];  // 只递增小跳
    this.metadata['current_hop_count'] = newHopCount;
    this.updatedAt = Date.now() / 1000;
    return newHopCount;
  }
  
  /** 设置 hop_count（从 Agent 回复中获取） */
  setHopCount(hopCount: number[]): void {
    if (Array.isArray(hopCount) && hopCount.length === 2) {
      this.metadata['current_hop_count'] = hopCount;
      this.updatedAt = Date.now() / 1000;
    }
  }

  // -- 通用元数据 --

  setMetadata(key: string, value: unknown): void {
    this.metadata[key] = value;
    this.updatedAt = Date.now() / 1000;
  }

  getMetadata(key: string, defaultValue?: unknown): unknown {
    return this.metadata[key] ?? defaultValue;
  }

  updateMetadata(data: Record<string, unknown>): void {
    Object.assign(this.metadata, data);
    this.updatedAt = Date.now() / 1000;
  }

  // -- 序列化 --

  toDict(): Record<string, unknown> {
    return {
      key: this.key,
      metadata: { ...this.metadata },
      updated_at: this.updatedAt,
    };
  }

  static fromDict(data: Record<string, unknown>): UserSession {
    return new UserSession({
      key: data['key'] as string,
      metadata: (data['metadata'] as Record<string, unknown>) ?? {},
      updatedAt: (data['updated_at'] as number) ?? Date.now() / 1000,
    });
  }
}

/**
 * UserSessionManager — 用户端会话存储，按 chatId 索引。
 *
 * 内存中维护所有活跃会话，可选持久化到 localStorage。
 */
export class UserSessionManager {
  private _sessions: Map<string, UserSession> = new Map();

  /** 获取或创建会话。 */
  getOrCreate(chatId: string): UserSession {
    if (!this._sessions.has(chatId)) {
      this._sessions.set(chatId, new UserSession({ key: chatId }));
    }
    return this._sessions.get(chatId)!;
  }

  /** 获取已有会话，不存在返回 undefined。 */
  get(chatId: string): UserSession | undefined {
    return this._sessions.get(chatId);
  }

  /** 保存/更新会话。 */
  save(session: UserSession): void {
    this._sessions.set(session.key, session);
  }

  /** 删除会话。 */
  delete(chatId: string): void {
    this._sessions.delete(chatId);
  }

  /** 所有会话条目。 */
  entries(): IterableIterator<[string, UserSession]> {
    return this._sessions.entries();
  }

  /** 会话数量。 */
  get size(): number {
    return this._sessions.size;
  }

  // -- 持久化 --

  /** 序列化所有会话为 JSON 字符串。 */
  serialize(): string {
    const obj: Record<string, unknown> = {};
    for (const [key, session] of this._sessions) {
      obj[key] = session.toDict();
    }
    return JSON.stringify(obj);
  }

  /** 从 JSON 字符串反序列化恢复所有会话。 */
  deserialize(json: string): void {
    try {
      const obj = JSON.parse(json);
      this._sessions.clear();
      for (const [key, value] of Object.entries(obj)) {
        this._sessions.set(key, UserSession.fromDict(value as Record<string, unknown>));
      }
    } catch {
      // 反序列化失败时保持空状态
    }
  }

  /** 保存到 localStorage。 */
  saveToStorage(storageKey: string = 'attp_user_sessions'): void {
    try {
      localStorage.setItem(storageKey, this.serialize());
    } catch {
      // localStorage 不可用时静默失败
    }
  }

  /** 从 localStorage 加载。 */
  loadFromStorage(storageKey: string = 'attp_user_sessions'): void {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) this.deserialize(raw);
    } catch {
      // localStorage 不可用时静默失败
    }
  }
}