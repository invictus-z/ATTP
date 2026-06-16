/**
 * 溯源模块共享类型定义。
 */

/** 行为溯源链的单条记录（扁平 chain） */
export interface BehaviorChainEntry {
  id?: number
  hop_count: number[]
  field_type: string
  sender_type: string
  sender_did: string
  target_did: string
  content: string
  timestamp: string | number | null
}

/** 单条行为条目（聚合到 hop 节点内） */
export interface BehaviorEntry {
  id?: number
  content: string
  target: string
  timestamp: string | number | null
  verification_status?: string
  node_type?: string
}

/** 按 hop_count + sender 聚合的节点 */
export interface HopNode {
  hop_count: number[]
  node_did: string
  A2T: BehaviorEntry[]
  A2U: BehaviorEntry[]
  U2A: BehaviorEntry[]
  A2A: BehaviorEntry[]
  T2A: BehaviorEntry[]
}

/** 纵向/横向分析报告 */
export interface AnalysisReport {
  id: number
  batch_index: number
  from_trace_id: number
  to_trace_id: number
  sessions_scanned?: number
  timestamp: string | number | null
  report: Record<string, any>
}

/** 告警（从分析报告提取） */
export interface Alert {
  report_id: number
  batch_index: number
  verdict: string
  summary: string
  from_trace_id: number
  to_trace_id: number
  timestamp: string | number | null
  suspicious_nodes: SuspiciousNode[]
}

export interface SuspiciousNode {
  node_did: string | null
  severity: string | null
  taint_score: number | null
  evidence: string | null
}

/** 分析任务状态 */
export interface AnalysisStatus {
  status: string          // running | completed | not_found | already_running ...
  session_id?: string
  did?: string
  phase?: string
  progress?: number
  triggered?: boolean
  reason?: string
}

/** 恶意节点报告（单条 incident） */
export interface MaliciousReport {
  id: number
  source: string
  target_did: string
  node_type: string
  session_id: string
  evidence_type: string
  severity: string
  taint_score: number
  evidence_description: string
  nonce: string
  report_id: number | null
  timestamp: number
  raw_evidence: Record<string, any>
}

/** 恶意节点档案 */
export interface MaliciousDossier {
  found?: boolean
  did: string
  total_violations: number
  severity_level: string          // clean / warning / dangerous / banned
  first_seen_at: number
  last_seen_at: number
  evidence_breakdown: Record<string, number>
  source_breakdown?: Record<string, number>
  last_evidence_type: string
  last_session_id: string
  last_evidence_desc: string
  incidents?: MaliciousReport[]
}

/** 横向分析累积状态 */
export interface HorizontalState {
  did: string
  accumulated_count: number
  last_trace_id: number
  batch_index: number
  node_type?: string
  has_context: boolean
}

/** 纵向分析累计状态（意图 + 分析状态，与后端 /state 嵌套结构对齐） */
export interface VerticalState {
  session_id: string
  intent: IntentDescriptor | null
  analysis_state: {
    batch_index: number
    last_trace_id: number
    report_count: number
    has_context: boolean
  }
}

/** 意图描述 */
export interface IntentDescriptor {
  original_task: string
  core_objective: string
  constraints: string[]
  involved_capabilities: string[]
  risk_level: string   // low / medium / high
}
