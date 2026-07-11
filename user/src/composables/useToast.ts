/**
 * useToast — 轻量 toast 状态（每次调用独立实例）。
 * 视图自行渲染 toast 标记（沿用现有视觉）。
 *
 * 时长策略：success 默认 2.5s，error 默认 6s（错误信息需更多阅读时间）。
 * 支持：点击关闭（dismissToast）、悬停暂停（pauseToast/resumeToast）。
 * showToast 可显式传 duration 覆盖默认值。
 */
import { ref } from 'vue'

const DEFAULT_DURATION: Record<'success' | 'error', number> = {
  success: 2500,
  error: 6000,
}

export function useToast() {
  const toastVisible = ref(false)
  const toastMessage = ref('')
  const toastType = ref<'success' | 'error'>('success')
  let hideTimer: ReturnType<typeof setTimeout> | null = null
  let remaining = 0     // 剩余可见时长（ms）
  let startedAt = 0     // 当前计时起点（ms）

  function clearTimer() {
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null }
  }

  /** 立即关闭 toast。 */
  function dismissToast() {
    clearTimer()
    remaining = 0
    toastVisible.value = false
  }

  function showToast(msg: string, type: 'success' | 'error' = 'success', duration?: number) {
    toastMessage.value = msg
    toastType.value = type
    toastVisible.value = true
    clearTimer()
    const dur = duration ?? DEFAULT_DURATION[type]
    remaining = dur
    startedAt = Date.now()
    hideTimer = setTimeout(() => { toastVisible.value = false }, dur)
  }

  /** 悬停暂停自动隐藏（保留剩余时间）。 */
  function pauseToast() {
    if (!hideTimer) return
    clearTimer()
    remaining = Math.max(0, remaining - (Date.now() - startedAt))
  }

  /** 离开恢复自动隐藏（按剩余时间继续）。 */
  function resumeToast() {
    if (!toastVisible.value || hideTimer || remaining <= 0) return
    startedAt = Date.now()
    hideTimer = setTimeout(() => { toastVisible.value = false }, remaining)
  }

  return { toastVisible, toastMessage, toastType, showToast, dismissToast, pauseToast, resumeToast }
}
