/**
 * useTraceFormat — 溯源模块共享的徽章 / 格式化工具。
 *
 * 纯函数 + 常量，无响应式状态，跨视图复用。
 */

export interface BadgeStyle {
  text: string
  cls: string
}

export const fieldTypes = ['A2T', 'A2U', 'U2A', 'A2A', 'T2A'] as const

export const fieldTypeConfig: Record<string, { label: string; color: string; bg: string; border: string }> = {
  A2T: { label: 'Agent→Tool', color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200' },
  A2U: { label: 'Agent→User', color: 'text-purple-600', bg: 'bg-purple-50', border: 'border-purple-200' },
  U2A: { label: 'User→Agent', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  A2A: { label: 'Agent→Agent', color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-200' },
  T2A: { label: 'Tool→Agent', color: 'text-cyan-600', bg: 'bg-cyan-50', border: 'border-cyan-200' },
}

export function verificationBadge(status?: string): BadgeStyle {
  if (!status) return { text: '未知', cls: 'bg-gray-100 text-gray-500 border-gray-200' }
  if (status === 'verified') return { text: '已验证', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (status === 'unverified') return { text: '未验证', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (status === 'tampered') return { text: '已篡改', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: status, cls: 'bg-gray-100 text-gray-500 border-gray-200' }
}

export function verdictBadge(verdict: string): BadgeStyle {
  if (verdict === 'clean') return { text: 'Clean', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (verdict === 'suspicious') return { text: 'Suspicious', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (verdict === 'malicious') return { text: 'Malicious', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: verdict, cls: 'bg-gray-100 text-gray-500 border-gray-200' }
}

/** 仅返回 class（用于不需要 text 的场景）。severity 五档：none/low/medium/high/critical */
export function severityBadgeCls(sev: string): string {
  if (sev === 'critical') return 'bg-red-100 text-red-700 border-red-300'
  if (sev === 'high') return 'bg-red-50 text-red-600 border-red-200'
  if (sev === 'medium') return 'bg-amber-50 text-amber-600 border-amber-200'
  if (sev === 'low') return 'bg-blue-50 text-blue-600 border-blue-200'
  return 'bg-gray-50 text-gray-500 border-gray-200'   // none / 未知
}

/** incident 行级背景 + 边框色（五档），供 MaliciousView 等行容器复用 */
export function severityRowCls(sev: string): string {
  if (sev === 'critical') return 'bg-red-50/60 border-red-200'
  if (sev === 'high') return 'bg-red-50/50 border-red-200'
  if (sev === 'medium') return 'bg-amber-50/50 border-amber-200'
  if (sev === 'low') return 'bg-blue-50/50 border-blue-200'
  return 'bg-gray-50/50 border-gray-200'   // none / 未知
}

export function severityLevelBadge(level: string): BadgeStyle {
  if (level === 'clean') return { text: 'Clean', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (level === 'warning') return { text: 'Warning', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (level === 'dangerous') return { text: 'Dangerous', cls: 'bg-orange-50 text-orange-600 border-orange-200' }
  if (level === 'banned') return { text: 'Banned', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: level, cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

export function riskLevelBadge(level: string): BadgeStyle {
  if (level === 'low') return { text: 'Low', cls: 'bg-emerald-50 text-emerald-600 border-emerald-200' }
  if (level === 'medium') return { text: 'Medium', cls: 'bg-amber-50 text-amber-600 border-amber-200' }
  if (level === 'high') return { text: 'High', cls: 'bg-red-50 text-red-600 border-red-200' }
  return { text: level, cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

export function sourceBadge(source: string): BadgeStyle {
  if (source === 'protocol_review') return { text: '协议审查', cls: 'bg-blue-50 text-blue-600 border-blue-200' }
  if (source === 'vertical_analysis') return { text: '纵向分析', cls: 'bg-purple-50 text-purple-600 border-purple-200' }
  if (source === 'horizontal_analysis') return { text: '横向分析', cls: 'bg-orange-50 text-orange-600 border-orange-200' }
  return { text: source, cls: 'bg-gray-50 text-gray-500 border-gray-200' }
}

export function formatTime(ts: string | number | null): string {
  if (!ts && ts !== 0) return '--'
  try {
    let d: Date
    if (typeof ts === 'number') {
      // 后端 time.time()/TS SDK 均为秒；旧版用户端曾误用 Date.now()(毫秒)。
      // 按数量级自适应：>1e11 视为毫秒（当前秒级时间戳 ~1.7e9），避免再 ×1000 溢出。
      d = ts > 1e11 ? new Date(ts) : new Date(ts * 1000)
    } else {
      d = new Date(ts)
    }
    if (isNaN(d.getTime())) return String(ts)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(ts)
  }
}

/** DID 取最后一段做简短展示 */
export function formatDid(did: string): string {
  if (!did) return '--'
  const parts = did.split(':')
  return parts.length > 1 ? parts[parts.length - 1] : did
}

/**
 * 把扁平 behavior chain 聚合成按 hop_count + sender 分组的节点列表。
 */
export function transformChainToNodes<T extends {
  hop_count: number[]
  sender_did: string
  field_type: string
  id?: number
  target_did?: string
  content?: string
  timestamp?: string | number | null
}>(chain: T[]): import('../views/trace/types').HopNode[] {
  const nodeMap = new Map<string, import('../views/trace/types').HopNode>()

  chain.forEach(entry => {
    const key = `${entry.hop_count.join('.')}_${entry.sender_did}`

    if (!nodeMap.has(key)) {
      nodeMap.set(key, {
        hop_count: entry.hop_count,
        node_did: entry.sender_did,
        A2T: [],
        A2U: [],
        U2A: [],
        A2A: [],
        T2A: [],
      })
    }

    const node = nodeMap.get(key)!
    const behaviorEntry = {
      id: entry.id,
      content: entry.content || '',
      target: entry.target_did || '',
      timestamp: entry.timestamp ?? null,
    }

    if (entry.field_type === 'A2T') node.A2T.push(behaviorEntry)
    else if (entry.field_type === 'A2U') node.A2U.push(behaviorEntry)
    else if (entry.field_type === 'U2A') node.U2A.push(behaviorEntry)
    else if (entry.field_type === 'A2A') node.A2A.push(behaviorEntry)
    else if (entry.field_type === 'T2A') node.T2A.push(behaviorEntry)
  })

  return Array.from(nodeMap.values()).sort((a, b) => {
    const [a0, a1] = a.hop_count
    const [b0, b1] = b.hop_count
    if (a0 !== b0) return a0 - b0
    return a1 - b1
  })
}
