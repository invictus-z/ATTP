/**
 * useAnalysisFlow — 引导式分析流程状态机。
 *
 * 封装「查状态 → 未完成才显示触发 → 触发后轮询 → 完成后取报告」流程，
 * 纵向（v, session 级）与横向（h, did 级）共用，仅 URL 前缀不同。
 *
 *   GET  /api/analysis/{axis}/status/{id}
 *   POST /api/analysis/{axis}/trigger/{id}
 *
 * 任务状态词汇（来自后端 orchestrator）：running | completed | not_found。
 * 注意：任务异常时后端返回 status:"completed" 且 triggered:false + reason，
 * 视图据此判定失败。
 */

import { ref, onScopeDispose } from 'vue'
import { apiFetch } from '../transport'
import { useProtocolNodes } from './useProtocolNodes'
import type { AnalysisStatus } from '../views/trace/types'

const POLL_INTERVAL_MS = 1500
const POLL_TIMEOUT_MS = 60_000

export type AnalysisAxis = 'v' | 'h'

export function useAnalysisFlow(
  axis: AnalysisAxis,
  onCompleted?: (id: string) => void,
) {
  const { buildUrl } = useProtocolNodes()

  const status = ref<AnalysisStatus | null>(null)
  const triggerLoading = ref(false)
  const polling = ref(false)

  let timer: ReturnType<typeof setInterval> | null = null
  let timeoutGuard: ReturnType<typeof setTimeout> | null = null
  const completedHooks: Array<(id: string) => void> = []
  if (onCompleted) completedHooks.push(onCompleted)

  async function refreshStatus(id: string): Promise<void> {
    if (!id) { status.value = null; return }
    try {
      const url = buildUrl(`/api/analysis/${axis}/status/${encodeURIComponent(id)}`)
      const result = await apiFetch(url)
      if (result.ok) status.value = result.data as AnalysisStatus
    } catch {
      /* keep last known status */
    }
  }

  /** 触发分析；成功则自动开始轮询。返回是否触发成功。 */
  async function trigger(id: string): Promise<boolean> {
    if (!id) return false
    triggerLoading.value = true
    try {
      const url = buildUrl(`/api/analysis/${axis}/trigger/${encodeURIComponent(id)}`)
      const result = await apiFetch(url, { method: 'POST' })
      if (result.ok && result.data?.triggered) {
        await refreshStatus(id)
        startPolling(id)
        return true
      }
      return false
    } finally {
      triggerLoading.value = false
    }
  }

  function startPolling(id: string): void {
    stopPolling()
    polling.value = true
    timer = setInterval(async () => {
      await refreshStatus(id)
      const s = status.value?.status
      if (s === 'completed') {
        stopPolling()
        completedHooks.forEach(cb => cb(id))
      } else if (s && s !== 'running') {
        // not_found 等终态，停止轮询
        stopPolling()
      }
    }, POLL_INTERVAL_MS)
    timeoutGuard = setTimeout(stopPolling, POLL_TIMEOUT_MS)
  }

  function stopPolling(): void {
    if (timer) { clearInterval(timer); timer = null }
    if (timeoutGuard) { clearTimeout(timeoutGuard); timeoutGuard = null }
    polling.value = false
  }

  /** 追加 completed 回调（完成时拉报告）。 */
  function onCompletedHook(cb: (id: string) => void): void {
    completedHooks.push(cb)
  }

  onScopeDispose(() => stopPolling())

  return {
    status,
    triggerLoading,
    polling,
    refreshStatus,
    trigger,
    stopPolling,
    onCompletedHook,
  }
}
