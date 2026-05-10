import { ref, reactive } from 'vue'

export interface TraceLog {
  timestamp: string
  source: string
  target: string
  sessionId: string
  payload: string
  direction: 'in' | 'out'
  type: string
}

const traceLogs = ref<TraceLog[]>([])
const traceFilter = reactive({ source: '', target: '', sessionId: '' })
const traceTimelineVisible = ref(false)
const flowDiagramVisible = ref(false)

export function useTrace() {
  const addTraceLog = (log: TraceLog) => {
    traceLogs.value.push(log)
    if (traceLogs.value.length > 500) traceLogs.value.shift()
  }

  const filteredTraceLogs = () => {
    return traceLogs.value.filter(log => {
      if (traceFilter.source && !log.source.toLowerCase().includes(traceFilter.source.toLowerCase())) return false
      if (traceFilter.target && !log.target.toLowerCase().includes(traceFilter.target.toLowerCase())) return false
      if (traceFilter.sessionId && !log.sessionId.toLowerCase().includes(traceFilter.sessionId.toLowerCase())) return false
      return true
    })
  }

  const clearTraceLogs = () => { traceLogs.value = [] }

  const exportTraceReport = () => {
    const logs = filteredTraceLogs()
    const report = logs.map(l => `[${l.timestamp}] ${l.direction === 'in' ? '←' : '→'} ${l.source} -> ${l.target} | ${l.type} | Session: ${l.sessionId}\n${l.payload}\n`).join('\n')
    const blob = new Blob([report], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `trace-report-${Date.now()}.txt`
    a.click(); URL.revokeObjectURL(url)
  }

  return {
    traceLogs, traceFilter, traceTimelineVisible, flowDiagramVisible,
    addTraceLog, filteredTraceLogs, clearTraceLogs, exportTraceReport,
  }
}