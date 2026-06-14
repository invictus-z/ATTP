/**
 * useToast — 轻量 toast 状态（每次调用独立实例）。
 * 视图自行渲染 toast 标记（沿用现有视觉）。
 */
import { ref } from 'vue'

export function useToast() {
  const toastVisible = ref(false)
  const toastMessage = ref('')
  const toastType = ref<'success' | 'error'>('success')
  let hideTimer: ReturnType<typeof setTimeout> | null = null

  function showToast(msg: string, type: 'success' | 'error' = 'success') {
    toastMessage.value = msg
    toastType.value = type
    toastVisible.value = true
    if (hideTimer) clearTimeout(hideTimer)
    hideTimer = setTimeout(() => { toastVisible.value = false }, 2500)
  }

  return { toastVisible, toastMessage, toastType, showToast }
}
