# 协议节点 API 文档


## 量纲与分档

- **taint_score / score**：`[0,10]`，0.5 步进。
- **severity** 五档：`none`(<1.5) / `low`(<3.5) / `medium`(<5.5) / `high`(<7.5) / `critical`(≤10)。
- **4 个评分维度**（每跳独立 `[0,10]`）：
  - `d1` 意图对齐（intent_alignment）
  - `d2` 能力域 / 越权（capability）
  - `d3` 注入与操纵（injection_manipulation）
  - `d4` 外泄与篡改（exfiltration_tampering）
  - 默认聚合 `s_i = max(d1..d4)`；`breadth` = 超过 medium 的维度数。
- **overall_verdict**（代码推导，不让 LLM 下）：任跳 critical→`malicious`、任跳 high→`suspicious`、否则 `clean`。

## 触发阈值（`analysis` 配置；R_S 已标定 cube@R_S=200）

横向 F 为**三次方和** `F_d = Σ s_i³`（自上次闭案以来该 DID 全部已打分跳；无折扣 γ、无死区 d），
单调递增，超 `R_S`（且累计跳数 ≥ 2）即触发确认并清零重累。`v_max`/`gamma`/`dead_zone_d` 已移除；
每次确认会**汇入上一次确认报告**，防止攻击者把攻击拆到多个会话集（batch）各自判良性。
> 注：会话选取权重 `W(σ) = Σ s_j²` 仅用于从候选会话里选 α 个，**不是** F 累积公式。

| 参数 | 默认 | 含义 |
|---|---|---|
| `horizontal_enabled` | true | 是否启用横轴 F 累加 + 确认 |
| `aggregation` | "max" | 单跳 4 维聚合：`s_i = max(d1..d4)` |
| `r_t` | 7.5 | 单点阈值：`s_i > R_T` 立即告警（critical 下沿） |
| `r_s` | 200.0 | 累积阈值：`F_d = Σ s_i³ > R_S`（且 volume ≥ 2）触发横轴确认 |
| `rho` | 8.0 | 高危兜底：会话内任一跳 `s_j ≥ ρ` 无条件纳入确认 |
| `rho_k` | 8.0 | 单维 critical 阈值：`d_k ≥ ρ_k` |
| `alpha` | 10 | 横轴确认上限：候选会话 > α 时按 W(σ) 取 α 个；≤ α 取全量（高危兜底不占名额） |
| `concurrency` | 8 | 全局并发 LLM 调用上限 |
| `queue_maxsize` | 1000 | 纵轴 per-session 有界队列容量（满则溢出转 catch-up 扫描补打，不丢数据） |

---

## 1. 写入

### `POST /record`
全网回传唯一入口。验签落库后**只投递逐跳任务即返回**（不 await LLM）。
- 200 `{"status": "Record verified and saved"}`（已落库并唤醒会话 worker）
- 200 `{"status": "stored", "nonce": ..., "session_id": ...}`（首条回传暂存待配对）
- 403 `{"status": "malicious_detected", "malicious_dids": [...], "evidence_type": ..., "description": ...}`（双回传恶意判定）
- 4xx `{"error": ...}`（字段/DID/签名/hop_count 等错误，见 `ERROR_MAP`）

---

## 2. 行为溯源（只读）

### `GET /api/status`
```json
{"status": "ok", "service": "protocol_node"}
```

### `GET /api/behavior/{session_id}?protocol_node_address=`
按 `hop_count` 排序的扁平行为链。
```json
{
  "session_id": "...",
  "protocol_node_address": "...",
  "chain": [
    {"hop_count": [0,0], "field_type": "U2A", "sender_type": "user",
     "sender_did": "...", "target_did": "...", "content": "...", "timestamp": 1.0}
  ]
}
```

---

## 3. 恶意报告 / 节点档案（只读）

`taint_score` 为 `[0,10]`，`severity` 为五档之一；`source` 取值：
`protocol_review`（双回传判定）/ `vertical_analysis`（R_T 单点告警）/ `horizontal_analysis`（横轴确认）。

