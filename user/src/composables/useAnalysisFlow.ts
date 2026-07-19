/**
 * useAnalysisFlow — 引导式分析流程状态机（SSE 推送版）。
 *
 * 通过 SSE 订阅 analysis 事件流，实时反映分析进度与累计状态变化：
 *   - analysis.progress    → 标记 running（含阶段 phase）
 *   - analysis.report      → 标记 completed，触发 completedHooks 拉取最新 state + report
 *   - horizontal.accumulated（仅横向）→ 触发 stateChangeHooks 拉取最新横向累计状态
 *
 * 订阅在 report 后不自动断开，保持连接以连续接收后续事件，实现全程实时更新。
 * 纵向（v, session 级）与横向（h, did 级）共用，仅过滤字段不同。
 *
 *   POST /api/analysis/{axis}/trigger/{id}                       — 手动触发
 *   GET  /api/events?topics=analysis&<session_id|did>=<id>       — SSE 事件流
 *
 * 任务状态词汇：running | completed | not_found。
 */

import { ref, computed, onScopeDispose } from 'vue'
import { apiFetch, createSse, onSseEvent, type SseConnection } from '../transport'
import { useProtocolNodes } from './useProtocolNodes'
import type { AnalysisStatus } from '../views/trace/types'

export type AnalysisAxis = 'v' | 'h'

export function useAnalysisFlow(
  axis: AnalysisAxis,
  onCompleted?: (id: string) => void,
) {
  const { buildUrl } = useProtocolNodes()

  const status = ref<AnalysisStatus | null>(null)
  const triggerLoading = ref(false)
  const running = computed(() => status.value?.status === 'running')

  let sseConn: SseConnection | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  const completedHooks: Array<(id: string) => void> = []
  const stateChangeHooks: Array<(id: string) => void> = []
  if (onCompleted) completedHooks.push(onCompleted)

  /** 构造本轴的分析状态对象。 */
  function makeStatus(state: string, extra: Partial<AnalysisStatus> = {}, id?: string): AnalysisStatus {
    const base: AnalysisStatus = { status: state }
    if (id) {
      if (axis === 'v') base.session_id = id
      else base.did = id
    }
    return { ...base, ...extra }
  }

  /** 轮询 llm-status 取 queue_depth / phase（running 期间，补 SSE 未带的积压跳数）。 */
  async function pollLlmStatus(id: string): Promise<void> {
    const url = buildUrl(`/api/analysis/${axis}/llm-status/${encodeURIComponent(id)}`)
    if (!url) return
    try {
      const res = await apiFetch(url)
      if (res.ok && res.data && status.value?.status === 'running') {
        status.value = makeStatus('running', {
          phase: res.data.phase ?? status.value.phase,
          queue_depth: res.data.queue_depth,
        }, id)
      }
    } catch {
      /* 轮询失败忽略，保持上次状态 */
    }
  }

  function startPolling(id: string): void {
    if (pollTimer) return  // 已在轮询，避免重置时钟
    pollTimer = setInterval(() => { void pollLlmStatus(id) }, 1500)
  }

  function stopPolling(): void {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  }

  /** 订阅指定 id 的分析事件流（progress + report）。 */
  async function subscribe(id: string): Promise<void> {
    if (!id) { status.value = null; return }
    await unsubscribe()
    const filterKey = axis === 'v' ? 'session_id' : 'did'
    const url = buildUrl(`/api/events?topics=analysis&${filterKey}=${encodeURIComponent(id)}`)
    if (!url) return
    try {
      sseConn = await createSse(url)
    } catch {
      /* 连接失败保持上次状态 */
      return
    }
    onSseEvent(sseConn, (event, data) => {
      if (event === 'analysis.progress') {
        status.value = makeStatus('running', { phase: data?.phase }, id)
        startPolling(id)
      } else if (event === 'analysis.report') {
        stopPolling()
        status.value = makeStatus('completed', {
          triggered: data?.triggered !== false,
          reason: data?.reason,
        }, id)
        completedHooks.forEach(cb => cb(id))
        // 不自动取消订阅：保持连接以连续接收后续事件（新的 progress/report、
        // 横向累加 horizontal.accumulated），实现全程实时更新。
      } else if (axis === 'v' && event === 'hop.scored') {
        // 纵轴打出一跳分 → 刷新逐跳评分报告。
        stateChangeHooks.forEach(cb => cb(id))
      } else if (axis === 'h' && event === 'horizontal.triggered') {
        // F 越 R_S，横轴确认被触发 → 刷新横向累计状态。
        stateChangeHooks.forEach(cb => cb(id))
      } else if (axis === 'h' && event === 'horizontal.accumulated') {
        // 横向 F/volume 累加 → 刷新横向累计状态。
        stateChangeHooks.forEach(cb => cb(id))
      }
    })
  }

  /** 关闭 SSE 订阅。 */
  async function unsubscribe(): Promise<void> {
    stopPolling()
    if (sseConn) {
      const conn = sseConn
      sseConn = null
      await conn.close()
    }
  }

  /** 触发分析；成功则立即标记 running 并订阅事件流。返回是否触发成功。 */
  async function trigger(id: string): Promise<boolean> {
    if (!id) return false
    triggerLoading.value = true
    try {
      const url = buildUrl(`/api/analysis/${axis}/trigger/${encodeURIComponent(id)}`)
      const result = await apiFetch(url, { method: 'POST' })
      if (result.ok && result.data?.triggered) {
        status.value = makeStatus('running', { phase: 'starting' }, id)
        void subscribe(id)
        startPolling(id)
        return true
      }
      return false
    } finally {
      triggerLoading.value = false
    }
  }

  /** 追加 completed 回调（完成时拉报告）。 */
  function onCompletedHook(cb: (id: string) => void): void {
    completedHooks.push(cb)
  }

  /** 追加 state-change 回调（hop.scored 刷逐跳评分 / horizontal.triggered|accumulated 刷 F/volume 时触发）。 */
  function onStateChange(cb: (id: string) => void): void {
    stateChangeHooks.push(cb)
  }

  onScopeDispose(() => { void unsubscribe() })

  return {
    status,
    triggerLoading,
    running,
    subscribe,
    unsubscribe,
    trigger,
    onCompletedHook,
    onStateChange,
  }
}
