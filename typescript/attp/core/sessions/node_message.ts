/**
 * BehaviorEntry — 单条行为记录。
 *
 * 从 python/attp/core/sessions/node_message.py 翻译而来。
 *
 * fieldType 取值：
 *   A2T — Agent → Tool   （Agent 调用工具）
 *   A2U — Agent → User   （Agent 发给用户）
 *   U2A — User  → Agent  （用户发给 Agent）
 *   A2A — Agent → Agent  （Agent 间通信）
 *   T2A — Tool  → Agent  （工具返回结果，预留）
 */

/** 行为类型枚举 */
export type FieldType = 'A2T' | 'A2U' | 'U2A' | 'A2A' | 'T2A';

export class BehaviorEntry {
  fieldType: FieldType;
  content: string;
  timestamp: number;
  target: string;       // A2T: tool; A2A: target_did; 其他: ""
  extra: Record<string, unknown>;

  constructor(data: {
    fieldType: FieldType;
    content: string;
    timestamp?: number;
    target?: string;
    extra?: Record<string, unknown>;
  }) {
    this.fieldType = data.fieldType;
    this.content = data.content;
    this.timestamp = data.timestamp ?? Date.now() / 1000;
    this.target = data.target ?? '';
    this.extra = data.extra ?? {};
  }

  toDict(): Record<string, unknown> {
    return {
      field_type: this.fieldType,
      content: this.content,
      timestamp: this.timestamp,
      target: this.target,
      extra: this.extra,
    };
  }

  static fromDict(data: Record<string, unknown>): BehaviorEntry {
    return new BehaviorEntry({
      fieldType: data['field_type'] as FieldType,
      content: data['content'] as string,
      timestamp: (data['timestamp'] as number) ?? 0.0,
      target: (data['target'] as string) ?? '',
      extra: (data['extra'] as Record<string, unknown>) ?? {},
    });
  }
}