### `GET /api/malicious/reports?session_id=&did=&source=&limit=100`
```json
{"total": 1, "reports": [{
  "id": 1, "source": "vertical_analysis", "target_did": "...", "node_type": "agent",
  "session_id": "...", "evidence_type": "data_exfiltration", "severity": "critical",
  "taint_score": 9.5, "evidence_description": "...", "report_id": null, "nonce": "",
  "timestamp": ..., "raw_evidence": {"trace_id": 5, "dimensions": [9,9,8,9.5], "breadth": 4, "evidence_items": [...]}
}]}
```

### `GET /api/malicious/dossier/{did}`
单 DID 档案 + 全部违规明细（`incidents`）+ 来源分布（`source_breakdown`）。

### `GET /api/malicious/dossiers?severity=&source=&limit=100`
全部档案，每条附 `source_breakdown`。

---

## 4. 纵向逐跳分析（只读 + 触发，prefix `/api/analysis/v`）

### `GET /api/analysis/v/report/{session_id}`
会话内逐跳评分聚合（`overall_verdict` 由代码推导）。
```json
{
  "session_id": "...", "initiator_did": "...",
  "intent_revisions": [{"goal": "...", "constraints": [...], "prohibitions": [...],
                        "source": {"trace_id": 1, "did": "...", "timestamp": 1.0}}],
  "hidden_state": "h: ...",
  "hop_scores": [{
    "trace_id": 5, "session_id": "...", "sender_did": "...", "field_type": "A2T",
    "hop_count": [1,3], "score": 9.5, "dimensions": [9,9,8,9.5], "breadth": 4,
    "severity": "critical", "deviation_type": "data_exfiltration",
    "evidence_refs": [{"description": "...", "trace_ids": [5], ...}],
    "hidden_state": "h: ...", "timestamp": 5.0
  }],
  "overall_verdict": "malicious", "max_score": 9.5, "total_hops": 4,
  "last_scored_trace_id": 5
}
```

### `GET /api/analysis/v/state/{session_id}`
```json
{"session_id": "...", "initiator_did": "...", "intent_revisions": [...],
 "has_hidden_state": true, "last_scored_trace_id": 5, "intent_revision_count": 1}
```

### `GET /api/analysis/v/aggregate/{session_id}?protocol_node_address=`
`traces.chain` + `traces.total_entries` + `hop_scores` + `alerts`（source=vertical_analysis）+ 推导 `overall_verdict`；
顶层另返回 `total_hops` / `total_alerts`。

### `POST /api/analysis/v/trigger/{session_id}`
手动触发：补打该会话未评分的跳（异步）。
```json
{"triggered": true, "status": "running", "session_id": "..."}
```
分析未启用时返回 `{"triggered": false, "reason": "analysis_disabled"}`。

### `GET /api/analysis/v/llm-status/{session_id}`
worker 状态（供轮询）。
```json
{"status": "running", "phase": "scoring|idle|intent_appended", "queue_depth": 0, "session_id": "..."}
```
- `status`：`running`（worker 存活）/ `idle`（worker 已退出）/ `disabled`（分析未启用）。
- `queue_depth` = 该会话有界队列当前积压跳数（`queue_maxsize` 满则溢出转 catch-up 扫描补打）。

---

## 5. 横向 F 累加 + 确认（只读 + 触发，prefix `/api/analysis/h`）

### `GET /api/analysis/h/state/{did}`
```json
{"did": "...", "f_value": 56.25, "volume": 3, "unanalyzed_count": 2,
 "last_trace_id": 5, "batch_index": 1, "node_type": "agent", "has_context": true, "r_s": 200.0}
```
- `f_value`：累积偏离 `F_d = Σ s_j³`（三次方和，跨会话叠加；闭案后归零）。
- `volume`：自上次闭案以来喂入 F 的跳数（仅 sub-R_T 评分跳，观测用）。
- `unanalyzed_count`：该节点在确认游标 `last_trace_id` 之后的全部跳数（最后一次分析位置 → 最新位置）。
- `last_trace_id`：确认游标。`batch_index`：已完成确认次数（已有报告数）。
- `r_s`：横轴 F 累积阈值（来自协调器，横轴未启用时为 `null`；前端 F 进度条分母应取此值）。

