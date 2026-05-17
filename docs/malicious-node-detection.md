# ATTP 恶意节点检测机制

## 概述

ATTP 协议节点通过 **MaliciousNodeDetector** 引擎检测恶意行为，检测结果持久化到 SQLite 数据库。系统采用两层存储设计：逐条检测明细 + per-DID 聚合档案。

## 检测触发场景

### 双回传（Dual Back-Propagation）

当协议节点收到同一 nonce 的两条回传消息时触发：

1. **Branch A**（第一条消息）→ 存入 `PendingMessage`，等待 60 秒超时
2. **Branch B**（第二条消息）→ 触发 `evaluate_dual_back_prop` 决策树

入口：`middleware.py` 中的 `intercept_record` 函数

### 单回传（Single Back-Propagation）

当 60 秒超时后仍只有一条消息时触发：

- `node.py` 中的 `_periodic_sweep()` 每 60 秒扫描过期 PendingMessage
- 调用 `evaluate_single_back_prop` 决策树

## 恶意行为分类（EvidenceType）

| 类型 | 枚举值 | 说明 |
|------|--------|------|
| 身份篡改 | `IDENTITY_TAMPERING` | 签名验证失败或 DID 解析失败 |
| 可信名单违规 | `TRUSTED_LIST_VIOLATION` | 节点 DID 不在最新可信名单中 |
| 内容篡改 | `CONTENT_TAMPERING` | 内容签名无法用发送方公钥验证 |
| 未转发 | `NO_PROPAGATION` | 节点收到消息但未回传 |
| 诬陷 | `FRAMING` | 伪造他人身份发送消息 |
| 不可区分对 | `INDISTINGUISHABLE_PAIR` | 无法判定双方谁恶意，两节点一起通报 |
| 同 DID 重复 | `SAME_DID_DUPLICATE` | 两条消息来自同一 DID（重放攻击） |

## 双回传决策树

```
回传1到达 → 存入 PendingMessage
回传2到达 → evaluate_dual_back_prop()
│
├─ Step 0a: 回传1身份签名检查
│   └─ 失败 → IDENTITY_TAMPERING（通报可信名单或发送者）
│
├─ Step 0b: 回传1可信名单校验
│   └─ DID ≠ 最新名单 → TRUSTED_LIST_VIOLATION（通报可信名单）
│
├─ Step 1: 回传2身份签名检查
│   └─ 失败 → IDENTITY_TAMPERING（判定回传1的 target）
│
├─ Step 2: DID 比对
│   └─ 两条 DID 相同 → SAME_DID_DUPLICATE
│
├─ Step 3: 回传1内容签名自检
│   └─ 失败 → CONTENT_TAMPERING（回传1节点为恶意）
│
└─ Step 4: 回传2内容签名交叉验证
    ├─ 通过 → 无恶意，正常流程
    └─ 失败 → INDISTINGUISHABLE_PAIR（两节点一起通报）
```

## 单回传决策树

```
超时后仅一条消息 → evaluate_single_back_prop()
│
├─ Case A: 身份签名无法验证
│   └─ IDENTITY_TAMPERING（垃圾消息）
│
├─ Case B: DID ≠ 最新可信名单
│   └─ TRUSTED_LIST_VIOLATION
│
└─ Case C: DID = 最新可信名单
    ├─ 有后续不同身份的消息 → NO_PROPAGATION
    ├─ 后续消息都来自同一恶意节点 → 抛弃（不记录）
    └─ 无后续消息 → 抛弃（垃圾消息）
```

## 数据库设计

### 表结构

#### malicious_nodes（逐条检测明细）

```sql
CREATE TABLE malicious_nodes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id              TEXT NOT NULL,          -- 检测所属 session
    malicious_did           TEXT NOT NULL,          -- 恶意节点 DID
    evidence_type           TEXT NOT NULL,          -- 违规类型枚举值
    evidence_description    TEXT,                   -- 违规描述
    severity                TEXT DEFAULT 'medium',  -- 严重程度
    nonce                   TEXT,                   -- 消息 nonce
    timestamp               REAL,                   -- 检测时间
    raw_evidence            TEXT DEFAULT '{}'        -- 原始证据 JSON
);

-- 索引
CREATE INDEX idx_mn_session ON malicious_nodes(session_id);
CREATE INDEX idx_mn_did ON malicious_nodes(malicious_did);
```

