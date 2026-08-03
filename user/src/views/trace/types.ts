/**
 * 溯源模块共享类型定义（逐跳改版，对齐新协议节点 API）。
 *
 * 量纲：taint_score / score ∈ [0,10]（0.5 步进）；severity 五档；
 * overall_verdict 由代码推导（clean/suspicious/malicious）。
 */

/** 评分维度数组固定 4 维：d1 意图对齐 / d2 能力 / d3 注入 / d4 外泄 */
export type DimensionScore = [number, number, number, number]

/** 评分维度名（与后端 DIMENSION_NAMES 一致，供 HopScoreCard 标注） */
export const DIMENSION_LABELS = ['意图对齐', '能力/越权', '注入/操纵', '外泄/篡改'] as const

/** severity 五档（score [0,10] 分档） */
export type Severity = 'none' | 'low' | 'medium' | 'high' | 'critical'

/** overall_verdict（代码推导，不让 LLM 下） */
export type OverallVerdict = 'clean' | 'suspicious' | 'malicious'

/** 恶意报告来源 */
export type AnalysisSource = 'protocol_review' | 'vertical_analysis' | 'horizontal_analysis'

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

/** 证据引用（单跳评分 evidence_refs / 横轴 verdict.evidence_items） */
export interface EvidenceRef {
  description: string
  trace_ids: number[]
  field_type?: string
}

/** 意图增量 Δ 的来源（由哪条发起者 U2A 抽取） */
export interface IntentRevisionSource {
  trace_id: number
  did: string
  timestamp: number
}

/** 意图增量 Δ（发起者 U2A 抽取，追加进意图流） */
export interface IntentRevision {
  goal: string
  constraints: string[]
  prohibitions: string[]
  source?: IntentRevisionSource
}

/** 单跳评分（纵轴 V-Reasoner 输出） */
export interface HopScore {
  trace_id: number
  session_id: string
  sender_did: string
  field_type: string
  hop_count: number[]
  score: number
  dimensions: DimensionScore
  breadth: number
  severity: Severity
  deviation_type: string
  evidence_refs: EvidenceRef[]
  hidden_state: string
  timestamp: number
}

/** 横轴确认裁决（单 DID） */
export interface ConfirmationVerdict {
  did: string
  node_type: string
  confirmed: boolean
  severity: Severity
  taint_score: number
  threat_pattern: string
  evidence: string
  evidence_items: EvidenceRef[]
  sessions_reviewed: number
}

/** 横轴确认报告的 report blob（/api/analysis/h/report 里每条的 report 字段） */
export interface HorizontalReportBlob {
  did: string
  node_type: string
  batch_index: number
  from_trace_id: number
  to_trace_id: number
  sessions_scanned: number
  selected_sessions: string[]
  confirmed: boolean
  verdict: ConfirmationVerdict | null
  overall_verdict: OverallVerdict
  summary: string
  context_summary: string
  triggered_by: string          // "f_threshold" / "manual"
  timestamp: number
}

/** 横向分析报告（外层包装） */
export interface AnalysisReport {
  id: number
  batch_index: number
  from_trace_id: number
  to_trace_id: number
  sessions_scanned?: number
  timestamp: string | number | null
  report: HorizontalReportBlob
}

/** 纵向分析报告（/api/analysis/v/report 扁平对象，非数组） */
export interface VerticalReport {
  session_id: string
  initiator_did: string
  intent_revisions: IntentRevision[]
  hidden_state: string
  hop_scores: HopScore[]
  overall_verdict: OverallVerdict
  max_score: number
  total_hops: number
  last_scored_trace_id: number
}

/** 纵向分析状态（/api/analysis/v/state 扁平） */
export interface VerticalState {
  session_id: string
  initiator_did: string
  intent_revisions: IntentRevision[]
  has_hidden_state: boolean
  last_scored_trace_id: number
  intent_revision_count: number
}

/** 横向分析累积状态（/api/analysis/h/state 扁平：F / 未分析数 / 游标 / 批次 / R_S） */
export interface HorizontalState {
  did: string
  f_value: number               // 累积偏离 F_d = Σ s_i³（三次方和，闭案后归零）
  volume: number                // 自上次闭案以来喂入 F 的跳数（观测用）
  unanalyzed_count?: number     // 该节点在确认游标之后的全部未分析跳数
  last_trace_id: number         // 确认游标（最后一次分析位置）
  batch_index: number           // 已完成确认次数
  node_type?: string
  has_context: boolean
  r_s?: number                  // 横轴 F 累积阈值（后端 analysis.r_s，默认 200.0）
}

/** 分析任务状态（SSE analysis.progress + llm-status 轮询） */
export interface AnalysisStatus {
  status: string                // running | completed | idle | not_found | already_running ...
  session_id?: string
  did?: string
  phase?: string                // scoring/idle（纵）; selecting/confirming/saving_results（横）
  progress?: number
  triggered?: boolean
  reason?: string
  queue_depth?: number          // 积压跳数（llm-status）
}

/** 告警（保留：从分析报告提取的可疑节点） */
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
  severity: Severity | null
  taint_score: number | null
  evidence: string | null
}

/** 恶意节点报告（单条 incident） */
export interface MaliciousReport {
  id: number
  source: AnalysisSource
  target_did: string
  node_type: string
  session_id: string
  evidence_type: string
  severity: Severity
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
  severity_level: string          // clean / warning / dangerous / banned（按违规计数，4 档）
  first_seen_at: number
  last_seen_at: number
  evidence_breakdown: Record<string, number>
  source_breakdown?: Record<string, number>
  last_evidence_type: string
  last_session_id: string
  last_evidence_desc: string
  incidents?: MaliciousReport[]
}