### `GET /api/analysis/h/report/{did}`
DID 全部确认报告。
```json
{"did": "...", "reports": [{
  "id": 1, "batch_index": 1, "from_trace_id": 0, "to_trace_id": 5,
  "sessions_scanned": 1, "timestamp": ...,
  "report": {
    "did": "...", "node_type": "agent", "confirmed": true,
    "verdict": {"severity": "critical", "taint_score": 9.0, "threat_pattern": "cross_session_apt",
                "evidence": "...", "evidence_items": [...], "sessions_reviewed": 1},
    "overall_verdict": "malicious", "triggered_by": "f_threshold",
    "selected_sessions": ["sess-1"], "summary": "...", "context_summary": "..."
  }
}], "total_batches": 1}
```

### `POST /api/analysis/h/trigger/{did}`
手动触发横轴确认（异步）。分析未启用时返回 `{"triggered": false, "reason": "analysis_disabled"}`。

### `GET /api/analysis/h/llm-status/{did}`
确认任务状态。
- `status`：`running`（`phase`: selecting / confirming / saving_results）/ `completed`（带结果体）/ `not_found`（无任务）/ `disabled`（分析未启用）。

---

## 6. 十字锁定综合视图

### `GET /api/analysis/cross-lock/{session_id}?protocol_node_address=`
一次聚出纵轴逐跳评分 + 各涉及 DID 的横轴 F/volume/最近确认。
```json
{
  "session_id": "...",
  "vertical": {"traces": 5, "hop_scores": [...], "overall_verdict": "malicious",
               "total_hops": 4, "alerts": [...]},
  "horizontal": {"tracked_dids": [{
    "did": "...", "f_value": 0.0, "volume": 0, "batch_index": 1,
    "last_horizontal_analysis": {"batch_index": 1, "confirmed": true, "overall_verdict": "malicious", "timestamp": ...}
  }]}
}
```

---

## 7. SSE 事件流

### `GET /api/events?session_id=&did=&topics=trace,analysis,malicious,record`
标准 SSE。`event` 为事件 type，`data` 为 JSON。

| event type | topic | 触发 | 关键字段 |
|---|---|---|---|
| `trace.recorded` | trace | 落库一条 behavior_trace | `session_id`, `trace_id`, `hop_count`, `field_type`, `sender_did`, `target_did`, `content`(截断 500), `timestamp` |
| `hop.scored` | analysis | 纵轴打出一跳分 | `session_id`, `trace_id`, `sender_did`, `field_type`, `score`, `severity`, `dimensions[4]`, `breadth` |
| `analysis.progress` | analysis | 纵/横阶段变化 | `axis`, `session_id`/`did`, `phase`, (纵向 `intent_appended` 另带 `trace_id`) |
| `analysis.report` | analysis | 横轴确认完成 | `axis=horizontal`, `did`, `batch_index`, `confirmed`, `verdict`, `summary`, `report_id`；无新分时另发 `{axis, did, triggered:false, reason:"no_new_scores"}` |
| `horizontal.accumulated` | analysis | 横轴 F/volume 累加 | `axis`, `did`, `session_id`, `trace_id`, `score`, `f_value`, `volume`, `r_s` |
| `horizontal.triggered` | analysis | 横轴确认被触发 | `axis`, `did`, `reason`(f_threshold), `f_value`, `volume` |
| `malicious.detected` | malicious | 写入一条恶意报告 | `did`, `severity`, `source`, `session_id`, `report_id`, `evidence_type`, `evidence_description` |
| `record.error` | record | /record 拒绝 | `session_id`, `nonce`, `node_did`, `protocol_url`, `hop_count`, `sender_did`, `target_did`, `error_key`, `error_message`, `status_code` |

过滤：`session_id` 匹配 payload.session_id；`did` 匹配 payload.did/target_did。
`analysis.progress.phase` 取值：纵向 `scoring` / `idle` / `intent_appended`；横向 `starting` / `selecting` / `confirming` / `saving_results`。
