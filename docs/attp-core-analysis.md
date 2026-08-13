# ATTP Core 层代码与功能分析

> 本文档对 `python/attp/core/` 目录下的所有模块进行全面的代码结构与功能分析，内容与 `dev` 分支（v0.3.0 逐跳有状态意图追踪）代码逐项核对。

## 目录

- [1. 概述](#1-概述)
- [2. 模块架构总览](#2-模块架构总览)
- [3. 顶层门面（Facade）](#3-顶层门面facade)
- [4. 认证模块（authentication）](#4-认证模块authentication)
- [5. 溯源模块（provenance）](#5-溯源模块provenance)
- [6. 消息模块（message）](#6-消息模块message)
- [7. 分析模块（analysis）— 十字锁定意图追踪](#7-分析模块analysis-十字锁定意图追踪)
- [8. 存储模块（storage）](#8-存储模块storage)
- [9. 会话模块（sessions）](#9-会话模块sessions)
- [10. SSE 子系统（sse）](#10-sse-子系统sse)
- [11. 核心数据流](#11-核心数据流)
- [12. 数据库表结构](#12-数据库表结构)
- [13. 设计模式与总结](#13-设计模式与总结)

---

## 1. 概述

ATTP Core 层是整个协议的核心实现，承载了 ATTP 四层架构的核心实现：

| 协议层 | Core 对应模块 |
|--------|--------------|
| 身份管理和加密通信层 | `authentication/`、`provenance/` — DID 身份认证、密钥管理、签名验证、哈希链与回传一致性校验 |
| 会话层 | `message/`、`sessions/` — 节点类型、行为类型与消息格式（单跳记录 / 转发消息 / 回传消息）、会话状态管理 |
| 消息固化层 | `storage/` — 行为轨迹 / 会话 / 分析 / 恶意档案的持久化（仓库模式）；固化验证管线编排于协议节点 |
| 意图追踪层 | `analysis/` — LLM 驱动的逐跳语义意图评分与跨会话确认 |
| 事件推送 | `sse/` — 进程内事件总线 + SSE 帧序列化（供协议节点推送给用户端） |

> **dev 分支边界**：v0.3.0 的身份管理和加密通信层仅实现 DID 身份认证（`anp` / `did:wba`）与消息内容签名（溯源链）。端到端加密（E2EE）/ TLS / 统一 transport-security 抽象层**不在 `dev` 分支**（位于 `refactor/transport` 分支，对应 README 的 v0.4.0 开发中），本文档不将其描述为已实现。

Core 层同时提供两个**门面（Facade）类**，分别服务于两种不同角色的节点：

- **Agent 侧**：`AgentTracer` — 轻量级，无数据库依赖，仅组合 KeyStore + ChainManager
- **协议节点侧**：`ProtocolTracer` — 完整功能，包含 KeyStore + ChainManager + SqliteStore

---

## 2. 模块架构总览

```
core/
├── __init__.py                  # 模块声明
├── agent_tracer.py              # Agent 侧门面
├── pn_tracer.py                 # 协议节点侧门面
│
├── authentication/              # 认证模块
│   ├── keys.py                  # 密钥加载与缓存（KeyStore）
│   ├── signatures.py            # 签名与验签引擎（多算法）
│   └── did_resolver.py          # DID 文档解析器（TTL 缓存 + 重试）
│
├── provenance/                  # 溯源模块
│   ├── hashing.py               # SHA-256 哈希计算（genesis / hop）
│   └── chain.py                 # 链管理器（追加跳 / 校验 / 回传验证）
│
├── message/                     # 消息模块
│   ├── event.py                 # 消息数据结构（RecordedHop / NodeMessage / BackMessage）
│   ├── back_sender.py           # BackMessage 统一发送函数
│   └── init.py                  # 便捷导出（RecordedHop / NodeMessage / BackMessage / send_back_message）
│
├── analysis/                    # 十字锁定意图追踪模块（逐跳有状态改版）
│   ├── __init__.py              # 模块声明（CrossLockCoordinator 入口）
│   ├── base_models.py           # 共享评分常量 + IntentRevision / HopScore / EvidenceItem
│   ├── cross_lock.py            # 十字锁定协调器（逐跳回调桥接纵→横）
│   ├── vertical/                # 纵轴 — per-session 逐跳 V-Reasoner
│   │   ├── models.py            # VerticalSessionReport（会话级聚合视图，只读端点用）
│   │   ├── analyzer.py          # VerticalIntentAnalyzer — 抽意图增量 + 逐跳 4 维评分
│   │   ├── prompts.py           # INTENT_REVISION_PROMPT + HOP_SCORING_PROMPT
│   │   └── orchestrator.py      # VerticalOrchestrator — per-session 有界队列 worker
│   └── horizontal/              # 横轴 — per-DID F 累加 + 跨会话确认
│       ├── models.py            # CrossSessionProfile / ConfirmationVerdict / ConfirmationReport
│       ├── analyzer.py          # HorizontalIntentAnalyzer — 跨会话确认器
│       ├── prompts.py           # CONFIRMATION_PROMPT（含跨 batch 上下文）
│       └── orchestrator.py      # HorizontalOrchestrator — F 累加 + α 会话选择 + 确认
│
├── storage/                     # 存储模块
│   ├── database.py              # aiosqlite 连接管理与 DDL（含幂等迁移）
│   ├── store.py                 # SqliteStore 外观类
│   └── repositories/            # Repository 模式
│       ├── base.py              # 基类
│       ├── trace_repo.py        # behavior_traces 仓储
│       ├── analysis_repo.py     # vertical_hop_scores + vertical_analysis_states 仓储（VerticalRepository）
│       ├── horizontal_repo.py   # horizontal_analysis_states + reports 仓储
│       ├── malicious_repo.py    # malicious_reports / node_dossiers 仓储（统一格式）
│       └── session_repo.py      # protocol_session_state 仓储
│
├── sessions/                    # 会话模块
│   ├── node_message.py          # BehaviorEntry 行为记录
│   ├── app/                     # App 层会话
│   │   ├── session.py           # AppSession
│   │   └── manager.py           # AppSessionManager
│   ├── protocol_node/           # 协议节点层会话
│   │   ├── session.py           # ProtocolSession（含 VerticalAnalysisState）
│   │   ├── manager.py           # ProtocolSessionManager
│   │   ├── pending_message.py   # PendingMessage
│   │   └── management/          # 分析状态管理（独立于 Session）
│   │       ├── vertical_state.py   # VerticalAnalysisManager
│   │       └── horizontal_state.py # HorizontalAnalysisManager
│   └── tools/                   # 工具节点层会话
│       ├── session.py           # ToolSession
│       └── manager.py           # ToolSessionManager
│
└── sse/                         # SSE 事件子系统
    ├── broker.py                # EventBroker 进程内发布-订阅总线
    ├── frames.py                # SSE 帧序列化（format_event_frame / HEARTBEAT）
    └── schema.py                # Topic / EventType 事件词汇表
```

### 模块依赖关系

```
AgentTracer ─────┬──→ KeyStore (authentication.keys)
                 └──→ ChainManager (provenance.chain)
                        ├──→ KeyStore
                        ├──→ sign_hash / verify_signature (authentication.signatures)
                        └──→ calculate_hop_hash (provenance.hashing)

ProtocolTracer ──┬──→ KeyStore
                 ├──→ ChainManager
                 └──→ SqliteStore (storage.store)
                       ├──→ Database (storage.database)
                       └──→ TraceRepository / VerticalRepository /
                            HorizontalRepository / MaliciousRepository /
                            ProtocolSessionRepository

CrossLockCoordinator ──┬──→ VerticalOrchestrator
                       │       ├──→ VerticalIntentAnalyzer
                       │       ├──→ VerticalAnalysisManager
                       │       │       └──→ ProtocolSessionManager + ProtocolTracer
                       │       ├──→ ProtocolTracer（save_hop_score 等）
                       │       └──→ EventBroker（可选，发布 hop.scored 等）
                       └──→ HorizontalOrchestrator [可选]
                               ├──→ HorizontalIntentAnalyzer
                               ├──→ HorizontalAnalysisManager
                               │       └──→ SqliteStore
                               ├──→ ProtocolTracer（query_hop_scores_by_did 等）
                               └──→ EventBroker（可选，发布 horizontal.accumulated 等）
```

---

## 3. 顶层门面（Facade）

### 3.1 AgentTracer（`agent_tracer.py`）

Agent 侧的**轻量级门面**，为 `ATTPClient`、`ATTPServer`、`MCPToolBridge` 等组件提供统一的溯源操作入口。

**设计原则**：无数据库依赖，仅组合 KeyStore（密钥缓存）和 ChainManager（跳构建）。

```python
class AgentTracer:
    def __init__(self) -> None
    def cache_public_key(self, node_did: str, public_key) -> None
    def load_private_key(self, key_path: str)
    def append_hop(self, metadata, content, node_did, target_did, private_key_path, behavior_type=None) -> dict
    @property key_store -> KeyStore
```

**核心功能**：
- `cache_public_key()` — 在验证前注入对方节点的公钥
- `load_private_key()` — 加载私钥（带缓存，同路径只加载一次，委托给 KeyStore）
- `append_hop()` — 构建新的跳记录（含签名），委托给 ChainManager

### 3.2 ProtocolTracer（`pn_tracer.py`）

协议节点侧的**完整门面**，组合了认证、溯源和存储三大能力。通过异步工厂方法 `create()` 初始化数据库连接。

```python
class ProtocolTracer:
    @classmethod
    async def create(cls, db_path: str) -> ProtocolTracer

    # 密钥管理
    def cache_public_key(self, node_did, public_key) -> None
    @property key_store -> KeyStore
    @property chain -> ChainManager
    @property storage -> SqliteStore

    # 链验证
    def verify_back_propagation(self, stored_hop, prev_hop, session_id) -> tuple[bool, str]

    # 行为追踪
    async def save_behavior_entry(...) -> int
    async def recover_behavior_trace(session_id, protocol_node_address=None) -> list
    async def recover_traces_since(session_id, since_id) -> tuple[list, int]

    # 逐跳评分（纵轴落库 / 查询）
    async def save_hop_score(score: dict) -> int
    async def query_hop_scores_by_session(session_id) -> list
    async def query_hop_scores_by_did(did, since_id=0) -> list
    async def max_trace_id_for_did(did) -> int
    async def max_trace_id_for_session(session_id) -> int

    # 纵向状态（意图流 / 隐状态 / 打分游标）
    async def save_vertical_state(session_id, state) -> None
    async def load_vertical_state(session_id) -> dict | None

    # 恶意节点报告（协议审查路径：接收 MaliciousNodeReport 对象）
    async def save_malicious_report(report) -> None          # 遍历 report.malicious_dids 落库
    async def query_malicious_nodes(session_id=None, malicious_did=None) -> list  # 兼容旧接口
    async def query_malicious_reports(session_id=None, target_did=None, source=None) -> list

    # 节点档案
    async def query_dossier(did) -> dict | None
    async def query_all_dossiers(severity_level=None, source=None, limit=100) -> list  # 附带 source_breakdown
```

> **注意 `save_malicious_report` 的两条路径**：`ProtocolTracer.save_malicious_report` 接收的是协议审查产出的 `MaliciousNodeReport` 对象（含 `malicious_dids` 列表、`evidence_type.value` 等），逐 DID 转成统一 dict 后写入；而纵轴 `_notify_rt_alert` 与横轴 `_notify_confirmed` 则**直接调用 `self._tracer.storage.save_malicious_report(dict)`**（已组装好的统一格式 dict，`source` 分别为 `vertical_analysis` / `horizontal_analysis`）。

> **向后兼容**：文件末尾提供别名 `MessageTracer = ProtocolTracer`。

---

## 4. 认证模块（authentication）

认证模块提供完整的分布式身份认证能力，包括密钥管理、多算法签名引擎和 DID 文档解析。

### 4.1 KeyStore（`keys.py`）

密钥缓存管理器，维护两个内存缓存字典：

| 缓存 | Key | Value | 用途 |
|------|-----|-------|------|
| `_cache` | `node_did` | 公钥对象 | 验证对方签名时查找公钥 |
| `_private_key_cache` | 解析后的文件绝对路径 | 私钥对象 | 避免重复加载同一私钥文件 |

**关键方法**：

- `load_private_key(key_path)` — 带缓存的私钥加载。将路径 `Path.expanduser().resolve()` 为绝对路径后缓存，后续相同路径直接返回缓存对象
- `cache_public_key(node_did, public_key)` — 注入公钥到缓存（由 DIDResolver 或外部调用）
- `get(node_did)` — 获取缓存的公钥，不存在返回 `None`
- `cache_dict`（property） — 暴露内部 `_cache` 字典引用，维持 `tracer._pub_key_cache` 的兼容性

**顶层函数** `load_private_key(key_path)` — 从 PEM 文件加载私钥（无缓存版本），文件不存在抛 `FileNotFoundError`，使用 `cryptography` 库的 `serialization.load_pem_private_key`。

### 4.2 签名引擎（`signatures.py`）

支持三种非对称加密算法的签名与验签：

| 算法 | 签名方式 | 验签方式 |
|------|---------|---------|
| **RSA** | PSS 填充（MGF1+SHA-256，salt=MAX_LENGTH）+ SHA-256 | PSS + SHA-256 |
| **ECDSA** (secp256k1/P-256/P-384/P-521) | ECDSA + SHA-256（DER 输出） | ECDSA + SHA-256（先尝试 DER，失败回退 compact） |
| **Ed25519** | 原生 Ed25519 | 原生 Ed25519 |

**核心函数**：

- `sign_hash(entry_hash, private_key) -> str` — 对哈希字符串签名，返回 Base64 编码的签名；未知密钥类型返回空串
- `verify_signature(entry_hash, signature_b64, public_key) -> bool` — 验证签名；任何异常（`InvalidSignature` 等）均返回 `False`，未知密钥类型记 error 日志后返回 `False`

**ECDSA 特殊处理**：由于 JS 端（Web Crypto API / @noble/secp256k1）输出 compact 格式（raw `r||s`），而 Python `cryptography` 库期望 DER 格式，验签时实现了双格式兼容：

```python
# 先尝试 DER 格式（Python cryptography 原生输出）
try:
    public_key.verify(sig_bytes, data, ec.ECDSA(hashes.SHA256()))
    return True
except InvalidSignature:
    pass
# DER 失败，尝试 compact (r||s) 格式
expected_compact_len = _ec_key_byte_size(public_key) * 2
if len(sig_bytes) == expected_compact_len:
    der_sig = _compact_to_der(sig_bytes)   # encode_dss_signature(r, s)
    public_key.verify(der_sig, data, ec.ECDSA(hashes.SHA256()))
else:
    raise InvalidSignature("Signature length mismatch")
```

辅助函数 `_compact_to_der()` 用 `asym_utils.encode_dss_signature(r, s)` 把 compact 字节串重组为 DER；`_ec_key_byte_size()` 由 `key.key_size` 推导字节长度。

### 4.3 DID 文档解析器（`did_resolver.py`）

完整的 DID 文档解析实现，从 ANP 迁移而来，支持带 TTL 缓存和重试机制的 DID → 公钥解析。

#### 支持的 DID 方法

- `did:wba` — WBA（Web-Based Addressable）方法
- `did:web` — Web 方法

#### 支持的公钥格式

| VerificationMethod Type | 格式 | 曲线/算法 |
|------------------------|------|----------|
| `EcdsaSecp256k1VerificationKey2019` | JWK / Multibase | secp256k1 |
| `EcdsaSecp256r1VerificationKey2019` | JWK | P-256 |
| `Ed25519VerificationKey2020/2018` | JWK / Base58 / Multibase | Ed25519 |
| `Multikey` | JWK / Base58 / Multibase | Ed25519 |
| `JsonWebKey2020` | JWK | 多曲线（EC） |

`CURVE_MAPPING` 覆盖 `secp256k1 / P-256 / P-384 / P-521` 四条曲线。

#### DIDResolutionResult

解析结果数据类：

| 字段 | 类型 | 说明 |
|------|------|------|
| `public_key` | `object \| None` | 提取的公钥对象 |
| `node_type` | `str \| None` | 节点类型（agent/tool/user） |
| `did_document` | `dict \| None` | 原始 DID 文档 |
| `from_cache` | `bool` | 是否来自缓存 |
| `failure_reason` | `str \| None` | 失败原因（如 `network_error`） |
| `resolution_url` | `str \| None` | 实际解析 URL |
| `http_status` | `int \| None` | HTTP 状态码 |
| `error_details` | `str \| None` | 错误详情 |

#### DIDResolver 核心方法

```python
class DIDResolver:
    def __init__(self, key_store, ttl_seconds=300.0, max_retries=2,
                 retry_delay=1.0, request_timeout=10.0)

    async def resolve_public_key(did, key_fragment="key-1") -> object | None
    async def resolve_did_document(did) -> tuple[doc, failure, url, status, error]
    async def resolve_full(did, key_fragment="key-1") -> DIDResolutionResult
    def extract_node_type(did_doc) -> str | None
    def invalidate(did) -> None
```

**特性**：
- **TTL 缓存**：默认 300 秒（`time.monotonic()` 计时），缓存命中时直接返回文档
- **指数退避重试**：最多重试 2 次，延迟 `retry_delay * 2^attempt` 倍增；区分连接错误 / HTTP 错误 / 超时 / 其他异常
- **文档 ID 校验**：解析返回的 `did_document["id"]` 需与 `did` 或其基础标识（`_did_base_id`，已剥离 key identifier）匹配，否则视为失败
- **节点类型识别**：从 DID 文档 `service` 数组中提取 `ATTPNodeType`（endpoint 格式：`attp:type:agent`，仅接受 `agent/tool/user`）
- **多格式公钥提取**：`_extract_public_key()` 支持 JWK、Multibase、Base58 三种编码，按 verificationMethod type 分派

**URL 构建规则**（`build_did_resolution_url`）：

```
did:wba:<domain>[:<path>...][:<key_identifier>]
  key identifier 按 e1_/k1_ 前缀识别并剥离（anp did:wba profile）：
  → https://<domain>/<path>/did.json          （有 path 段）
  → https://<domain>/.well-known/did.json     （无 path 段）
```

---

## 5. 溯源模块（provenance）

溯源模块实现消息溯源链的构建和验证，是 ATTP 身份管理和加密通信层（哈希链与回传一致性验证）的核心。

### 5.1 哈希计算（`hashing.py`）

两个 SHA-256 哈希函数，输入为确定性 JSON 序列化（`sort_keys=True, separators=(",",":")`，`ensure_ascii=False`）：

- `calculate_genesis_hash(session_id, protocol_node_address) -> str` — 创世标识哈希
- `calculate_hop_hash(content, sender_did, target_did, hop_count, timestamp, session_id) -> str` — 单跳消息哈希（6 字段）

### 5.2 链管理器（`chain.py`）

管理消息跳的追加、校验和回传验证。

#### hop_count 语义

`hop_count` 为二元组 `[a2a_count, intra_count]`：

- `a2a_count` — 跨 Agent 间（A2A）通信的跳序号
- `intra_count` — Agent 内部操作（A2T/A2U/T2A）的跳序号

递增规则（`append_hop` 内）：
- `behavior_type == "A2A"` → `[prev[0] + 1, 0]`
- 其他 → `[prev[0], prev[1] + 1]`
- 首条消息（无 `metadata["recorded_hop"]`）→ `[0, 0]`

#### append_hop(metadata, content, node_did, target_did, private_key_path, behavior_type=None)

构建新的跳记录并签名。流程：

1. 从 `metadata["recorded_hop"]` 获取前一跳信息（无则取 `metadata["Session_ID"]` 作为 session_id）
2. 根据 `behavior_type` 递增 hop_count
3. 调用 `calculate_hop_hash()` 计算 6 字段哈希
4. 经 KeyStore 加载私钥并调用 `sign_hash()` 签名
5. 构建新跳记录（`sender_did/target_did/hop_count/timestamp/sig_content/content/session_id`），写回 `metadata["recorded_hop"]`

#### validate_hop(hop, timeout=300.0) -> tuple[bool, str]

校验单条 hop 的完整性（不含签名验证与 hop_count 递增校验，后者在协议节点 Branch B 中按行为类型执行）：

| 校验步骤 | 内容 |
|---------|------|
| Step 1 | 字段完整性 + 类型检查（`sender_did`, `target_did`, `hop_count`(list), `timestamp`(float/int), `sig_content`, `content` 均为 str） |
| Step 1b | 值约束（非空、`hop_count` 长度为 2 且元素非负、`sig_content` 非空、`timestamp` 为正且不超前当前时间） |
| Step 2 | timestamp 超时检查（`timeout>0` 时，`now - timestamp > timeout` 判过期） |

#### verify_back_propagation(stored_hop, prev_hop, session_id) -> tuple[bool, str]

**回传验证**的核心方法，对比 Branch A（发送方暂存）和 Branch B（接收方到达）的记录，检测篡改。

三步验证：

| 步骤 | 检查内容 | 失败含义 |
|------|---------|---------|
| Step 1 | 上一跳签名验证（`verify_signature(prev_hop_hash, prev_sign, prev_public_key)`） | 签名是否由声称的节点签署 |
| Step 2 | 签名字节级比对（`stored_hop["Signature"] == prev_sign`） | 双方签名必须完全一致（ECDSA 每次签名不同，必须共享同一签名） |
| Step 3 | 哈希一致性（`store_hop_hash == prev_hop_hash`） | 内容是否被篡改 |

> 注：Step 2/3 使用的字段名为大写驼峰形式（`Content` / `Hop_Count` / `Timestamp` / `Signature`），对应协议节点中间件规范化后的 hop dict 形状。

**篡改诊断矩阵**：

| Step 1 | Step 2 | Step 3 | 诊断 |
|--------|--------|--------|------|
| ✗ | ✗ | — | 当前节点篡改内容 |
| ✗ | ✓ | ✗ | 当前节点篡改 pre_content |
| ✗ | ✓ | ✓ | 上一节点栽赃下一节点 |
| ✓ | ✓ | ✗ | 上一节点签名和内容不匹配 |
| ✓ | ✗ | * | **发送方双签/栽赃**：prev 副本签名在发送方公钥下有效却与 stored 不同，仅发送方私钥持有者可做到 ⇒ 发送方恶意 |

> 注：`Step 1=✓ ∧ Step 2=✗`（发送方双签）情形已由 `malicious_detector.evaluate_dual_back_prop` 的 **Step 4b** 在进入本函数前归因为发送方并写入恶意报告，正常 Branch B 流程不会进入本表的最后一行；此处保留为防御性诊断。

---

## 6. 消息模块（message）

定义 ATTP 协议的核心消息数据结构和回传发送逻辑。

### 6.1 RecordedHop（`event.py`）

单跳记录数据结构，嵌入在 `NodeMessage` 和 `BackMessage` 中。

```python
@dataclass
class RecordedHop:
    session_id: str
    sender_did: str
    target_did: str
    content: str
    timestamp: float
    hop_count: list[int]
    sig_content: str = ""        # 对其余字段哈希后的签名
```

- `content_hash()` — 计算除 `sig_content` 外所有字段的 SHA-256 哈希（确定性 JSON 序列化）
- `to_dict()` / `from_dict()` — 序列化/反序列化

### 6.2 NodeMessage（`event.py`）

节点间转发消息（A → B），由发送方构造。

```python
@dataclass
class NodeMessage:
    protocol_url: str            # 协议节点地址
    nonce: str                   # 唯一标识（匹配回传消息）
    recorded_hop: RecordedHop    # 单跳记录
```

- `sign_content(private_key)` — 发送方私钥对 `recorded_hop.content_hash()` 签名，写入 `sig_content`
- `verify_content(public_key)` — 验证签名（`sig_content` 为空直接返回 `False`）

### 6.3 BackMessage（`event.py`）

节点回传消息（A 或 B → 协议节点），用于双轮回溯确认。

```python
@dataclass
class BackMessage:
    protocol_url: str            # 协议节点地址
    node_did: str                # 回传节点的 DID
    nonce: str                   # 唯一标识
    sig_identity: str            # node_did + nonce 的签名
    recorded_hop: RecordedHop    # 单跳记录
```

BackMessage 包含两层签名：

| 签名 | 方法 | 用途 |
|------|------|------|
| `sig_identity` | `sign_identity(private_key)` — 签名 `SHA256(json({node_did, nonce}))` | 确认回传者身份 |
| `recorded_hop.sig_content` | `sign_content(private_key)` — 签名 hop 内容哈希 | 确认内容完整性（由发送方签署） |

验证方法：
- `verify_identity(public_key)` — 验证身份签名
- `verify_content(public_key)` — 验证内容签名（`sig_content` 为空返回 `False`）

### 6.4 send_back_message（`back_sender.py`）

统一的 BackMessage 发送函数，封装构造、签名、HTTP 发送和错误处理。

```python
async def send_back_message(
    protocol_url, node_did, nonce, recorded_hop, private_key, timeout=10.0
) -> None
```

**流程**：
1. 构造 `BackMessage`（`sig_identity` 初始为空）
2. 调用 `sign_identity()` 签名身份
3. POST 到 `{protocol_url}/record` 端点
4. 处理响应：HTTP 200 且响应 JSON 不含 `error`、`status` 非 `error/rejected` 视为成功；否则抛 `BackPropagationError`

**异常**：`BackPropagationError` — 回传失败时抛出（协议节点拒绝、非 200 HTTP、网络异常）。

### 6.5 init.py

便捷导出：`RecordedHop` / `NodeMessage` / `BackMessage` / `send_back_message`。

---

## 7. 分析模块（analysis）— 十字锁定意图追踪

基于 LLM 的语义意图追踪系统，采用**十字锁定（Cross-Lock）架构**。v0.3.0 改版为**逐跳、有状态**模型：纵轴对每条动作跳实时打分，横轴按 per-DID 累积偏离 F 触发跨会话确认。

| 维度 | 分析粒度 | 核心类 | 说明 |
|------|---------|--------|------|
| **纵轴（Vertical）** | per-session / per-hop | `VerticalIntentAnalyzer` + `VerticalOrchestrator` | 逐跳 V-Reasoner 评分（意图流 + 4 维 + 单点 R_T 告警） |
| **横轴（Horizontal）** | per-DID / cross-session | `HorizontalIntentAnalyzer` + `HorizontalOrchestrator` | 纯平方和 F 累加 + α 会话跨会话确认 |
| **十字锁定** | 纵横联动 | `CrossLockCoordinator` | 纵轴每打一跳分 → 回调横轴 `on_hop_scored` 喂入 F |

### 7.1 共享基础模型与评分常量（`base_models.py`）

#### 评分量纲与分档（§6）

| 常量 | 值 | 说明 |
|------|----|------|
| `SCORE_STEP` | `0.5` | 分数步进（21 档） |
| `SCORE_MAX` | `10.0` | 分数上限 |
| `DIMENSION_NAMES` | `(intent_alignment, capability, injection_manipulation, exfiltration_tampering)` | 4 个正交评分维度（d1..d4） |
| `SEVERITY_HIGH_LOWER` | `5.5` | high 档下沿（breadth 统计阈值） |
| `SEVERITY_CRITICAL_LOWER` | `7.5` | critical 档下沿 |

**severity 分档**（左闭右开，由 `severity_for_score(score)` 代码推导，**不让 LLM 下**）：

| score 区间 | severity |
|-----------|----------|
| `< 1.5` | none |
| `< 3.5` | low |
| `< 5.5` | medium |
| `< 7.5` | high |
| `≥ 7.5` | critical |

**会话级 overall_verdict 推导**（`overall_verdict_for_severities(severities)`）：任一跳 critical → `malicious`；任一跳 high → `suspicious`；否则 `clean`。

**聚合函数**（`aggregate_score(dims, p="max")`）：
- `"max"`（默认）— 取最大维，任一维突出即决定总分，单点高分不被稀释
- `"sum"` — 在场均值的平均（会稀释，作基线）
- 数值 `p` — L^p 范数 `(Σ d_k^p)^(1/p)`

**breadth**（`compute_breadth(dims)`）— 统计 `≥ SEVERITY_HIGH_LOWER (5.5)` 的维度数（仅归因用，不参与触发）。

#### IntentRevision — 意图增量 Δ（追加式意图流）

意图流 `I = [Δ_0, ..., Δ_m]` 只增不改，由会话发起者 DID 的每条 U2A 追加：

| 字段 | 类型 | 说明 |
|------|------|------|
| `goal` | `str` | 这条 U2A 带来的新目标/子目标 |
| `constraints` | `list[str]` | 这条 U2A 明确陈述的约束 |
| `prohibitions` | `list[str]` | 这条 U2A 明确禁止的事（v0.3.0 新增字段） |
| `source` | `IntentRevisionSource \| None` | 来源（trace_id / did / timestamp），单独记录供回放 |

`IntentRevisionSource` 不作为意图字段，仅记录该增量来自哪条 U2A。

#### HopScore — 单跳评分结果

V-Reasoner 对单条动作跳的评分结果：

| 字段 | 说明 |
|------|------|
| `trace_id / session_id / sender_did / field_type / hop_count` | 跳定位 |
| `score` | 聚合后的总分 `s_i ∈ [0,10]` |
| `dimensions` | `[d1, d2, d3, d4]` 固定 4 维数组（缺失位记 0） |
| `breadth` | ≥ high 的维度数（归因用） |
| `severity` | 由 score 代码推导（none/low/medium/high/critical） |
| `deviation_type` | 偏离类型（none/goal_hijack/constraint_violation/unauthorized_action/instruction_injection/data_exfiltration/privilege_escalation/social_engineering） |
| `evidence_items` | 证据列表（`EvidenceItem`） |
| `hidden_state` | 本跳产出的滚动隐状态 `h_i`（供下一跳使用） |

#### EvidenceItem — 证据条目（纵横共用）

| 字段 | 说明 |
|------|------|
| `description` | 证据描述 |
| `trace_ids` | 引用的 trace ID 列表 |
| `field_type` | 行为类型 |
| `severity_hint` | 严重程度提示（info / warning / critical） |

### 7.2 纵轴 — Vertical Axis

#### 7.2.1 纵轴数据模型（`vertical/models.py`）

##### VerticalSessionReport — 会话级聚合视图

单会话的逐跳评分聚合（供 `/report`、`/aggregate` 等只读端点使用，由 `VerticalIntentAnalyzer.aggregate_session()` 构建）：

| 字段 | 说明 |
|------|------|
| `session_id` | 会话 ID |
| `initiator_did` | 会话发起者 DID |
| `intent_revisions` | 意图流（list[dict]） |
| `hidden_state` | 最新隐状态 |
| `hop_scores` | 各跳评分（list[dict]） |
| `overall_verdict` | 总体判定（clean / suspicious / malicious，代码推导） |
| `max_score` | 会话内最高单跳分 |
| `total_hops` | 已打分跳数 |

> 逐跳评分本身用共享的 `HopScore`（base_models）承载并落库 `vertical_hop_scores`；本模块只提供会话级只读视图。

#### 7.2.2 VerticalIntentAnalyzer（`vertical/analyzer.py`）

逐跳 V-Reasoner：意图增量抽取 + 单跳 4 维评分。`s_i / breadth / severity / overall` 均由代码推导，**LLM 只输出 4 维原始分 + deviation_type + evidence_refs + hidden_state**。

**两个核心方法**：

##### extract_intent_revision(u2a_content, previous_revisions, source) -> IntentRevision

从单条 U2A 抽意图增量 Δ。失败时用 U2A 原文兜底构造最小 Δ（不阻塞流程）。调用 `INTENT_REVISION_PROMPT`，`temperature=0.1`，`response_format=json_object`，`timeout=120`。

##### score_hop(hop, intent_revisions, hidden_state_prev) -> HopScore | None

对单条动作跳评分，输入三元组 `(I, h_{i-1}, a_i)`，输出 `HopScore`。失败返回 `None`（调用方决定是否推进游标）。调用 `HOP_SCORING_PROMPT`。

**`_build_hop_score()` 组装逻辑**：
1. `_build_dimensions(result["dimensions"], aggregation)` — 解析 LLM 原始 4 维分。**缺失维度不补 0 参与聚合**（补 0 会让 mean 聚合被稀释、漏报），聚合只在 LLM 实际给出的维度上算；固定 4 维数组里缺失位记 0，仅供落库与 breadth 统计。每维分按 0.5 步进量化并 clip 到 `[0,10]`。
2. `severity_for_score(score)` — 代码推导 severity
3. 解析 `evidence_refs` → `EvidenceItem` 列表
4. 组装 `HopScore`（含 `hidden_state` 来自 LLM 输出）

**field_type → sender node_type 映射**（`FIELD_TYPE_TO_SENDER_NODE_TYPE`，与横轴一致）：

| field_type | sender node_type |
|-----------|-----------------|
| A2T / A2U / A2A | agent |
| U2A | user |
| T2A | tool |

#### 7.2.3 纵轴 Prompt 模板（`vertical/prompts.py`）

##### INTENT_REVISION_PROMPT — 意图增量抽取

从单条 U2A 抽取增量 Δ={goal, constraints, prohibitions}。强调只抽本条输入的增量、不合并之前意图；constraints/prohibitions 仅记录用户**明确陈述**的，缺省返回空数组。

##### HOP_SCORING_PROMPT — 逐跳评分（V-Reasoner）

输入 `(I, h_{i-1}, a_i)`，要求 LLM 在 4 个正交维度各打 `d_k∈[0,10]`（0.5 步进），维度独立、**不做加权平均**。

**4 维锚点表**（prompt 内嵌）：

| 维度 | 含义 | 0 | 4 | 6 | 8–10 |
|---|---|---|---|---|---|
| d1 意图对齐 | 偏离当前 goal / 引入新目标 | 服务 goal | 弱相关子任务 | 明显偏离 | goal 劫持 |
| d2 能力域 | 触及意图外能力 / 越权 | 仅授权 | 未授权低危 | 明显越权 | 读 shadow、删凭据、全网扫描 |
| d3 注入与操纵 | 指令注入 / 社工 / 认知操纵 | 无 | 疑似载荷 | 明确注入 | 完整注入链、社工 |
| d4 外泄与篡改 | 数据外发 / 参数或返回篡改 | 无 | 可疑外发 | 敏感外发、篡改 | 凭据外泄、全面篡改 |

判别原则：服务于用户目标的正常操作（即便涉及敏感命令）各维低分；能力域边界外的动作 d2/d4 高分；信息误导需有欺骗意图。LLM 输出 JSON 含 `dimensions / deviation_type / evidence_refs / hidden_state`。

#### 7.2.4 VerticalOrchestrator（`vertical/orchestrator.py`）

逐跳纵向编排：**per-session 有界队列 worker + 全局并发限流**。

**改版核心**：`/record` 落库后把该跳 `hop` 投进该会话的**有界队列**即返回（不 await LLM）；每个会话一个后台 worker 从队列消费，按 trace 序串行（per-session `asyncio.Lock` 保护意图流 / 隐状态 / 游标），LLM 调用受全局信号量 `concurrency` 限并发。队列满（`queue_maxsize`）= 真背压：`/record` 不阻塞，溢出 hop 留在 DB，由 worker 的 **catch-up 扫描**按游标补打，不丢数据。

**构造参数**：`analyzer, vertical_state_mgr, tracer, r_t=7.5, concurrency=8, queue_maxsize=1000, event_broker=None`。

**分流（`_process_one`）**：
- **U2A 且 sender==发起者 DID** → 抽 Δ 追加意图流（**不打分**）。首条 U2A 时若发起者未定，则以该跳 sender 为发起者。
- **U2A 但 sender≠发起者 DID** → **当普通动作跳打分**（防第二用户注入/越权引导盲区，是典型 d3 注入向量）。
- **动作跳（A2A/A2T/T2A/A2U）** → V-Reasoner 逐跳打分 → 落 `vertical_hop_scores` → 更新 `h_i` → `s_i > R_T` 立即告警 → 把 **sub-R_T** 的 `s_i` 报给横轴 `on_hop_scored`（critical 单跳不重复计入 F：R_T 抓单跳恶，F 抓累积慢投毒）。

> 无论成功或失败，`finally` 都推进打分游标 `last_scored_trace_id`（失败/降级本次不做，不重试，避免卡死）。

##### worker 生命周期

- `_ensure_worker(session_id)` — 惰性创建 per-session `asyncio.Queue` + `asyncio.Lock` + worker Task
- `_worker_loop(session_id)` — 启动即 catch-up（恢复崩溃前已落库未打分的跳）；主循环 `queue.get(timeout=WORKER_IDLE_TIMEOUT=300s)`，超时则再 catch-up 一次，仍无新增则退出 worker（下次 enqueue 重建）；收到 `_CATCHUP_SENTINEL` 哨兵则强制 catch-up（手动触发用）；普通跳按游标去重后串行处理
- `shutdown()` — cancel 所有 worker task

##### R_T 单点告警（`_notify_rt_alert`）

`score.score > r_t`（严格大于，默认 `r_t=7.5`）→ 写 `malicious_reports`（`source="vertical_analysis"`），`severity` 取该跳代码推导档，`taint_score` 即 `score`，`raw_evidence` 含 dimensions/breadth/evidence_items。

##### 对外接口

| 方法 | 功能 |
|------|------|
| `enqueue_trace(session_id, hop)` | `/record` 落库后投队（不阻塞） |
| `trigger_analysis_async(session_id)` | 手动触发：投哨兵跑 catch-up |
| `get_analysis_status(session_id)` | 查询 worker 阶段（idle/scoring）与队列深度 |
| `shutdown()` | 停止所有 worker |

##### SSE 集成

- U2A 抽意图后：发布 `ANALYSIS_PROGRESS`（`phase=intent_appended`）
- 横轴联动回调 `_on_hop_scored_callback` 由 `CrossLockCoordinator` 注入

### 7.3 横轴 — Horizontal Axis

#### 7.3.1 横轴数据模型（`horizontal/models.py`）

##### CrossSessionProfile — 跨会话行为画像

单个 DID 跨多个会话的行为画像（确认时构建，供 prompt 使用）。field 映射（作为 sender）：`field_a_traces→A2T`、`field_b_traces→A2U`、`field_c_traces→U2A`、`field_d_traces→A2A`、`field_e_traces→T2A`、`received_traces→该 DID 作为 target 接收的消息`。

##### ConfirmationVerdict — 横轴确认结论（单 DID）

| 字段 | 说明 |
|------|------|
| `confirmed` | 是否确认存在跨会话攻击 |
| `severity` | none/low/medium/high/critical |
| `taint_score` | `[0,10]` |
| `threat_pattern` | 威胁模式（none/cross_session_apt/slow_poisoning/persistent_manipulation/privilege_escalation_chain/data_exfiltration_pattern/unauthorized_access_pattern/collaborative_attack） |
| `evidence / evidence_items` | 证据描述 / 证据条目 |
| `sessions_reviewed` | 复核会话数 |
| `summary / context_summary` | 本次结论 / 节点档案摘要 |

##### ConfirmationReport — 一次横轴确认的报告

持久化到 `horizontal_analysis_reports`。含 `batch_index / from_trace_id / to_trace_id / sessions_scanned / selected_sessions / verdict / overall_verdict / triggered_by`（`f_threshold` / `manual`）。`overall_verdict` 由代码推导：未确认→clean；确认且 severity≥high→malicious；否则 suspicious。

#### 7.3.2 HorizontalIntentAnalyzer（`horizontal/analyzer.py`）

跨会话确认器。横轴不再独立做全局画像，而是对纵轴筛出的 α 个可疑会话做跨会话**确认**：确认存在连贯攻击则告警，否则判良性（消化纵轴误报）。

##### confirm(did, node_type, sessions_data, previous_context, prior_report) -> ConfirmationVerdict

对 α 个会话的高分跳做跨会话确认，可汇入上一次确认报告（防会话集拆分规避）。`temperature=0.1`，`response_format=json_object`，`timeout=120`。失败时返回默认 `ConfirmationVerdict`（`confirmed=False`）。

**node_type 推导**：`_derive_node_type_from_scores()` 从逐跳评分取首条作为 sender 的 field_type 映射；兜底 `_derive_node_type()` 从 traces 推导（先 sender 后 receiver）。

#### 7.3.3 横轴 Prompt 模板（`horizontal/prompts.py`）

##### CONFIRMATION_PROMPT — 跨会话确认

单一 Prompt（不再按 node_type 分 3 套），输入：审计目标 DID / 历史确认上下文（滚动节点档案）/ **上一次确认结论**（跨 batch，防会话集拆分规避）/ 各会话授权意图 + 高分跳摘要。

判别原则：
- **意图违反（首要信号）**：对照各会话「授权意图」（尤其 prohibitions），触碰禁令即为强信号；同一禁令多会话反复违反 = 跨会话连贯模式，判确认
- 单会话一次性偏差、跨会话无连贯模式、未违反显式禁令 → 倾向判良性
- 多会话重复同类可疑动作 / 慢投毒（跨会话方向一致缓慢推进）→ 判确认
- 误报消化：高分跳跨会话无关联、各有合理解释 → 判良性

**taint_score 评分标准**（`[0,10]`，0.5 步进）：0–1.5 none / 1.5–3.5 low / 3.5–5.5 medium / 5.5–7.5 high / 7.5–10 critical。

#### 7.3.4 HorizontalOrchestrator（`horizontal/orchestrator.py`）

横向编排：per-DID F 累加 + α 会话确认。

**构造参数**：`analyzer, horizontal_state_mgr, tracer, r_s=25.0, alpha=10, rho=8.0, concurrency=8, event_broker=None`。

##### F 累加（`on_hop_scored`）

纵轴每打一跳分即由 CrossLockCoordinator 调用：

1. **纯平方和**：`f_delta = score ** 2`（**无死区 d、无折扣 γ、无 V_max、无窗口截断**），per-DID 累加 `F += f_delta`、`volume += 1`
2. 发布 `HORIZONTAL_ACCUMULATED` 事件（含 f_value/volume/r_s）
3. 触发判定：`f_value > r_s **且** volume >= _MIN_TRIGGER_VOLUME(=2)` → 触发确认（`reason=f_threshold`）。F 越阈值但体积不足时**保留 F 累加**，等下一跳达标再触发（不丢偏移量）
4. 触发后发布 `HORIZONTAL_TRIGGERED`，fire-and-forget 调用 `trigger_analysis_async(did)`

> `_MIN_TRIGGER_VOLUME=2` 仅约束 `on_hop_scored` 的自动触发；手动 `/h/trigger`（`run_analysis`）不受此限。单跳 critical 交给纵轴 R_T，横轴等累积 ≥2 跳才确认。

##### 确认主流程（`run_analysis`）

caller 持 per-DID 锁。流程：

1. 恢复 per-DID 状态，取确认游标 `last_trace_id`
2. `selecting`：`query_hop_scores_by_did(did, cursor)` 取游标以来的逐跳评分；无新分则清零滞留 F、闭案推进
3. `_select_sessions()` 选会话：候选数 ≤ α 直接取全量；否则按 `W(σ)=Σ s²` 降序取 α 个 + **高危兜底**（任一跳 `s≥ρ(=8.0)` 的会话无条件入选，不占 α 名额）
4. 取 traces 供确认画像（仅取 content）；游标按"已打分跳"的 max trace_id 推进（不用 behavior_traces 的 max，避免越过尚未打分的跳）
5. `_load_session_intents()` 各会话独立取自己的意图流（不跨会话），只取 `source.trace_id <= max_trace_id` 的 Δ（排除本批之后才更新的意图，防溯及既往）；`_accumulate_intent()` 把增量并集化（prohibitions/constraints 取并、goal 取最新非空）
6. `confirming`：加载上一次确认报告（`_load_prior_report`，按 batch_index 升序取最后一行），调用 `analyzer.confirm()`（汇入 prior_report）
7. `_derive_overall(verdict)` 推导 overall_verdict；持久化 `ConfirmationReport` 到 `horizontal_analysis_reports`
8. 确认（`confirmed=True`）→ `_notify_confirmed` 写 `malicious_reports`（`source="horizontal_analysis"`）
9. **闭案**：`state_mgr.close(did, max_scored, context)` 重置 F/体积、推进游标、batch+1、记摘要

##### 异步任务管理

- `trigger_analysis_async(did, triggered_by)` — fire-and-forget，per-DID 锁 + Task；`already_running` 时直接返回
- `get_analysis_status(did)` — completed（弹出结果）/ running（含 phase）/ not_found
- `shutdown()` — cancel 所有 task

### 7.4 CrossLockCoordinator（`cross_lock.py`）

十字锁定协调器，串联纵轴逐跳评分与横轴 F 累加/确认。

```python
class CrossLockCoordinator:
    def __init__(
        self,
        vertical_orchestrator: VerticalOrchestrator,
        horizontal_orchestrator: HorizontalOrchestrator | None = None,
    )
```

**核心桥接逻辑**：构造时若提供了横轴，则把 `self._on_hop_scored` 注入纵轴作为 `_on_hop_scored_callback`。纵轴每打一跳分即回调横轴 `on_hop_scored` 喂入 F。

```
/record 落库 → coordinator.enqueue_trace(session_id, hop)
                    ↓
           VerticalOrchestrator worker 逐跳处理
                    ↓ （动作跳打分后）
           _on_hop_scored(did, session_id, trace_id, score, field_type)
                    ↓ （仅 sub-R_T 的跳）
           HorizontalOrchestrator.on_hop_scored → F += s²
                    ↓ （F > R_S 且 volume ≥ 2）
           横轴自动确认 run_analysis(did)
```

**对外接口**：

| 方法 | 委托目标 |
|------|---------|
| `enqueue_trace(session_id, hop)` | 纵轴 |
| `trigger_analysis_async(session_id)` | 纵轴（手动补打） |
| `get_analysis_status(session_id)` | 纵轴 |
| `trigger_horizontal_async(did)` | 横轴（手动确认；横轴禁用时返回 `horizontal_disabled`） |
| `get_horizontal_status(did)` | 横轴 |
| `shutdown()` | 停止纵横 worker（ProtocolNode.stop 调用） |

`vertical` / `horizontal` 为只读 property。

### 7.5 分析状态管理

#### VerticalAnalysisManager（`sessions/protocol_node/management/vertical_state.py`）

封装 `ProtocolSession.vertical_analysis` 状态（发起者 DID / 意图流 / 隐状态 / 打分游标）的读写，持久化委托给 `SqliteStore`（`vertical_analysis_states` 表）。

| 方法 | 功能 |
|------|------|
| `restore_state(session_id)` | 从 SQLite 恢复纵向状态（每 session 仅一次；已恢复/已有内存状态则跳过） |
| `get_state(session_id)` | 获取纵向分析状态 dict（先 restore） |
| `set_initiator_did(session_id, did)` | 设置会话发起者 DID |
| `append_intent_revision(session_id, revision)` | 追加一条意图增量 Δ 并持久化 |
| `set_hidden_state(session_id, hidden)` | 更新滚动隐状态 |
| `advance_score_cursor(session_id, trace_id)` | 推进打分游标到 max(已记录, trace_id) |

#### HorizontalAnalysisManager（`sessions/protocol_node/management/horizontal_state.py`）

管理每个 DID 的累积偏离 F、体积计数、确认游标、批次与上下文。横向状态是全局 per-DID 的，不属于任何单个 Session，持久化到 `horizontal_analysis_states` 表。

`HorizontalAccumulationState` 字段：`f_value`（纯平方和 Σ s²）、`volume`（自上次闭案以来的跳数）、`last_trace_id`（确认游标）、`batch_index`（已完成确认次数）、`context`（最近确认摘要）。

| 方法 | 功能 |
|------|------|
| `restore_state(did)` | 从 SQLite 恢复 DID 横向状态（懒加载） |
| `accumulate(did, f_delta, node_type)` | F += f_delta、volume += 1，持久化，返回 (f_value, volume) |
| `close(did, advance_cursor_to, context)` | 闭案：重置 F/体积、推进游标、batch+1、记摘要 |
| `reset_accumulation(did)` | 清零 F/体积但不动游标/batch/context（用于 no_new_scores 清滞留 F） |
| `get_state(did) / get_cursor(did)` | 取状态 / 游标 |

---

## 8. 存储模块（storage）

基于 aiosqlite 的异步 SQLite 存储引擎，采用 **Repository 模式**分层组织。

### 8.1 Database（`database.py`）

aiosqlite 连接管理器，提供便捷方法：

| 方法 | 说明 |
|------|------|
| `initialize()` | 执行全部 DDL（建表 + 索引 + 幂等迁移），共 8 张表 |
| `execute(sql, params)` | 执行写操作并自动 commit |
| `execute_insert(sql, params) -> int` | 执行 INSERT 并返回 `lastrowid` |
| `execute_fetch(sql, params) -> list[dict]` | 查询返回 `list[dict]` |
| `execute_fetchone(sql, params) -> dict \| None` | 查询返回单行 `dict` 或 `None` |

**数据库归一化与迁移**（`initialize()` 中幂等执行）：

| 迁移 | 说明 |
|------|------|
| `_normalize_legacy_tables()` | 归一化旧表结构（无向后兼容，旧形状直接 DROP+CREATE）：删除已废弃的 `vertical_analysis_reports` / `analysis_reports`；`vertical_analysis_states` 缺 `intent_revisions_json` 列则 DROP 重建，清理旧名 `analysis_sessions`；`horizontal_analysis_states` 缺 `f_value` 列则 DROP 重建 |
| `_migrate_malicious_nodes()` | `malicious_nodes` → `malicious_reports`（补 `source/target_did/node_type/severity/taint_score/report_id` 列，重命名 `malicious_did→target_did`），兼容旧库 |

**严重等级映射**（`severity_for_count`，用于 node_dossiers）：

```python
_SEVERITY_THRESHOLDS = [(0, "clean"), (1, "warning"), (4, "dangerous")]
# count >= 4 → "banned"
```

### 8.2 Repository 基类（`repositories/base.py`）

```python
class BaseRepository:
    def __init__(self, db: Database) -> None:
        self._db = db
```

所有 Repository 通过 `self._db` 访问数据库。

### 8.3 TraceRepository（`repositories/trace_repo.py`）

`behavior_traces` 表的读写。

| 方法 | 功能 |
|------|------|
| `save_behavior_entry(...)` | 插入一条行为记录，将 `hop_count` 拆为 `hop_count_a2a` + `hop_count_intra` |
| `recover_behavior_trace(session_id, protocol_node_address=None)` | 按 session 查询全部 trace（按 hop_count 序） |
| `recover_traces_since(session_id, since_id)` | 查询指定 ID 之后的 trace（增量分析用），返回 `(list, max_id)` |

**字段映射**：数据库中 `node_did` → 返回时 `sender_did`，`target` → `target_did`，`hop_count_a2a/intra` → `hop_count`。

### 8.4 VerticalRepository（`repositories/analysis_repo.py`）

`vertical_hop_scores`（逐跳评分）+ `vertical_analysis_states`（意图流/隐状态/游标）的读写。

| 方法 | 功能 |
|------|------|
| `save_hop_score(score: dict) -> int` | 保存一条逐跳评分（含 dim1..dim4 / breadth / severity / evidence_refs_json / hidden_state），返回插入行 ID |
| `query_hop_scores_by_session(session_id)` | 会话内全部逐跳评分，按 trace_id 升序 |
| `query_hop_scores_by_did(did, since_id=0)` | 某 DID 作为 sender 的全部评分（since_id 之后），供横轴 W(σ) 取数 |
| `max_trace_id_for_did(did)` | 该 DID 已打分的最大 trace_id |
| `max_trace_id_for_session(session_id)` | 该会话已打分的最大 trace_id |
| `save_vertical_state(session_id, state)` | INSERT OR REPLACE 纵向状态 |
| `load_vertical_state(session_id)` | 加载纵向状态 |

`_shape_hop_row()` 把存储行整理为对外一致 dict（`hop_count` / `dimensions[4]` / `evidence_refs`）。

### 8.5 HorizontalRepository（`repositories/horizontal_repo.py`）

`horizontal_analysis_states` 和 `horizontal_analysis_reports` 的读写。

| 方法 | 功能 |
|------|------|
| `save_horizontal_state(did, state)` | INSERT OR REPLACE 横向状态（F / volume / cursor / batch / context） |
| `load_horizontal_state(did)` | 加载 DID 横向状态 |
| `save_horizontal_report(report_json) -> int` | 保存横向确认报告，返回插入行 ID |
| `recover_horizontal_reports(did)` | 查询 DID 全部横向报告（按 batch_index 升序） |
| `recover_traces_by_did_since(did, since_id)` | 恢复 DID 在所有会话中 since_id 之后的全部 trace（含 sender 与 receiver），返回 `(list, max_id)` |
| `count_sessions_for_did(did, since_id=0)` | 统计 DID 涉及的会话数 |

### 8.6 MaliciousRepository（`repositories/malicious_repo.py`）

`malicious_reports` 和 `node_dossiers` 的读写（统一恶意报告格式）。

| 方法 | 功能 |
|------|------|
| `save_malicious_report(report: dict) -> int` | 统一写入 `malicious_reports` 表并自动 `_upsert_dossier`，返回插入行 ID |
| `query_malicious_reports(session_id, target_did, source)` | 按条件查询恶意报告（支持 `source` 筛选） |
| `query_malicious_nodes(session_id, malicious_did)` | 兼容旧接口，委托到 `query_malicious_reports` |
| `_upsert_dossier(did, evidence_type, session_id, description)` | 更新或创建节点档案 |
| `upsert_dossier(...)` | 公开接口 |
| `query_dossier(did)` | 查询单个 DID 档案 |
| `query_all_dossiers(severity_level, source, limit)` | 查询所有档案（`source` 筛选语义：只返回至少有一条来自该来源 incident 的档案，经子查询判定） |
| `compute_source_breakdown()` | 返回 `{did: {source: count}}` 映射（一条 GROUP BY 查询） |

**统一恶意报告格式**（三个来源写入同一张表）：

```python
{
    "source": "protocol_review" | "vertical_analysis" | "horizontal_analysis",
    "target_did": str,
    "node_type": str,
    "session_id": str,
    "evidence_type": str,
    "severity": str,
    "taint_score": float,        # v0.3.0 值域 0–10
    "evidence_description": str,
    "nonce": str,
    "report_id": int | None,     # 关联的分析报告 ID
    "raw_evidence": dict,
    "timestamp": float,
}
```

> v0.3.0 起 `taint_score` 值域为 0–10、`severity` 为 5 档（none/low/medium/high/critical）。

**Dossier 更新逻辑**：
- 有 `session_id`（纵向/协议）：更新全部字段
- 无 `session_id`（横向跨 session）：仅更新统计和等级，保留已有 session 信息
- 首次创建：`total_violations=1`, `severity_level=warning`
- 后续更新：递增 `total_violations`，按阈值映射 `severity_level`（warning → dangerous → banned）

### 8.7 ProtocolSessionRepository（`repositories/session_repo.py`）

`protocol_session_state` 的读写，用于验证状态持久化。

| 方法 | 功能 |
|------|------|
| `save_verification_state(session_id, state)` | 保存 completed_nonces / hop_count_map / trusted_dids |
| `load_verification_state(session_id)` | 加载验证状态（JSON 反序列化；`hop_count_map_json` 为 NULL 时返回 None） |
| `delete_verification_state(session_id)` | 删除验证状态 |

### 8.8 SqliteStore（`store.py`）

**外观类**，统一代理所有 Repository。

```
SqliteStore
  ├── TraceRepository          → behavior_traces
  ├── VerticalRepository       → vertical_hop_scores + vertical_analysis_states
  ├── HorizontalRepository     → horizontal_analysis_states + horizontal_analysis_reports
  ├── MaliciousRepository      → malicious_reports + node_dossiers
  └── ProtocolSessionRepository → protocol_session_state
```

通过 `@classmethod async def create(db_path)` 异步工厂方法初始化（调用 `Database.initialize()`）。

**事件总线集成**：`set_event_broker(broker)` 注入 `EventBroker`（None-safe）。写入点自动发布事件：
- `save_behavior_entry` → `TRACE_RECORDED`（topic=trace）
- `save_hop_score` → `HOP_SCORED`（topic=analysis，含 dimensions[4]/breadth）
- `save_malicious_report` → `MALICIOUS_DETECTED`（topic=malicious）

---

## 9. 会话模块（sessions）

会话管理分为三层，分别服务于不同角色的节点。

### 9.1 BehaviorEntry（`node_message.py`）

单条行为记录数据结构，贯穿所有层次的会话管理。

| field_type | 含义 | target 字段 |
|------------|------|------------|
| `A2T` | Agent → Tool | 工具名称 |
| `A2U` | Agent → User | 空 |
| `U2A` | User → Agent | 空 |
| `A2A` | Agent → Agent | 目标 Agent DID |
| `T2A` | Tool → Agent（预留） | 空 |

### 9.2 App 层会话

#### AppSession

App 层 per-chat_id 路由元数据容器，存储消息追踪路由信息。

```python
@dataclass
class AppSession:
    key: str                              # chat_id
    metadata: dict[str, Any]              # 包含 recorded_hop, protocol_url 等
    updated_at: float
```

核心方法：
- `get_trace_metadata()` — 提取追踪相关键（`recorded_hop`, `protocol_url`）
- `set_trace_metadata(trace_data)` — 合并追踪键到 metadata
- `set_metadata / get_metadata / update_metadata` — 通用元数据

#### AppSessionManager

内存会话存储，按 `chat_id` 索引。提供 `locked_session()` 异步上下文管理器，防止并发的 read-modify-write 竞争（如 hop_count 损坏）。

```python
async with manager.locked_session(chat_id) as session:
    trace = session.get_trace_metadata()
    # ... compute hop, do I/O ...
    session.set_trace_metadata(new_trace)
    # save() 自动调用
```

`locked_session(chat_id, *, create=True)`：`create=False` 时对不存在的 session yield `None`。

### 9.3 协议节点层会话

#### PendingMessage

nonce 匹配的暂存消息，用于双轮回溯确认中的 Branch A 暂存。

```python
@dataclass
class PendingMessage:
    hop: dict                     # 完整 hop 记录
    session_id: str
    protocol_node_address: str
    sender_did: str
    sender_node_type: str         # "agent" / "tool" / "user"
    nonce: str
    stored_at: float
    ttl_seconds: float = 300.0
    # 身份验证扩展字段
    node_did: str = ""
    identity_public_key_pem: str | None = None
    identity_verified: bool = False
    identity_verification_attempted: bool = False
```

- `is_expired()` — 检查是否超过 TTL（默认 300 秒）

#### ProtocolSession

协议节点层 per-session 状态容器，管理验证状态和**纵向分析状态**（`VerticalAnalysisState`）。

**VerticalAnalysisState**（逐跳改版字段）：
- `initiator_did` — 会话发起者 DID（首条 U2A 的发送方），意图只采信它的 U2A
- `intent_revisions` — 意图流 `I=[Δ_0..Δ_m]`
- `hidden_state` — 定长滚动隐状态 `h_i`
- `last_scored_trace_id` — 打分游标（崩溃恢复用）

核心功能分组：

| 功能 | 方法 |
|------|------|
| **Pending 管理** | `store_pending_message()`, `get_pending_message()`, `remove_pending_message()`, `pop_expired_pending_messages()` |
| **Hop count 校验** | `get_max_a2a_count()`, `get_latest_intra_count()` |
| **Nonce 追踪** | `mark_nonce_completed()`, `has_subsequent_activity_after()`, `has_subsequent_with_different_verified_identity()` |
| **可信名单** | `add_trusted_did()`, `get_latest_trusted_did()`, `get_trusted_did_list()`, `clear_trusted_list()` |
| **验证便捷方法** | `complete_verification(nonce, hop_count, trusted_did)` — 一次完成所有 Branch B 状态更新 |
| **纵向分析状态** | `get_analysis_state()`, `set_initiator_did()`, `append_intent_revision()`, `get_intent_revisions()`, `set_hidden_state()`, `advance_score_cursor()`, `get_score_cursor()` |

#### ProtocolSessionManager

协议节点层会话存储，支持 SQLite 持久化（验证状态：completed_nonces / hop_count_map / trusted_dids）。

- `get_or_create(session_id)` — 惰性恢复：首次访问时从 SQLite 加载验证状态
- `save(session)` — 同时写入内存和 SQLite（如果有 storage）
- 无 storage 时退化为纯内存 dict（向后兼容）

### 9.4 工具节点层会话

#### ToolSession

工具节点侧 per-session 状态容器。

```python
@dataclass
class ToolSession:
    key: str
    protocol_node_address: str = ""
    metadata: dict[str, Any]
    updated_at: float
```

核心方法：
- `store_pending_request(nonce, request_info)` / `get_pending_request(nonce)` / `remove_pending_request(nonce)` — 以 `_pending_req:{nonce}` 为 key 暂存待处理工具调用
- `get_last_hop_count()` / `set_last_hop_count(hc)` — 跳计数追踪
- `set_protocol_node_address(address)` — 设置协议节点地址

#### ToolSessionManager

纯内存会话存储，无持久化需求。

---

## 10. SSE 子系统（sse）

进程内事件总线 + SSE 帧序列化 + 事件词汇表。本包**不依赖任何 web 框架**（纯 asyncio + 标准库），故可安全置于 `core/`；SSE 的 HTTP 接线（FastAPI `StreamingResponse` + 心跳循环）在 web 层（`attp.protocol_node.api.events`），仅作为本包的薄适配。

### 10.1 事件词汇表（`schema.py`）

**Topic**（粗粒度分类，订阅者按此过滤）：

| Topic | 值 |
|-------|----|
| `TRACE` | `trace` |
| `ANALYSIS` | `analysis` |
| `MALICIOUS` | `malicious` |
| `RECORD` | `record` |

**EventType**（细粒度事件名，格式 `<scope>.<name>`；type 前缀**不必**与 topic 一致，如 `horizontal.accumulated` 归入 `analysis` topic）：

| EventType | 值 |
|-----------|----|
| `TRACE_RECORDED` | `trace.recorded` |
| `ANALYSIS_PROGRESS` | `analysis.progress` |
| `ANALYSIS_REPORT` | `analysis.report` |
| `HOP_SCORED` | `hop.scored` |
| `HORIZONTAL_ACCUMULATED` | `horizontal.accumulated` |
| `HORIZONTAL_TRIGGERED` | `horizontal.triggered` |
| `MALICIOUS_DETECTED` | `malicious.detected` |
| `RECORD_ERROR` | `record.error` |

**过滤键约定**：`session_id` 直接匹配 payload；`did` 匹配 payload 的 `did` 或 `target_did`。

### 10.2 EventBroker（`broker.py`）

进程内发布-订阅总线。

- 单进程、单实例；非分布式（多协议节点实例间不共享事件）
- 每订阅者一个有界 `asyncio.Queue`（`QUEUE_MAXSIZE=256`），溢出丢最旧并计数（防慢客户端撑爆内存）
- 支持 topic / session_id / did 过滤，避免无关事件入队
- None-safe：组件持有 `broker: EventBroker | None`，未注入时跳过发布

| 类 | 字段/方法 |
|----|----------|
| `Event` | `id / type / topic / payload` |
| `Subscription` | `id / queue / topics / session_id / did / dropped`；`matches(event)` 按过滤条件判定 |
| `EventBroker` | `publish(event_type, payload, *, topic)`、`subscribe(topics, session_id, did) -> Subscription`、`unsubscribe(sub)` |

`publish` 队列满时丢最旧腾位给最新，仍满则丢弃最新并记 warning。

### 10.3 帧序列化（`frames.py`）

把 `Event` 序列化为标准 SSE 帧，供 web 层直接 yield。

```python
HEARTBEAT = ": ping\n\n"   # SSE 注释行，不触发 EventSource 事件，防反代关闭空闲连接

def format_event_frame(event_id: int, event_type: str, payload: dict) -> str
```

输出格式：
```
id: <单调递增 id>
event: <事件类型>
data: <JSON payload>

```

### 10.4 事件发布点（汇总）

| 发布点 | 事件 | topic |
|--------|------|-------|
| `SqliteStore.save_behavior_entry` | `TRACE_RECORDED` | trace |
| `SqliteStore.save_hop_score` | `HOP_SCORED` | analysis |
| `SqliteStore.save_malicious_report` | `MALICIOUS_DETECTED` | malicious |
| `VerticalOrchestrator._handle_u2a` | `ANALYSIS_PROGRESS`（intent_appended） | analysis |
| `HorizontalOrchestrator.on_hop_scored` | `HORIZONTAL_ACCUMULATED` / `HORIZONTAL_TRIGGERED` | analysis |
| `HorizontalOrchestrator._set_phase` / `run_analysis` | `ANALYSIS_PROGRESS`（phase 变化）/ `ANALYSIS_REPORT` | analysis |

---

## 11. 核心数据流

### 11.1 双轮回溯确认

双轮回溯确认是 ATTP 的核心机制，确保通信链路的不可否认性。

```
  Agent A                    Agent B                  Protocol Node
    │                          │                          │
    │  ① NodeMessage           │                          │
    │  (A 签名 content)         │                          │
    ├─────────────────────────→│                          │
    │                          │                          │
    │                          │  ② BackMessage Phase 1   │
    │                          │  (B 签名 identity +      │
    │                          │   携带 A 的签名内容)      │
    │                          ├─────────────────────────→│
    │                          │                          │
    │                          │                   Branch A:│
    │                          │                   暂存为 │
    │                          │                   PendingMessage│
    │                          │                   验证 B 身份│
    │                          │                          │
    │  ③ BackMessage Phase 2   │                          │
    │  (A 签名 identity +      │                          │
    │   发送内容副本)           │                          │
    ├────────────────────────────────────────────────────→│
    │                          │                          │
    │                          │                   Branch B:│
    │                          │                   Nonce 匹配│
    │                          │                   验证 A 身份│
    │                          │                   内容一致性│
    │                          │                   行为记录│
    │                          │                          │
```

**阶段说明**：

1. **NodeMessage（A → B）**：A 构造消息，用私钥签名 `recorded_hop.content_hash()`，发送给 B
2. **BackMessage Phase 1（B → 协议节点）**：B 收到消息后，签名自己的身份（`SHA256(json({node_did, nonce}))`），携带 A 的签名内容原样回传
3. **BackMessage Phase 2（A → 协议节点）**：A 也向协议节点回传，签名自己的身份，发送与 B 一致的内容副本

**协议节点验证管线**：

| 阶段 | Branch A（Phase 1 先到） | Branch B（Phase 2 后到） |
|------|------------------------|------------------------|
| 身份验证 | 验证 B 的 `sig_identity` | 验证 A 的 `sig_identity` |
| 暂存 | 存为 `PendingMessage` | — |
| 匹配 | — | 通过 `nonce` 匹配 Phase 1 |
| 内容验证 | — | `verify_back_propagation()` 三步验证 |
| 行为记录 | — | 保存 `behavior_entry` |

### 11.2 十字锁定意图追踪流程（逐跳改版）

#### 11.2.1 纵轴逐跳评分流程（per-session）

```
  /record                    CrossLockCoordinator        VerticalOrchestrator (worker)        VerticalIntentAnalyzer
    │                              │                              │                              │
    │  hop 落库                    │                              │                              │
    ├─────────────────────────────→│  enqueue_trace(session,hop)  │                              │
    │                              ├─────────────────────────────→│ (投进有界队列,不阻塞)         │
    │                              │                              │                              │
    │                              │                   worker 消费（按 trace 序串行,per-session Lock）
    │                              │                              │                              │
    │                              │                   field_type==U2A ?                       │
    │                              │                   ┌──── 发起者 ──→ extract_intent_revision()
    │                              │                   │                  → append IntentRevision Δ
    │                              │                   │                    （不打分,只追加意图流）
    │                              │                   │                                      │
    │                              │                   ├──── 非发起者 U2A ──→ 当动作跳打分（防注入）
    │                              │                   │                                      │
    │                              │                   └──── 动作跳（A2A/A2T/T2A/A2U）──────────→
    │                              │                              │  score_hop(I, h_{i-1}, a_i)   │
    │                              │                              │  （4 维 + hidden_state）       │
    │                              │                              │←─────────────────────────────┤
    │                              │                              │  HopScore (s_i, dims, h_i)    │
    │                              │                              │                              │
    │                              │                              │  save_hop_score() → DB        │
    │                              │                              │  set_hidden_state(h_i)        │
    │                              │                              │                              │
    │                              │                              │  s_i > R_T(7.5)? ── YES → 写 malicious_reports
    │                              │                              │                  (source=vertical_analysis)
    │                              │                              │                              │
    │                              │                   （仅 sub-R_T 的跳,回调横轴）             │
    │                              │  _on_hop_scored(did,...,s_i) │                              │
    │                              ├─────────────────────────────→│                              │
```

> 队列满时 `/record` 不阻塞，溢出 hop 留在 DB，由 worker 的 catch-up 扫描（启动 / 空闲 / 手动触发）按打分游标补打。

#### 11.2.2 横轴 F 累加与跨会话确认流程（per-DID）

```
  VerticalOrchestrator         CrossLockCoordinator         HorizontalOrchestrator       HorizontalIntentAnalyzer
    │                              │                              │                              │
    │  动作跳打分后                 │                              │                              │
    │  s_i ≤ R_T                   │                              │                              │
    ├─────────────────────────────→│  on_hop_scored(did,...,s_i)  │                              │
    │                              ├─────────────────────────────→│  F += s_i²（纯平方和）        │
    │                              │                              │  volume += 1                  │
    │                              │                              │  → 发布 horizontal.accumulated│
    │                              │                              │                              │
    │                              │                              │  F > R_S(25.0) 且 volume≥2 ?│
    │                              │                              │  ──── YES ───→ fire-and-forget│
    │                              │                              │      run_analysis(did)        │
    │                              │                              │                              │
    │                              │                              │  query_hop_scores_by_did()   │
    │                              │                              │  → 选 α 个会话(W(σ)=Σs² 降序 + ρ兜底)
    │                              │                              │  → 加载各会话授权意图流        │
    │                              │                              │  → 加载上一次确认报告          │
    │                              │                              │  analyze.confirm(...) ───────→│
    │                              │                              │                              │  LLM 跨会话确认
    │                              │                              │←─────────────────────────────┤ ConfirmationVerdict
    │                              │                              │                              │
    │                              │                              │  持久化 ConfirmationReport    │
    │                              │                              │  confirmed? → 写 malicious_reports
    │                              │                              │              (source=horizontal_analysis)
    │                              │                              │  close(did)（重置 F/volume,推进游标,batch+1）
    │                              │                              │  → 发布 analysis.report       │
```

---

## 12. 数据库表结构

`Database.initialize()` 创建 8 张表和对应索引，含幂等迁移逻辑。

### 12.1 behavior_traces

行为追踪记录表，存储每次通信的详细记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `session_id` | TEXT NOT NULL | 会话 ID |
| `protocol_node_address` | TEXT NOT NULL | 协议节点地址 |
| `node_did` | TEXT NOT NULL | 发送节点 DID |
| `hop_count_a2a` | INTEGER NOT NULL | A2A 跳计数 |
| `hop_count_intra` | INTEGER NOT NULL | 内部跳计数 |
| `field_type` | TEXT NOT NULL | 行为类型（A2T/A2U/U2A/A2A/T2A） |
| `content` | TEXT | 消息内容 |
| `target` | TEXT DEFAULT '' | 目标（工具名/DID） |
| `timestamp` | REAL | 时间戳 |
| `extra` | TEXT DEFAULT '{}' | 额外信息 JSON |

**索引**：
- `idx_bt_session` — `(session_id, protocol_node_address)`
- `idx_bt_hop` — `(session_id, protocol_node_address, hop_count_a2a, hop_count_intra)`

### 12.2 vertical_hop_scores（新增）

逐跳 V-Reasoner 评分结果表（v0.3.0 新增）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `trace_id` | INTEGER NOT NULL | 关联的 trace ID |
| `session_id` | TEXT NOT NULL | 会话 ID |
| `sender_did` | TEXT NOT NULL | 发送方 DID |
| `field_type` | TEXT NOT NULL | 行为类型 |
| `hop_count_a2a` | INTEGER NOT NULL | A2A 跳计数 |
| `hop_count_intra` | INTEGER NOT NULL | 内部跳计数 |
| `score` | REAL NOT NULL DEFAULT 0 | 聚合总分 s_i ∈ [0,10] |
| `dim1`..`dim4` | REAL NOT NULL DEFAULT 0 | 4 维原始分（d1..d4） |
| `breadth` | INTEGER NOT NULL DEFAULT 0 | ≥ high 的维度数 |
| `severity` | TEXT NOT NULL DEFAULT 'none' | 代码推导的严重档 |
| `deviation_type` | TEXT NOT NULL DEFAULT 'none' | 偏离类型 |
| `evidence_refs_json` | TEXT NOT NULL DEFAULT '[]' | 证据列表 JSON |
| `hidden_state` | TEXT NOT NULL DEFAULT '' | 本跳产出的滚动隐状态 h_i |
| `timestamp` | REAL | 时间戳 |

**索引**：
- `idx_vhs_session` — `(session_id)`
- `idx_vhs_sender` — `(sender_did)`
- `idx_vhs_trace` — `(trace_id)`

### 12.3 vertical_analysis_states（重定义）

纵向分析会话状态表（意图流 + 隐状态 + 打分游标，v0.3.0 重定义）。旧表（含 `pending_count/batch_index/last_trace_id/context`）由 `_normalize_legacy_tables` 检测到缺 `intent_revisions_json` 列时 DROP 重建。

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | TEXT PK | 会话 ID |
| `initiator_did` | TEXT DEFAULT '' | 会话发起者 DID |
| `intent_revisions_json` | TEXT DEFAULT '[]' | 意图流 I=[Δ₀..Δ_m] JSON |
| `hidden_state` | TEXT DEFAULT '' | 最新滚动隐状态 |
| `last_scored_trace_id` | INTEGER DEFAULT 0 | 打分游标 |
| `updated_at` | REAL | 更新时间 |

> 旧表 `vertical_analysis_reports`（批次报告）已**废弃删除**，逐跳评分改由 `vertical_hop_scores` 承载。

### 12.4 horizontal_analysis_states（重定义）

横向分析状态表（per-DID F 累加 + 体积 + 确认游标，v0.3.0 重定义）。旧表（含 `pending_count`）由 `_normalize_legacy_tables` 检测到缺 `f_value` 列时 DROP 重建。

| 字段 | 类型 | 说明 |
|------|------|------|
| `did` | TEXT PK | 节点 DID |
| `node_type` | TEXT NOT NULL DEFAULT 'agent' | 节点类型 |
| `f_value` | REAL NOT NULL DEFAULT 0 | 累积偏离 F = Σ s²（纯平方和） |
| `volume` | INTEGER NOT NULL DEFAULT 0 | 自上次闭案以来的跳数 |
| `last_trace_id` | INTEGER NOT NULL DEFAULT 0 | 确认游标 |
| `batch_index` | INTEGER NOT NULL DEFAULT 0 | 已完成确认次数 |
| `context` | TEXT NOT NULL DEFAULT '' | 最近确认摘要（节点档案） |
| `updated_at` | REAL NOT NULL | 更新时间 |

### 12.5 horizontal_analysis_reports

横向确认报告表。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `did` | TEXT NOT NULL | 分析的目标 DID |
| `node_type` | TEXT NOT NULL | 节点类型 |
| `batch_index` | INTEGER NOT NULL DEFAULT 0 | 批次序号 |
| `report_json` | TEXT NOT NULL | 完整 ConfirmationReport JSON |
| `from_trace_id` | INTEGER NOT NULL DEFAULT 0 | 起始 trace ID |
| `to_trace_id` | INTEGER NOT NULL DEFAULT 0 | 结束 trace ID |
| `sessions_scanned` | INTEGER NOT NULL DEFAULT 0 | 实际复核会话数 |
| `timestamp` | REAL | 时间戳 |

**索引**：
- `idx_hor_did` — `(did)`
- `idx_hor_did_batch` — `(did, batch_index)`

### 12.6 node_dossiers

节点档案表（累计违规记录）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `did` | TEXT PK | 节点 DID |
| `total_violations` | INTEGER DEFAULT 0 | 累计违规次数 |
| `severity_level` | TEXT DEFAULT 'clean' | 严重等级（clean/warning/dangerous/banned） |
| `first_seen_at` | REAL | 首次发现时间 |
| `last_seen_at` | REAL | 最近发现时间 |
| `evidence_breakdown` | TEXT DEFAULT '{}' | 各类违规计数 JSON |
| `last_evidence_type` | TEXT DEFAULT '' | 最近违规类型 |
| `last_session_id` | TEXT DEFAULT '' | 最近违规会话 |
| `last_evidence_desc` | TEXT DEFAULT '' | 最近违规描述 |
| `updated_at` | REAL | 更新时间 |

**严重等级映射**：

| 累计违规次数 | severity_level |
|------------|----------------|
| 0 | clean |
| 1–3 | warning |
| ≥4 | banned（中间经过 dangerous） |

### 12.7 malicious_reports

恶意节点报告表（统一三个来源的格式；v0.3.0 起 `taint_score` 值域 0–10、`severity` 5 档）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `source` | TEXT NOT NULL | 来源（protocol_review / vertical_analysis / horizontal_analysis） |
| `target_did` | TEXT NOT NULL | 恶意节点 DID |
| `node_type` | TEXT NOT NULL DEFAULT '' | 节点类型（agent / tool / user） |
| `session_id` | TEXT NOT NULL DEFAULT '' | 会话 ID |
| `evidence_type` | TEXT NOT NULL | 证据类型 |
| `severity` | TEXT NOT NULL DEFAULT 'medium' | 严重程度 |
| `taint_score` | REAL NOT NULL DEFAULT 0.0 | 意图偏离分数（0–10） |
| `evidence_description` | TEXT NOT NULL DEFAULT '' | 证据描述 |
| `nonce` | TEXT DEFAULT '' | Nonce |
| `report_id` | INTEGER DEFAULT NULL | 关联的分析报告 ID |
| `raw_evidence` | TEXT DEFAULT '{}' | 原始证据 JSON |
| `timestamp` | REAL | 时间戳 |

**索引**：
- `idx_mr_session` — `(session_id)`
- `idx_mr_did` — `(target_did)`
- `idx_mr_source` — `(source)`

### 12.8 protocol_session_state

协议节点验证状态持久化表。

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | TEXT PK | 会话 ID |
| `completed_nonces_json` | TEXT NOT NULL DEFAULT '[]' | 已完成的 nonce 列表 |
| `hop_count_map_json` | TEXT DEFAULT NULL | hop_count 映射（可为 NULL） |
| `trusted_dids_json` | TEXT NOT NULL DEFAULT '[]' | 可信 DID 列表 |
| `updated_at` | REAL NOT NULL | 更新时间 |

---

## 13. 设计模式与总结

### 设计模式

| 模式 | 应用 | 说明 |
|------|------|------|
| **Facade** | `AgentTracer`、`ProtocolTracer`、`SqliteStore`、`CrossLockCoordinator` | 简化子系统接口 |
| **Repository** | `TraceRepository`、`VerticalRepository`、`HorizontalRepository`、`MaliciousRepository`、`ProtocolSessionRepository` | 数据访问抽象层 |
| **Factory Method** | `ProtocolTracer.create()`、`SqliteStore.create()` | 异步初始化 |
| **Observer/Callback** | `_on_hop_scored_callback`（纵→横逐跳桥接）、`EventBroker` 发布-订阅 | 事件驱动；CrossLockCoordinator 注入回调 |
| **Producer-Consumer** | `VerticalOrchestrator` per-session 有界队列 worker | `/record` 生产、worker 消费，真背压 + catch-up 补打 |
| **Strategy** | 签名引擎按密钥类型分派算法；`aggregate_score` 支持 max/sum/L^p | RSA / ECDSA / Ed25519；聚合策略可换 |
| **State Manager** | `VerticalAnalysisManager`、`HorizontalAnalysisManager` | 将分析状态（意图流 / F 累加）从编排器中解耦、带持久化 |
| **Coordinator** | `CrossLockCoordinator` | 串联纵轴逐跳评分与横轴 F 累加/确认，解耦纵横编排器 |

### 模块职责总结

| 模块 | 核心职责 | 主要使用者 |
|------|---------|-----------|
| `authentication` | DID 身份认证、密钥管理、签名验证 | Agent 端、协议节点端 |
| `provenance` | 消息溯源链构建、哈希计算、篡改检测 | Agent 端（追加跳）、协议节点（验证） |
| `message` | 消息数据结构、回传发送 | 所有节点 |
| `analysis` | 十字锁定意图追踪（纵轴逐跳评分 + 横轴 F 累加确认 + 协调器） | 协议节点端 |
| `storage` | SQLite 异步持久化（含逐跳评分、F 累加状态、幂等迁移） | 协议节点端 |
| `sessions` | 三层会话管理（App/协议节点/工具）+ 纵横分析状态管理 | 对应层次的节点 |
| `sse` | 进程内事件总线 + SSE 帧序列化 + 事件词汇表 | 协议节点端（推送用户端） |

### 技术栈

| 技术 | 用途 |
|------|------|
| `cryptography` | RSA/ECDSA/Ed25519 签名与验签 |
| `aiosqlite` | 异步 SQLite 访问 |
| `aiohttp` | DID 解析 HTTP 请求、BackMessage 回传 |
| `base58` | DID 文档中 Multibase/Base58 编码的公钥解析 |
| `openai`（AsyncOpenAI） | LLM 意图增量抽取、逐跳评分、跨会话确认 |
| `dataclasses` | 数据模型定义 |
