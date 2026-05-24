# ATTP Core 层代码与功能分析

> 本文档对 `python/attp/core/` 目录下的所有模块进行全面的代码结构与功能分析。

## 目录

- [1. 概述](#1-概述)
- [2. 模块架构总览](#2-模块架构总览)
- [3. 顶层门面（Facade）](#3-顶层门面facade)
- [4. 认证模块（authentication）](#4-认证模块authentication)
- [5. 溯源模块（provenance）](#5-溯源模块provenance)
- [6. 消息模块（message）](#6-消息模块message)
- [7. 分析模块（analysis）](#7-分析模块analysis)
- [8. 存储模块（storage）](#8-存储模块storage)
- [9. 会话模块（sessions）](#9-会话模块sessions)
- [10. 核心数据流](#10-核心数据流)
- [11. 数据库表结构](#11-数据库表结构)
- [12. 设计模式与总结](#12-设计模式与总结)

---

## 1. 概述

ATTP（Agents Traceability and Trust Protocol）Core 层是整个协议的核心实现，承载了 ATTP 四层架构中的三层核心逻辑：

| 协议层 | Core 对应模块 |
|--------|--------------|
| 安全通信层 | `authentication/` — DID 身份认证、密钥管理、签名验证 |
| 消息追踪层 | `provenance/`、`message/`、`sessions/` — 哈希链构建、双轮回溯确认、会话管理 |
| 污点分析层 | `analysis/` — LLM 驱动的语义污点检测 |
| 数据持久化 | `storage/` — SQLite 异步存储引擎 |

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
│   └── back_sender.py           # BackMessage 统一发送函数
│
├── analysis/                    # 污点分析模块
│   ├── models.py                # 数据模型（IntentDescriptor / TaintReport 等）
│   ├── analyzer.py              # LLM 语义污点分析器
│   ├── prompts.py               # LLM Prompt 模板
│   └── orchestrator.py          # 分析生命周期编排器
│
├── storage/                     # 存储模块
│   ├── database.py              # aiosqlite 连接管理与 DDL
│   ├── store.py                 # SqliteStore 外观类
│   └── repositories/            # Repository 模式
│       ├── base.py              # 基类
│       ├── trace_repo.py        # behavior_traces 仓储
│       ├── analysis_repo.py     # analysis_reports / sessions 仓储
│       ├── malicious_repo.py    # malicious_nodes / node_dossiers 仓储
│       └── session_repo.py      # protocol_session_state 仓储
│
└── sessions/                    # 会话模块
    ├── node_message.py          # BehaviorEntry 行为记录
    ├── app/                     # App 层会话
    │   ├── session.py           # AppSession
    │   └── manager.py           # AppSessionManager
    ├── protocol_node/           # 协议节点层会话
    │   ├── session.py           # ProtocolSession
    │   ├── manager.py           # ProtocolSessionManager
    │   └── pending_message.py   # PendingMessage
    └── tools/                   # 工具节点层会话
        ├── session.py           # ToolSession
        └── manager.py           # ToolSessionManager
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
                       └──→ Database (storage.database)
                       └──→ TraceRepository / AnalysisRepository / ...

AnalysisOrchestrator ──→ SemanticTaintAnalyzer
                      ──→ ProtocolSessionManager
                      ──→ ProtocolTracer
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
- `load_private_key()` — 加载私钥（带缓存，同路径只加载一次）
- `append_hop()` — 构建新的跳记录，包含签名

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
    async def save_behavior_entry(...)
    async def recover_behavior_trace(session_id, protocol_node_address=None) -> list
    async def recover_traces_since(session_id, since_id) -> tuple[list, int]

    # 分析报告
    async def save_analysis_report(report_json)
    async def recover_analysis_reports(session_id) -> list

    # 分析会话状态
    async def save_analysis_session(session_id, state)
    async def load_analysis_session(session_id) -> dict | None

    # 恶意节点报告
    async def save_malicious_report(report)
    async def query_malicious_nodes(session_id=None, malicious_did=None) -> list

    # 节点档案
    async def query_dossier(did) -> dict | None
    async def query_all_dossiers(severity_level=None, limit=100) -> list
```

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

- `load_private_key(key_path)` — 带缓存的私钥加载。将路径 resolve 为绝对路径后缓存，后续相同路径直接返回缓存对象
- `cache_public_key(node_did, public_key)` — 注入公钥到缓存（由 DIDResolver 或外部调用）
- `get(node_did)` — 获取缓存的公钥，不存在返回 `None`

**顶层函数** `load_private_key(key_path)` — 从 PEM 文件加载私钥（无缓存版本），使用 `cryptography` 库的 `load_pem_private_key`。

### 4.2 签名引擎（`signatures.py`）

支持三种非对称加密算法的签名与验签：

| 算法 | 签名方式 | 验签方式 |
|------|---------|---------|
| **RSA** | PSS 填充 + SHA-256 | PSS + SHA-256 |
| **ECDSA** (secp256k1/P-256/P-384/P-521) | ECDSA + SHA-256 | ECDSA + SHA-256（先尝试 DER，失败回退 compact） |
| **Ed25519** | 原生 Ed25519 | 原生 Ed25519 |

**核心函数**：

- `sign_hash(entry_hash, private_key) -> str` — 对哈希字符串签名，返回 Base64 编码的签名
- `verify_signature(entry_hash, signature_b64, public_key) -> bool` — 验证签名

**ECDSA 特殊处理**：由于 JS 端（Web Crypto API / @noble/secp256k1）输出 compact 格式（raw `r||s`），而 Python `cryptography` 库期望 DER 格式，验签时实现了双格式兼容：

```python
# 先尝试 DER 格式（Python 原生输出）
try:
    public_key.verify(sig_bytes, data, ec.ECDSA(hashes.SHA256()))
    return True
except InvalidSignature:
    pass
# DER 失败，尝试 compact (r||s) 格式
expected_compact_len = _ec_key_byte_size(public_key) * 2
if len(sig_bytes) == expected_compact_len:
    der_sig = _compact_to_der(sig_bytes)
    public_key.verify(der_sig, data, ec.ECDSA(hashes.SHA256()))
```

### 4.3 DID 文档解析器（`did_resolver.py`）

完整的 DID 文档解析实现，支持带 TTL 缓存和重试机制的 DID → 公钥解析。

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
| `JsonWebKey2020` | JWK | 多曲线 |

#### DIDResolutionResult

解析结果数据类，包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `public_key` | `object \| None` | 提取的公钥对象 |
| `node_type` | `str \| None` | 节点类型（agent/tool/user） |
| `did_document` | `dict \| None` | 原始 DID 文档 |
| `from_cache` | `bool` | 是否来自缓存 |
| `failure_reason` | `str \| None` | 失败原因 |
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
- **TTL 缓存**：默认 300 秒，避免频繁网络请求
- **指数退避重试**：最多重试 2 次，延迟倍增
- **节点类型识别**：从 DID 文档 `service` 数组中提取 `ATTPNodeType`（endpoint 格式：`attp:type:agent`）
- **多格式公钥提取**：支持 JWK、Multibase、Base58 三种编码格式

**URL 构建规则**：

```
did:wba:<domain>:<path>[:<key_identifier>]
→ http://<domain>/<path>/did.json
→ http://<domain>/.well-known/did.json (无 path 时)
```

---

## 5. 溯源模块（provenance）

溯源模块实现消息溯源链的构建和验证，是 ATTP 消息追踪层的核心。

### 5.1 哈希计算（`hashing.py`）

两个 SHA-256 哈希函数，输入为确定性 JSON 序列化（`sort_keys=True, separators=(",",":")`）：

- `calculate_genesis_hash(session_id, protocol_node_address) -> str` — 创世标识哈希
- `calculate_hop_hash(content, sender_did, target_did, hop_count, timestamp, session_id) -> str` — 单跳消息哈希

### 5.2 链管理器（`chain.py`）

管理消息跳的追加、校验和回传验证。

#### hop_count 语义

`hop_count` 为二元组 `[a2a_count, intra_count]`：

- `a2a_count` — 跨 Agent 间（A2A）通信的跳序号
- `intra_count` — Agent 内部操作（A2T/A2U）的跳序号

递增规则：
- `behavior_type == "A2A"` → `[prev[0] + 1, 0]`
- 其他 → `[prev[0], prev[1] + 1]`
- 首条消息 → `[0, 0]`

#### append_hop(metadata, content, node_did, target_did, private_key_path, behavior_type=None)

构建新的跳记录并签名。流程：

1. 从 `metadata["recorded_hop"]` 获取前一跳信息
2. 根据 `behavior_type` 递增 hop_count
3. 调用 `calculate_hop_hash()` 计算哈希
4. 加载私钥并调用 `sign_hash()` 签名
5. 构建新跳记录并更新 `metadata["recorded_hop"]`

#### validate_hop(hop, timeout=300.0) -> tuple[bool, str]

校验单条 hop 的完整性：

| 校验步骤 | 内容 |
|---------|------|
| Step 1 | 字段完整性检查（`sender_did`, `target_did`, `hop_count`, `timestamp`, `sig_content`, `content`） |
| Step 1b | 值约束（非空、hop_count 二元组、非负） |
| Step 2 | timestamp 超时检查（默认 300 秒） |

#### verify_back_propagation(stored_hop, prev_hop, session_id) -> tuple[bool, str]

**回传验证**的核心方法，对比 Branch A（发送方暂存）和 Branch B（接收方到达）的记录，检测篡改。

三步验证：

| 步骤 | 检查内容 | 失败含义 |
|------|---------|---------|
| Step 1 | 上一跳签名验证（`verify_signature(prev_hop_hash, prev_sign, prev_public_key)`） | 签名是否由声称的节点签署 |
| Step 2 | 签名字节级比对（`stored_hop["Signature"] == prev_sign`） | 双方签名必须完全一致（ECDSA 每次签名不同，必须共享同一签名） |
| Step 3 | 哈希一致性（`store_hop_hash == prev_hop_hash`） | 内容是否被篡改 |

**篡改诊断矩阵**：

| Step 1 | Step 2 | Step 3 | 诊断 |
|--------|--------|--------|------|
| ✗ | ✗ | — | 当前节点篡改内容 |
| ✗ | ✓ | ✗ | 当前节点篡改 pre_content |
| ✗ | ✓ | ✓ | 上一节点栽赃下一节点 |
| ✓ | ✓ | ✗ | 上一节点签名和内容不匹配 |

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

- `content_hash()` — 计算除 `sig_content` 外所有字段的 SHA-256 哈希
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

- `sign_content(private_key)` — 发送方私钥对 `recorded_hop` 内容签名
- `verify_content(public_key)` — 验证签名

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
| `sig_identity` | `sign_identity(private_key)` | 签名 `SHA256(node_did + nonce)`，确认回传者身份 |
| `recorded_hop.sig_content` | `sign_content(private_key)` | 签名 hop 内容哈希，确认内容完整性（由发送方签署） |

验证方法：
- `verify_identity(public_key)` — 验证身份签名
- `verify_content(public_key)` — 验证内容签名

### 6.4 send_back_message（`back_sender.py`）

统一的 BackMessage 发送函数，封装构造、签名、HTTP 发送和错误处理。

```python
async def send_back_message(
    protocol_url, node_did, nonce, recorded_hop, private_key, timeout=10.0
) -> None
```

**流程**：
1. 构造 `BackMessage`
2. 调用 `sign_identity()` 签名身份
3. POST 到 `{protocol_url}/record` 端点
4. 处理响应（成功 / 协议节点拒绝 / HTTP 错误）

**异常**：`BackPropagationError` — 回传失败时抛出（协议节点拒绝、HTTP 错误、网络异常）。

---

## 7. 分析模块（analysis）

基于 LLM 的语义污点分析系统，实现 ATTP 污点分析层的核心逻辑。

### 7.1 数据模型（`models.py`）

#### IntentDescriptor — 结构化用户意图

从用户原始输入中提取的意图描述：

| 字段 | 类型 | 说明 |
|------|------|------|
| `original_task` | `str` | 用户原始输入 |
| `core_objective` | `str` | 核心目标（一句话） |
| `constraints` | `list[str]` | 约束条件 |
| `involved_capabilities` | `list[str]` | 涉及的能力域（文件操作、网络请求等） |
| `risk_level` | `str` | 风险等级（low / medium / high） |

#### NodeBehaviorProfile — 节点行为画像

按 `(node_did, hop_count[0])` 分组聚合的行为记录：

| 字段 | 说明 |
|------|------|
| `field_a` | Agent → Tool 调用记录 |
| `field_b` | Agent → User 回复记录 |
| `field_d` | Agent → Agent 消息记录 |

#### EvidenceItem — 证据条目

引用具体 trace 条目的证据：

| 字段 | 说明 |
|------|------|
| `trace_ids` | 引用的 trace ID 列表 |
| `severity_hint` | 严重程度（info / warning / critical） |

#### NodeTaintVerdict — 节点污点判定

单个节点的分析判定结果：

| 字段 | 说明 |
|------|------|
| `aligned` | 行为是否与用户意图一致 |
| `deviation_type` | 偏离类型（none / goal_hijack / constraint_violation / unauthorized_action） |
| `influence_detected` | 是否检测到节点间恶意影响 |
| `influence_type` | 影响类型（instruction_injection / info_collection / privilege_escalation / social_engineering / goal_replacement） |
| `taint_score` | 污点分数（0.0 - 1.0） |
| `severity` | 严重程度（none / low / medium / high） |

#### TaintReport — 完整分析报告

| 字段 | 说明 |
|------|------|
| `batch_index` | 批次序号 |
| `from_trace_id / to_trace_id` | 分析的 trace ID 范围 |
| `node_verdicts` | 各节点的判定结果 |
| `overall_verdict` | 总体判定（clean / suspicious / malicious / error） |
| `context_summary` | 上下文摘要（传递给下一批次分析） |

### 7.2 SemanticTaintAnalyzer（`analyzer.py`）

基于 LLM 的语义污点分析引擎，通过 OpenAI 兼容 API 调用大模型。

#### 两阶段分析流程

**阶段一：意图提取**（`extract_intent`）

从用户原始输入提取结构化意图（`IntentDescriptor`），使用 `INTENT_EXTRACTION_PROMPT`。

**阶段二：语义污点分析**（`analyze`）

对一批行为 trace 执行两阶段分析：

1. **意图对齐检查**：判断节点行为是否与用户核心目标一致
2. **节点间影响力分析**：检查 Agent→Agent 消息中是否存在恶意影响

#### 内部处理流程

```
traces (list[dict])
  ↓ _reconstruct_profiles()    — 按 (node_did, a2a_count) 分组
profiles (list[NodeBehaviorProfile])
  ↓ _build_flow_graph()        — 构建消息流向图
  ↓ _format_behaviors()        — 格式化为 LLM 输入
ANALYSIS_PROMPT
  ↓ LLM 调用
TaintReport
```

### 7.3 Prompt 模板（`prompts.py`）

#### INTENT_EXTRACTION_PROMPT

要求 LLM 从用户输入中提取 JSON 格式的结构化意图，包含 `core_objective`、`constraints`、`involved_capabilities`、`risk_level`。

#### ANALYSIS_PROMPT

要求 LLM 执行两阶段分析并返回 JSON 格式的判定结果，包含：
- `node_verdicts` — 每个节点的判定
- `overall_verdict` — 总体判定
- `context_summary` — 传递给下一批次的上下文

污点评分标准：

| 分数范围 | severity | 含义 |
|---------|----------|------|
| 0.0 - 0.2 | none | 无异常 |
| 0.2 - 0.4 | low | 轻微偏差 |
| 0.4 - 0.7 | medium | 中度可疑 |
| 0.7 - 1.0 | high | 高度可疑/确认恶意 |

### 7.4 AnalysisOrchestrator（`orchestrator.py`）

分析生命周期编排器，协调意图提取、报告计数和分析调度。

**设计原则**：完全由 DataPort record 接收驱动，无 Web 层依赖。

#### 回调接口

| 回调 | 触发时机 | 功能 |
|------|---------|------|
| `on_field_U2A_recorded(session_id, content)` | User→Agent 消息记录 | 提取用户意图 |
| `on_record_received(session_id)` | 每条 record 到达 | 递增计数，达到 batch_size 时触发分析 |

#### 核心分析流程（`run_analysis`）

```
1. 检查 intent 是否已提取（否则重试，最多 3 次）
2. 恢复未分析的 traces（recover_traces_since）
3. 调用 SemanticTaintAnalyzer.analyze()
4. 持久化报告到 SQLite
5. 更新 session 状态（重置计数、移动游标、存储上下文）
6. 如果判定为 suspicious/malicious，触发安全告警
```

#### 异步任务管理

- `trigger_analysis_async(session_id)` — 发射后不管（fire-and-forget）的分析任务
- `get_analysis_status(session_id)` — 查询异步任务状态（running / completed / not_found）

#### 状态持久化

分析状态通过 SQLite 持久化，支持崩溃恢复：

```python
await _persist_state(session_id)  # 保存 intent、report_count、last_trace_id、batch_index、context
await _restore_state(session_id)  # 从 SQLite 恢复到 Session（仅首次）
```

---

## 8. 存储模块（storage）

基于 aiosqlite 的异步 SQLite 存储引擎，采用 **Repository 模式**分层组织。

### 8.1 Database（`database.py`）

aiosqlite 连接管理器，提供三个便捷方法：

| 方法 | 说明 |
|------|------|
| `initialize()` | 执行全部 DDL（建表 + 索引），共 6 张表 |
| `execute(sql, params)` | 执行写操作并自动 commit |
| `execute_fetch(sql, params)` | 查询返回 `list[dict]` |
| `execute_fetchone(sql, params)` | 查询返回单行 `dict` 或 `None` |

**严重等级映射**：

```python
_SEVERITY_THRESHOLDS = [(0, "clean"), (1, "warning"), (4, "dangerous")]
# 4+ 次违规 → "banned"
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
| `recover_behavior_trace(session_id, protocol_node_address)` | 按 session 查询全部 trace |
| `recover_traces_since(session_id, since_id)` | 查询指定 ID 之后的 trace（增量分析用） |

**字段映射**：数据库中 `node_did` → 返回时 `sender_did`，`target` → `target_did`，`hop_count_a2a/intra` → `hop_count`。

### 8.4 AnalysisRepository（`repositories/analysis_repo.py`）

`analysis_reports` 和 `analysis_sessions` 的读写。

| 方法 | 功能 |
|------|------|
| `save_analysis_report(report_json)` | 从 JSON 解析字段并插入报告 |
| `recover_analysis_reports(session_id)` | 按 session 查询全部报告 |
| `save_analysis_session(session_id, state)` | INSERT OR REPLACE 分析状态 |
| `load_analysis_session(session_id)` | 加载分析状态 |

### 8.5 MaliciousRepository（`repositories/malicious_repo.py`）

`malicious_nodes` 和 `node_dossiers` 的读写。

| 方法 | 功能 |
|------|------|
| `save_malicious_report(...)` | 插入恶意报告并自动 upsert dossier |
| `query_malicious_nodes(session_id, malicious_did)` | 条件查询恶意节点 |
| `upsert_dossier(did, evidence_type, session_id, description)` | 更新或创建节点档案 |
| `query_dossier(did)` | 查询单个 DID 档案 |
| `query_all_dossiers(severity_level, limit)` | 查询所有档案（可筛选） |

**Dossier 更新逻辑**：
- 首次创建：`total_violations=1`, `severity_level=warning`
- 后续更新：递增 `total_violations`，按阈值映射 `severity_level`（warning → dangerous → banned）

### 8.6 ProtocolSessionRepository（`repositories/session_repo.py`）

`protocol_session_state` 的读写，用于验证状态持久化。

| 方法 | 功能 |
|------|------|
| `save_verification_state(session_id, state)` | 保存 completed_nonces / hop_count_map / trusted_dids |
| `load_verification_state(session_id)` | 加载验证状态（JSON 反序列化） |
| `delete_verification_state(session_id)` | 删除验证状态 |

### 8.7 SqliteStore（`store.py`）

**外观类**，统一代理所有 Repository，对外接口与原始 SqliteStore 完全一致。

```
SqliteStore
  ├── TraceRepository       → behavior_traces
  ├── AnalysisRepository    → analysis_reports + analysis_sessions
  ├── MaliciousRepository   → malicious_nodes + node_dossiers
  └── ProtocolSessionRepository → protocol_session_state
```

通过 `@classmethod async def create(db_path)` 异步工厂方法初始化。

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
```

核心方法：
- `get_trace_metadata()` — 提取追踪相关键（`recorded_hop`, `protocol_url`）
- `set_trace_metadata(trace_data)` — 合并追踪键到 metadata

#### AppSessionManager

内存会话存储，按 `chat_id` 索引。提供 `locked_session()` 异步上下文管理器，防止并发的 read-modify-write 竞争（如 hop_count 损坏）。

```python
async with manager.locked_session(chat_id) as session:
    trace = session.get_trace_metadata()
    # ... compute hop, do I/O ...
    session.set_trace_metadata(new_trace)
    # save() 自动调用
```

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

协议节点层 per-session 状态容器，管理验证状态和分析状态。

核心功能分组：

| 功能 | 方法 |
|------|------|
| **Pending 管理** | `store_pending_message()`, `get_pending_message()`, `remove_pending_message()`, `pop_expired_pending_messages()` |
| **Hop count 校验** | `get_max_a2a_count()`, `get_latest_intra_count()` |
| **Nonce 追踪** | `mark_nonce_completed()`, `has_subsequent_activity_after()`, `has_subsequent_with_different_verified_identity()` |
| **可信名单** | `add_trusted_did()`, `get_latest_trusted_did()`, `clear_trusted_list()` |
| **验证便捷方法** | `complete_verification(nonce, hop_count, trusted_did)` — 一次完成所有 Branch B 状态更新 |
| **分析状态** | `increment_report_count()`, `reset_report_count()`, `update_analysis_cursor()`, `set_intent()`, `get_intent()` |

#### ProtocolSessionManager

协议节点层会话存储，支持 SQLite 持久化。

- `get_or_create(session_id)` — 惰性恢复：首次访问时从 SQLite 加载验证状态
- `save(session)` — 同时写入内存和 SQLite（如果有 storage）

### 9.4 工具节点层会话

#### ToolSession

工具节点侧 per-session 状态容器。

```python
@dataclass
class ToolSession:
    key: str
    protocol_node_address: str = ""
    metadata: dict[str, Any]
```

核心方法：
- `store_pending_request(nonce, request_info)` — 暂存待处理的工具调用
- `get_pending_request(nonce)` / `remove_pending_request(nonce)` — 查询/移除
- `get_last_hop_count()` / `set_last_hop_count(hc)` — 跳计数追踪

#### ToolSessionManager

纯内存会话存储，无持久化需求。

---

## 10. 核心数据流

### 10.1 双轮回溯确认

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
2. **BackMessage Phase 1（B → 协议节点）**：B 收到消息后，签名自己的身份（`SHA256(node_did + nonce)`），携带 A 的签名内容原样回传
3. **BackMessage Phase 2（A → 协议节点）**：A 也向协议节点回传，签名自己的身份，发送与 B 一致的内容副本

**协议节点验证管线**：

| 阶段 | Branch A（Phase 1 先到） | Branch B（Phase 2 后到） |
|------|------------------------|------------------------|
| 身份验证 | 验证 B 的 `sig_identity` | 验证 A 的 `sig_identity` |
| 暂存 | 存为 `PendingMessage` | — |
| 匹配 | — | 通过 `nonce` 匹配 Phase 1 |
| 内容验证 | — | `verify_back_propagation()` 三步验证 |
| 行为记录 | — | 保存 `behavior_entry` |

### 10.2 语义污点分析流程

```
  DataPort                    AnalysisOrchestrator          SemanticTaintAnalyzer
    │                              │                              │
    │  U2A record                  │                              │
    ├─────────────────────────────→│                              │
    │                              │  extract_intent(content)     │
    │                              ├─────────────────────────────→│
    │                              │  IntentDescriptor            │
    │                              │←─────────────────────────────┤
    │                              │                              │
    │  each record                 │                              │
    ├─────────────────────────────→│                              │
    │                              │  increment_report_count()    │
    │                              │                              │
    │  ... (N records)             │                              │
    │                              │  count >= batch_size?        │
    │                              │  ──── YES ───→               │
    │                              │                              │
    │                              │  recover_traces_since()      │
    │                              │  → SqliteStore               │
    │                              │                              │
    │                              │  analyze(traces, intent)     │
    │                              ├─────────────────────────────→│
    │                              │                              │
    │                              │              LLM 调用        │
    │                              │              (两阶段分析)     │
    │                              │                              │
    │                              │  TaintReport                 │
    │                              │←─────────────────────────────┤
    │                              │                              │
    │                              │  save_analysis_report()      │
    │                              │  → SqliteStore               │
    │                              │                              │
    │                              │  suspicious/malicious?       │
    │                              │  → 安全告警                   │
```

---

## 11. 数据库表结构

Database 类在 `initialize()` 中创建 6 张表和对应索引。

### 11.1 behavior_traces

行为追踪记录表，存储每次通信的详细记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
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

### 11.2 analysis_reports

分析报告表。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `session_id` | TEXT NOT NULL | 会话 ID |
| `batch_index` | INTEGER NOT NULL | 批次序号 |
| `report_json` | TEXT NOT NULL | 完整报告 JSON |
| `from_trace_id` | INTEGER NOT NULL | 起始 trace ID |
| `to_trace_id` | INTEGER NOT NULL | 结束 trace ID |
| `timestamp` | REAL | 时间戳 |

**索引**：`idx_ar_session` — `(session_id)`

### 11.3 analysis_sessions

分析会话状态表（支持崩溃恢复）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | TEXT PK | 会话 ID |
| `intent_json` | TEXT | 意图 JSON |
| `report_count` | INTEGER DEFAULT 0 | 当前批次报告计数 |
| `last_trace_id` | INTEGER DEFAULT 0 | 最后分析的 trace ID |
| `batch_index` | INTEGER DEFAULT 0 | 当前批次序号 |
| `context` | TEXT DEFAULT '' | 上下文摘要 |
| `updated_at` | REAL | 更新时间 |

### 11.4 node_dossiers

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
| 1-3 | warning |
| 4+ | banned（中间经过 dangerous） |

### 11.5 malicious_nodes

恶意节点报告表。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `session_id` | TEXT NOT NULL | 会话 ID |
| `malicious_did` | TEXT NOT NULL | 恶意节点 DID |
| `evidence_type` | TEXT NOT NULL | 证据类型 |
| `evidence_description` | TEXT | 证据描述 |
| `nonce` | TEXT | Nonce |
| `timestamp` | REAL | 时间戳 |
| `raw_evidence` | TEXT DEFAULT '{}' | 原始证据 JSON |

**索引**：
- `idx_mn_session` — `(session_id)`
- `idx_mn_did` — `(malicious_did)`

### 11.6 protocol_session_state

协议节点验证状态持久化表。

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | TEXT PK | 会话 ID |
| `completed_nonces_json` | TEXT DEFAULT '[]' | 已完成的 nonce 列表 |
| `hop_count_map_json` | TEXT | hop_count 映射 |
| `trusted_dids_json` | TEXT DEFAULT '[]' | 可信 DID 列表 |
| `updated_at` | REAL NOT NULL | 更新时间 |

---

## 12. 设计模式与总结

### 设计模式

| 模式 | 应用 | 说明 |
|------|------|------|
| **Facade** | `AgentTracer`、`ProtocolTracer`、`SqliteStore` | 简化子系统接口 |
| **Repository** | `TraceRepository`、`AnalysisRepository` 等 | 数据访问抽象层 |
| **Factory Method** | `ProtocolTracer.create()`、`SqliteStore.create()` | 异步初始化 |
| **Observer/Callback** | `on_field_U2A_recorded()`、`on_record_received()` | DataPort → Orchestrator 事件驱动 |
| **Strategy** | 签名引擎根据密钥类型选择算法 | RSA / ECDSA / Ed25519 |
| **Template Method** | `send_back_message()` | 统一回传流程 |

### 模块职责总结

| 模块 | 核心职责 | 主要使用者 |
|------|---------|-----------|
| `authentication` | DID 身份认证、密钥管理、签名验证 | Agent 端、协议节点端 |
| `provenance` | 消息溯源链构建、哈希计算、篡改检测 | Agent 端（追加跳）、协议节点（验证） |
| `message` | 消息数据结构、回传发送 | 所有节点 |
| `analysis` | LLM 语义污点分析、意图提取、恶意检测 | 协议节点端 |
| `storage` | SQLite 异步持久化 | 协议节点端 |
| `sessions` | 三层会话管理（App/协议节点/工具） | 对应层次的节点 |

### 技术栈

| 技术 | 用途 |
|------|------|
| `cryptography` | RSA/ECDSA/Ed25519 签名与验签 |
| `aiosqlite` | 异步 SQLite 访问 |
| `aiohttp` | DID 解析 HTTP 请求、BackMessage 回传 |
| `base58` | DID 文档中 Multibase/Base58 编码的公钥解析 |
| `openai`（AsyncOpenAI） | LLM 语义污点分析 |
| `dataclasses` | 数据模型定义 |