#### node_dossiers（per-DID 聚合档案）

```sql
CREATE TABLE node_dossiers (
    did                 TEXT PRIMARY KEY,           -- 恶意节点 DID（唯一）
    total_violations    INTEGER DEFAULT 0,          -- 累计违规次数
    severity_level      TEXT DEFAULT 'clean',       -- 档案等级
    first_seen_at       REAL,                       -- 首次检测时间
    last_seen_at        REAL,                       -- 最近一次检测时间
    evidence_breakdown  TEXT DEFAULT '{}',           -- JSON: 各类型累计次数
    last_evidence_type  TEXT DEFAULT '',             -- 最近一次违规类型
    last_session_id     TEXT DEFAULT '',             -- 最近一次违规所属 session
    last_evidence_desc  TEXT DEFAULT '',             -- 最近一次违规描述
    updated_at          REAL                        -- 档案最后更新时间
);
```

### 两表关系

```
node_dossiers (1) ←→ (N) malicious_nodes
      ↑                        ↑
  did (PK)              malicious_did (索引)
```

- `malicious_nodes` 是逐条明细，每次检测产生一条记录
- `node_dossiers` 是 per-DID 聚合，每个 DID 有且仅有一份档案
- 写入 `malicious_nodes` 时自动 upsert `node_dossiers`

### severity_level 递进规则

| 累计违规次数 | severity_level | 含义 |
|-------------|---------------|------|
| 0 | clean | 无记录 |
| 1 | warning | 首次违规，观察 |
| 2-3 | dangerous | 屡次违规，高危 |
| 4+ | banned | 累犯，建议封禁 |

### evidence_breakdown 示例

```json
{
    "identity_tampering": 2,
    "content_tampering": 1,
    "no_propagation": 3
}
```

## 数据写入流程

```
MaliciousNodeDetector 产出 MaliciousNodeReport
        │
        ▼
ProtocolTracer.save_malicious_report()
        │
        ├──▶ SqliteStore.save_malicious_report()
        │       │
        │       ├── INSERT INTO malicious_nodes  (逐条明细)
        │       │
        │       └── SqliteStore.upsert_dossier()  (自动聚合)
        │               │
        │               ├── 首次 → INSERT (total=1, severity='warning')
        │               └── 已有 → UPDATE (total+1, 更新 severity_level,
        │                                  更新 evidence_breakdown JSON)
        │
        └──▶ 向客户端返回 403
```

## 查询 API

### 按会话查询明细

```
GET /api/malicious/session/{session_id}
```

返回该 session 下所有恶意检测报告。

### 按 DID 查询明细

```
GET /api/malicious/did/{did}
```

返回该 DID 的所有恶意检测报告。

### 查询单个 DID 档案

```
GET /api/malicious/dossier/{did}
```

返回该 DID 的聚合档案，附带全部违规明细：

```json
{
    "found": true,
    "did": "did:attp:xxx",
    "total_violations": 3,
    "severity_level": "dangerous",
    "first_seen_at": 1715932800.0,
    "last_seen_at": 1716019200.0,
    "evidence_breakdown": "{\"identity_tampering\": 1, \"content_tampering\": 1, \"no_propagation\": 1}",
    "last_evidence_type": "no_propagation",
    "last_evidence_desc": "...",
    "incidents": [
        {
            "session_id": "...",
            "evidence_type": "identity_tampering",
            "evidence_description": "...",
            "nonce": "...",
            "timestamp": 1715932800.0
        }
    ]
}
```

### 查询所有档案

```
GET /api/malicious/dossiers?severity=warning&limit=50
```

支持 `severity` 筛选参数和 `limit` 分页参数。

## 关键文件

| 文件 | 职责 |
|------|------|
| `protocol_node/malicious_detector.py` | 恶意判定引擎，决策树实现 |
| `protocol_node/middleware.py` | 消息中间件，触发检测 |
| `protocol_node/node.py` | 节点主控，单回传超时扫描 |
| `core/storage/sqlite_store.py` | SQLite 存储层，两张表的读写 |
| `core/pn_tracer.py` | 存储门面，透传查询方法 |
| `protocol_node/api/malicious.py` | 查询 API 路由 |
| `core/sessions/protocol_node/session.py` | 会话管理，可信名单维护 |
