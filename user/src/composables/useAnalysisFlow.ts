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

  /** 轮询 llm-status 取 queue_depth / phase。
   *  逐跳改版后纵轴状态由 worker phase 驱动：phase=scoring/有积压 → 分析中；
   *  phase=idle 且无积压 → 空闲（停止轮询）。横轴 completed/not_found 同样收敛。 */
  async function pollLlmStatus(id: string): Promise<void> {
    const url = buildUrl(`/api/analysis/${axis}/llm-status/${encodeURIComponent(id)}`)
    if (!url) return
    try {
      const res = await apiFetch(url)
      if (!res.ok || !res.data) return
      const s = res.data.status
      const phase = res.data.phase
      const qd = res.data.queue_depth ?? 0
      // 终态：worker 空闲 / 分析未启用 / 无任务 / 纵轴打分完毕 → 空闲，停轮询
      if (s === 'idle' || s === 'disabled' || s === 'not_found' ||
          (axis === 'v' && phase === 'idle' && qd === 0)) {
        stopPolling()
        status.value = makeStatus('idle', {}, id)
        return
      }
      // 横轴确认已完成 → completed（通常 analysis.report 已先行处理，此处兜底）
      if (s === 'completed') {
        stopPolling()
        status.value = makeStatus('completed', { triggered: true }, id)
        return
      }
      // 运行中：刷新 phase / 积压跳数
      status.value = makeStatus('running', { phase, queue_depth: qd }, id)
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
    // 订阅即探一次 worker 状态：若查询时正在逐跳打分，立即显示「分析中」并开轮询。
    void pollLlmStatus(id)
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
        // 纵轴逐跳打分自动进行（无需手动触发）：每出一跳分即标「分析中」并刷新报告；
        // worker 空闲后由 pollLlmStatus 转回「空闲」。
        status.value = makeStatus('running', { phase: 'scoring' }, id)
        startPolling(id)
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
