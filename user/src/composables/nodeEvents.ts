/**
 * nodeEvents — 协议节点全局事件常驻连接（模块级单例）。
 *
 * 在 App.vue 选中协议节点时建立一条 SSE 连接（topics=record,malicious），
 * 负责两类「全局告警」的接收与分发，无论用户在哪个页面都送达：
 *   - record.error       回传消息处理失败（验证失败/异常）
 *   - malicious.detected 恶意节点检出
 *
 * 消费方通过 onRecordError / onMaliciousDetected 注册 handler（返回 unsubscribe）。
 * 分析进度（analysis.*）与行为链生长（trace.recorded）仍是按视图订阅，不在此处。
 */

import { createSse, onSseEvent, type SseConnection } from '../transport'

let conn: SseConnection | null = null
const maliciousHandlers = new Set<(data: any) => void>()
const recordErrorHandlers = new Set<(data: any) => void>()

/** 注册 malicious.detected handler，返回取消注册函数。 */
export function onMaliciousDetected(cb: (data: any) => void): () => void {
  maliciousHandlers.add(cb)
  return () => { maliciousHandlers.delete(cb) }
}

/** 注册 record.error handler，返回取消注册函数。 */
export function onRecordError(cb: (data: any) => void): () => void {
  recordErrorHandlers.add(cb)
  return () => { recordErrorHandlers.delete(cb) }
}

/** 建立常驻 SSE 连接（先断旧连再开新连）。url 为空则仅断开。 */
export async function connectNodeEvents(url: string): Promise<void> {
  await disconnectNodeEvents()
  if (!url) return
  try {
    conn = await createSse(url)
  } catch {
    conn = null
    return
  }
  onSseEvent(conn, (event, data) => {
    if (event === 'malicious.detected') {
      maliciousHandlers.forEach(h => { try { h(data) } catch { /* ignore */ } })
    } else if (event === 'record.error') {
      recordErrorHandlers.forEach(h => { try { h(data) } catch { /* ignore */ } })
    }
  })
}

/** 断开常驻 SSE 连接（保留已注册 handler，下次连接继续生效）。 */
export async function disconnectNodeEvents(): Promise<void> {
  if (conn) {
    const c = conn
    conn = null
    await c.close()
  }
}
