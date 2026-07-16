/**
 * ATTP WebSocket hub —— 宿主无关（host-agnostic）的 WS 连接管理。
 *
 * 维护 sessionId -> 活跃 WS 连接集合的映射，供上层（attp-server.ts 的 WebUI
 * 端口）在浏览器 WS 接入时 register、在 A2A 回复时 broadcast、断开时 unregister。
 *
 * 本模块只承载 NodeMessage 形状的 WS 帧（ATTP user 端协议）：
 *   - parseInboundNodeMessage  ：入站 { protocol_url, nonce, recorded_hop: {...} }
 *                                 形状，session_id / sender_did / content /
 *                                 target_did 嵌在 recorded_hop 内。
 *   - nodeMessageFrame         ：把出站 NodeMessage 序列化为 WS 文本帧。
 *
 * Plan 2, Task 6（旧版扁平 parseWsMessage 已随 Plan 3 gateway-route 形态的移除
 * 一并删除——三端口改造后入站 WS 只走 NodeMessage 协议）。
 */

import { NodeMessage } from "../core/message/event.js";

/**
 * 最小 WS-like 抽象。
 *
 * readyState 遵循浏览器 WebSocket 常量：1 = OPEN。
 * send 与浏览器 WebSocket.send(data: string) 同形。
 */
export interface WsLike {
  send(data: string): void;
  readyState: number;
}

/** readyState === 1 即 OPEN（对齐 WHATWG WebSocket）。 */
const WS_OPEN = 1;

/**
 * 进程内 WS 连接 hub：按 sessionId 聚合多条 WS 连接。
 *
 * 同一 session 可被多个浏览器标签页（多条 WS）订阅，broadcast 会
 * 逐一投递给仍处于 OPEN 状态的连接，跳过已关闭/正在关闭的连接。
 */
export class WsHub {
  private sessions = new Map<string, Set<WsLike>>();

  /** 将 ws 加入该 session 的集合；集合不存在则创建。 */
  register(sessionId: string, ws: WsLike): void {
    let set = this.sessions.get(sessionId);
    if (!set) {
      set = new Set();
      this.sessions.set(sessionId, set);
    }
    set.add(ws);
  }

  /** 从该 session 的集合中移除 ws；集合为空时删除映射项。 */
  unregister(sessionId: string, ws: WsLike): void {
    const set = this.sessions.get(sessionId);
    if (!set) return;
    set.delete(ws);
    if (set.size === 0) {
      this.sessions.delete(sessionId);
    }
  }

  /** 返回该 session 当前注册的 WS 数量；session 不存在返回 0。 */
  size(sessionId: string): number {
    return this.sessions.get(sessionId)?.size ?? 0;
  }

  /** 对该 session 下每条 OPEN 的 WS 调用 ws.send(text)。 */
  broadcast(sessionId: string, text: string): void {
    const set = this.sessions.get(sessionId);
    if (!set) return;
    for (const ws of set) {
      if (ws.readyState === WS_OPEN) {
        ws.send(text);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// NodeMessage 形状的 WS 帧解析 / 序列化（ATTP user 端协议）
// ---------------------------------------------------------------------------

/**
 * 解析后的 NodeMessage 入站 WS 帧。
 *
 * sessionId / senderDid / content / targetDid 都从 `recorded_hop` 内抽取；
 * nodeMessage 保留为整帧原始 dict（snake_case），调用方可按需用
 * `NodeMessage.fromDict` 进一步解析。
 */
export interface InboundNodeMessage {
  sessionId: string;
  senderDid: string;
  targetDid?: string;
  content: string;
  /** 整帧 NodeMessage dict（snake_case，未转换）。 */
  nodeMessage: any;
}

/**
 * 解析入站 NodeMessage WS 文本帧。
 *
 * 接受 `NodeMessage.to_dict()` 形状的 JSON：
 *   { protocol_url, nonce, recorded_hop: { session_id, sender_did, target_did,
 *     content, timestamp, hop_count, sig_content } }
 *
 * 从 `recorded_hop` 抽取 session_id / sender_did / target_did / content，
 * 整帧 dict 原样回填到 nodeMessage 字段。
 *
 * 解析失败（非法 JSON / 顶层非对象 / 缺失 recorded_hop）时返回 null。
 */
export function parseInboundNodeMessage(raw: string): InboundNodeMessage | null {
  let msg: any;
  try {
    msg = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!msg || typeof msg !== "object") return null;
  const hop = msg.recorded_hop;
  if (!hop || typeof hop !== "object") return null;
  return {
    sessionId: hop.session_id,
    senderDid: hop.sender_did,
    targetDid: hop.target_did,
    content: hop.content,
    nodeMessage: msg,
  };
}

/**
 * 将 NodeMessage 序列化为 WS 文本帧（A2U 推送）。
 *
 * 直接 `JSON.stringify(nodeMsg.toDict())` —— 与 Python `NodeMessage.to_dict()`
 * 后 json.dumps 的字节序一致（字段顺序由 toDict 决定）。
 */
export function nodeMessageFrame(nodeMsg: NodeMessage): string {
  return JSON.stringify(nodeMsg.toDict());
}
