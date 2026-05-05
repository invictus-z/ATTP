# ATTP Core 层代码与功能分析

## 1. 概述

`python/attp/core` 是 ATTP（Agent-to-Agent Trusted Protocol，Agent 间可信传输协议）的**核心层**，负责为分布式 Agent 网络提供三大基础能力：

1. **身份认证**（Authentication）— 基于公私钥的签名与验签，确保消息来源可信
2. **溯源链**（Provenance）— 类区块链的哈希链机制，保证消息在多跳传递中不可被篡改
3. **行为追踪**（Behavior Tracing）— a/b/c/d 四类交互的完整记录与持久化

Core 层通过 **Facade 门面模式**（`MessageTracer`）对外暴露统一 API，上层业务代码（client / server / web）无需直接与子模块交互。

---

## 2. 模块架构

```
┌─────────────────────────────────────────────────────┐
│                  上层业务代码                         │
│         (client.py / server.py / web app)            │
└──────────────────────┬──────────────────────────────┘
                       │ 调用
                       ▼
┌─────────────────────────────────────────────────────┐
│              MessageTracer (Facade)                  │
│                  tracer.py                           │
│  ┌─────────────┬──────────────┬───────────────────┐ │
│  │ KeyStore    │ ChainManager │ SqliteStore       │ │
│  │ (密钥缓存)  │ (链管理)     │ (持久化)          │ │
│  └──────┬──────┴──────┬───────┴───────┬───────────┘ │
│         │             │               │             │
└─────────┼─────────────┼───────────────┼─────────────┘
          ▼             ▼               ▼
  ┌──────────────┐ ┌──────────┐  ┌────────────┐
  │authentication │ │provenance│  │  storage   │
  │  keys.py     │ │ hashing  │  │sqlite_store│
  │  signatures  │ │ chain.py │  │            │
  └──────────────┘ └──────────┘  └────────────┘
                                          │
                                          ▼
                                   ┌────────────┐
                                   │ sessions   │
                                   │ session.py │
                                   │node_message│
                                   │ manager.py │
                                   └────────────┘
```

### 依赖关系

| 模块 | 依赖 |
|------|------|
| `tracer.py` | authentication, provenance, storage, sessions |
| `provenance/chain.py` | authentication (KeyStore, signatures), provenance (hashing) |
| `storage/sqlite_store.py` | sessions (NodeMessage) |
| `sessions/session.py` | sessions (NodeMessage) |

---

## 3. 子模块详解

### 3.1 authentication — 身份认证

#### 3.1.1 keys.py：密钥加载与缓存

**核心组件**：

| 组件 | 类型 | 职责 |
|------|------|------|
| `load_private_key(key_path)` | 函数 | 从 PEM 文件加载私钥 |
| `KeyStore` | 类 | 管理公钥缓存和私钥缓存 |

**KeyStore 内部结构**：

```python
class KeyStore:
    _cache: dict[str, object]            # 公钥缓存: node_did → public_key
    _private_key_cache: dict[str, object] # 私钥缓存: 文件绝对路径 → private_key
```

**关键方法**：

| 方法 | 说明 |
|------|------|
| `cache_public_key(node_did, public_key)` | 注入公钥到缓存（由外部在验签前调用） |
| `get(node_did)` | 获取缓存的公钥，不存在返回 `None` |
| `load_private_key(key_path)` | 加载私钥并缓存，相同路径仅加载一次 |

**设计要点**：
- 公钥由外部主动注入（`cache_public_key`），支持异步场景下提前准备
- 私钥通过文件路径缓存，避免重复 I/O 和反序列化开销

> 代码位置：`python/attp/core/authentication/keys.py`

#### 3.1.2 signatures.py：签名与验签引擎

**核心函数**：

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `sign_hash(entry_hash, private_key)` | 哈希字符串 + 私钥 | Base64 签名字符串 | 对哈希值签名 |
| `verify_signature(entry_hash, signature_b64, public_key)` | 哈希字符串 + 签名 + 公钥 | `bool` | 验证签名合法性 |

**支持的密钥算法**：

| 算法 | 签名方式 | 填充/参数 |
|------|----------|-----------|
| RSA | `PSS` 签名 | `MGF1(SHA256)`, `MAX_LENGTH` 盐值 |
| ECDSA（椭圆曲线） | `ECDSA` 签名 | `SHA256` 哈希 |

**异常处理**：
- `InvalidSignature` → 返回 `False`（签名不匹配）
- 其他异常 → 记录日志并返回 `False`
- 不支持的密钥类型 → 返回空字符串（签名）或 `False`（验签）

> 代码位置：`python/attp/core/authentication/signatures.py`

---

### 3.2 provenance — 溯源链

#### 3.2.1 hashing.py：哈希计算

提供两个 SHA-256 哈希函数，是整个溯源链的**信任锚点**：

**`calculate_genesis_hash(session_id, origin_did)`** — 创世哈希：

```python
# 输入
{"session_id": "sess_001", "origin_did": "did:wba:agent_A"}
# 排序后 JSON → SHA-256 → hexdigest
```

**`calculate_hop_hash(content, node_did, target_did, hop_count, timestamp, session_id, origin_did)`** — 跳哈希：

```python
# 输入 7 个字段
# 排序后 JSON → SHA-256 → hexdigest
# 该哈希会被私钥签名，形成不可抵赖的证据
```

**设计要点**：
- 使用 `json.dumps(sort_keys=True)` 确保序列化结果的确定性
- 所有字段参与哈希，任何篡改都会导致哈希值改变

> 代码位置：`python/attp/core/provenance/hashing.py`

#### 3.2.2 chain.py：链管理器

`ChainManager` 是溯源链的核心逻辑所在，负责跳的追加、校验和回传验证。

**Hop 必填字段定义**：

```python
_HOP_REQUIRED_FIELDS = {
    "node_did": str,
    "target_did": str,
    "Hop_Count": (float, int),
    "Timestamp": (float, int),
    "Signature": str,
    "Content": str,
}
```

**核心方法详解**：

##### `append_hop(metadata, content, node_did, target_did, private_key_path) → dict`

追加一跳，完整流程：

```
1. 计算当前 hop_count（若 metadata 中无 Hop 则为 0，即创世跳）
2. 若 hop_count == 0，设置 Origin_DID = node_did
3. 获取时间戳 timestamp = time.time()
4. 计算 hop_hash = calculate_hop_hash(7个字段)
5. 加载私钥，对 hop_hash 签名
6. 构建 new_log_entry 并写入 metadata["Hop"]
7. 返回更新后的 metadata
```

##### `validate_hop(hop, prev_hop_count, timeout) → (bool, str)`

校验单条 hop 的合法性，包含三步：

| 步骤 | 校验内容 | 错误前缀 |
|------|----------|----------|
| Step 1 | 字段完整性 + 类型检查 + 值约束 | `[FIELD_MISSING]` / `[FIELD_TYPE]` / `[FIELD_VALUE]` |
| Step 2 | Hop_Count 递增校验（= prev + 1） | `[HOP_COUNT_MISMATCH]` |
| Step 3 | 时间戳超时校验（默认 300s） | `[TIMESTAMP_EXPIRED]` |

##### `verify_back_propagation(stored_hop, prev_hop, session_id, origin_did) → (bool, str)`

**回传验证** — 这是最关键的安全机制，用于检测消息在传递过程中是否被篡改。

验证三步：

| 步骤 | 逻辑 | 检测目标 |
|------|------|----------|
| step1 | 用公钥验证 prev_hop 的签名是否合法 | 签名是否被伪造 |
| step2 | stored_hop 的 Signature == prev_hop 的 Signature | 签名是否被替换 |
| step3 | stored_hop 的 hop_hash == prev_hop 的 hop_hash | 内容是否被篡改 |

**篡改分类（错误诊断）**：

| step1 | step2 | step3 | 诊断 |
|-------|-------|-------|------|
| ✅ | ✅ | ✅ | 验证通过 |
| ❌ | ❌ | — | 节点篡改内容 |
| ❌ | ✅ | ❌ | 节点篡改 pre_content |
| ❌ | ✅ | ✅ | 上一节点栽赃下一节点 |
| ✅ | ✅ | ❌ | 上一节点签名和内容不匹配 |
| 其他 | — | — | 未知验证失败 |

> 代码位置：`python/attp/core/provenance/chain.py`

---

### 3.3 sessions — 会话管理

#### 3.3.1 session.py：会话数据类

`Session` 是一个 `@dataclass`，作为单个聊天会话的元数据容器：

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | `str` | 会话标识（chat_id） |
| `metadata` | `dict[str, Any]` | 元数据字典（存储 Hop、Session_ID、Origin_DID、NodeMessage 等） |
| `updated_at` | `float` | 最后更新时间戳 |

**关键方法**：

| 方法 | 说明 |
|------|------|
| `get_trace_metadata()` | 提取溯源相关的 key（Hop, Session_ID, Origin_DID） |
| `set_trace_metadata(trace_data)` | 合并溯源 key 到 metadata |
| `get_or_create_node_message(node_did, origin_did, hop_count)` | 获取或创建指定 hop 的 NodeMessage |
| `get_node_message(hop_count)` | 按 hop 序号检索 NodeMessage |

**NodeMessage 存储机制**：每个 hop 的 NodeMessage 存储在 `metadata["node_msg_{hop_count}"]` 中。

> 代码位置：`python/attp/core/sessions/session.py`

#### 3.3.2 node_message.py：行为溯源数据结构

定义了两个核心数据类：

**`BehaviorEntry`** — 单条行为记录：

| 字段 | 类型 | 说明 |
|------|------|------|
| `field_type` | `str` | 行为类型：`"A2T"` / `"A2U"` / `"U2A"` / `"A2A"` / `"T2A"` |
| `content` | `str` | 行为内容 |
| `timestamp` | `float` | 时间戳 |
| `target` | `str` | 目标标识 |
| `extra` | `dict` | 扩展元数据 |

**`NodeMessage`** — 一个节点在一次 hop 中的全部行为：

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_did` | `str` | 当前节点 DID |
| `session_id` | `str` | 会话 ID |
| `hop_count` | `int` | hop 序号 |
| `origin_did` | `str` | 消息最初发出者的 DID |
| `entries` | `list[BehaviorEntry]` | 行为条目列表 |

**四类行为（field_type）**：

| 类型 | 方向 | 含义 | target 字段 |
|------|------|------|-------------|
| **A2T** | Agent → Tool | Agent 调用工具 | 工具名 |
| **A2U** | Agent → User | Agent 向用户发送回复 | 空 |
| **U2A** | User → Agent | 用户向 Agent 发送消息 | 空 |
| **A2A** | Agent → Agent | Agent 之间互发消息 | 目标 Agent DID |
| **T2A** | Tool → Agent | 工具返回结果（预留） | 空 |

两个数据类均支持 `to_dict()` / `from_dict()` 序列化，用于网络传输和持久化。

> 代码位置：`python/attp/core/sessions/node_message.py`

#### 3.3.3 manager.py：会话管理器

`SessionManager` 是一个轻量级的**内存会话存储**，以 `chat_id` 为键管理所有活跃会话：

```python
class SessionManager:
    _sessions: dict[str, Session]

    def get_or_create(chat_id) → Session   # 获取或创建
    def get(chat_id) → Session | None       # 获取
    def save(session) → None                # 保存
    def delete(chat_id) → None              # 删除
```

> 代码位置：`python/attp/core/sessions/manager.py`

---

### 3.4 storage — 持久化层

#### sqlite_store.py：SQLite 存储

**表结构** `behavior_traces`：

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| `id` | INTEGER | PK AUTOINCREMENT | 自增主键 |
| `session_id` | TEXT | NOT NULL | 会话 ID |
| `origin_did` | TEXT | NOT NULL | 消息源 DID |
| `node_did` | TEXT | NOT NULL | 行为发生节点 DID |
| `hop_count` | INTEGER | NOT NULL | hop 序号 |
| `field_type` | TEXT | NOT NULL | A2T/A2U/U2A/A2A/T2A |
| `content` | TEXT | — | 行为内容 |
| `target` | TEXT | DEFAULT '' | 目标标识 |
| `timestamp` | REAL | — | 时间戳 |
| `extra` | TEXT | DEFAULT '{}' | JSON 扩展数据 |

**索引**：
- `idx_bt_session`: `(session_id, origin_did)`
- `idx_bt_hop`: `(session_id, origin_did, hop_count)`

**核心方法**：

| 方法 | 说明 |
|------|------|
| `save_behavior_entry(...)` | 逐条插入行为记录（本地实时记录） |
| `save_node_message(node_message)` | 批量插入 NodeMessage 的所有 entries（接收远端 record 时） |
| `recover_behavior_trace(session_id, origin_did)` | 按 session + origin 查询完整行为链，按 hop_count 和 timestamp 排序 |

> 代码位置：`python/attp/core/storage/sqlite_store.py`

---

### 3.5 tracer.py — MessageTracer 门面类

`MessageTracer` 是整个 core 层的**统一入口**，采用 Facade 设计模式，组合三个子模块：

```python
class MessageTracer:
    _key_store: KeyStore           # 密钥管理
    _storage: SqliteStore          # 数据持久化
    _chain: ChainManager           # 链操作
```

**对外 API**：

| 方法 | 委托目标 | 说明 |
|------|----------|------|
| `cache_public_key(node_did, public_key)` | KeyStore | 注入公钥 |
| `append_hop(metadata, content, node_did, target_did, private_key_path)` | ChainManager | 追加一跳 |
| `verify_back_propagation(stored_hop, prev_hop, session_id, origin_did)` | ChainManager | 回传验证 |
| `save_behavior_entry(...)` | SqliteStore | 保存单条行为 |
| `save_node_message(node_message)` | SqliteStore | 批量保存行为 |
| `recover_behavior_trace(session_id, origin_did)` | SqliteStore | 恢复行为链 |

> 代码位置：`python/attp/core/tracer.py`

---

## 4. 设计模式分析

### 4.1 Facade 门面模式

`MessageTracer` 是典型的 Facade 实现：
- 隐藏了 `KeyStore`、`ChainManager`、`SqliteStore` 之间的复杂交互
- 上层代码只需创建 `MessageTracer(db_path)` 即可获得完整功能
- 各子模块可以独立演化，不影响上层接口

### 4.2 数据类模式

`Session`、`NodeMessage`、`BehaviorEntry` 均使用 `@dataclass` 定义：
- 清晰的字段声明和类型标注
- 自动生成 `__init__`、`__repr__` 等
- 支持 `to_dict()` / `from_dict()` 序列化模式

### 4.3 缓存模式

`KeyStore` 对公钥和私钥均采用内存缓存：
- 公钥：按 `node_did` 缓存，由外部注入
- 私钥：按文件绝对路径缓存，首次加载后复用

---

## 5. 完整交互流程示例

### 场景：Agent A 调用 Agent B，Agent B 再调用 Agent C

假设：
- Agent A: `did:wba:agent_A`，私钥 `key_a.pem`
- Agent B: `did:wba:agent_B`，私钥 `key_b.pem`
- Agent C: `did:wba:agent_C`，私钥 `key_c.pem`
- 会话 ID: `sess_001`

#### Step 1: Agent A 发起请求（创世跳）

```python
# Agent A 创建 MessageTracer
tracer_a = MessageTracer(db_path="agent_a.db")

# Agent A 的 metadata 初始状态
metadata = {"Session_ID": "sess_001"}

# 追加创世跳 (hop_count = 0)
metadata = tracer_a.append_hop(
    metadata=metadata,
    content="帮我分析这段日志中的异常",
    node_did="did:wba:agent_A",
    target_did="did:wba:agent_B",
    private_key_path="key_a.pem"
)

# 此时 metadata 变为：
# {
#   "Session_ID": "sess_001",
#   "Origin_DID": "did:wba:agent_A",       # hop_count==0 时自动设置
#   "Hop": {
#     "node_did": "did:wba:agent_A",
#     "target_did": "did:wba:agent_B",
#     "Hop_Count": 0,
#     "Timestamp": 1714567890.123,
#     "Signature": "Base64编码的RSA/ECDSA签名...",
#     "Content": "帮我分析这段日志中的异常"
#   }
# }
```

**内部发生了什么？**

```
1. hop_count = 0 (首次跳)
2. origin_did = "did:wba:agent_A"  (自动设为 node_did)
3. hop_hash = SHA256({
     "content": "帮我分析这段日志中的异常",
     "hop_count": 0,
     "node_did": "did:wba:agent_A",
     "origin_did": "did:wba:agent_A",
     "session_id": "sess_001",
     "target_did": "did:wba:agent_B",
     "timestamp": 1714567890.123
   })
   → 例如 "a1b2c3d4e5f6..."

4. private_key = load_private_key("key_a.pem")  # 首次加载并缓存
5. signature = sign_hash(hop_hash, private_key)
   → Base64 编码的签名字符串
```

#### Step 2: Agent A 记录行为（field A2T: Agent→Tool）

```python
# 记录 Agent A 调用了 "send_message" 工具
tracer_a.save_behavior_entry(
    session_id="sess_001",
    origin_did="did:wba:agent_A",
    node_did="did:wba:agent_A",
    hop_count=0,
    field_type="A2T",
    content="调用 send_message 工具发送消息到 Agent B",
    target="send_message"
)
```

#### Step 3: Agent B 收到请求，追加第二跳

```python
# Agent B 创建自己的 MessageTracer
tracer_b = MessageTracer(db_path="agent_b.db")

# Agent B 缓存 Agent A 的公钥（用于后续验签）
tracer_b.cache_public_key("did:wba:agent_A", agent_a_public_key)

# Agent B 追加跳 (hop_count = 1)
metadata = tracer_b.append_hop(
    metadata=metadata,           # 从 Agent A 收到的 metadata
    content="收到日志分析请求，转发给专家 C",
    node_did="did:wba:agent_B",
    target_did="did:wba:agent_C",
    private_key_path="key_b.pem"
)

# metadata["Hop"] 变为：
# {
#   "node_did": "did:wba:agent_B",
#   "target_did": "did:wba:agent_C",
#   "Hop_Count": 1,
#   "Timestamp": 1714567891.456,
#   "Signature": "Agent B 的签名...",
#   "Content": "收到日志分析请求，转发给专家 C"
# }
```

#### Step 4: Agent C 收到请求，追加第三跳

```python
tracer_c = MessageTracer(db_path="agent_c.db")

metadata = tracer_c.append_hop(
    metadata=metadata,
    content="异常分析完成：发现 3 个关键错误",
    node_did="did:wba:agent_C",
    target_did="did:wba:agent_B",    # 回复给 Agent B
    private_key_path="key_c.pem"
)
# hop_count = 2
```

#### Step 5: 回传验证 — 检测篡改

当消息沿 C → B → A 回传时，Agent A 进行回传验证：

```python
# Agent A 已存储了 hop_count=0 时 Agent B 的回传记录
stored_hop = {
    "node_did": "did:wba:agent_B",
    "target_did": "did:wba:agent_C",
    "Hop_Count": 1,
    "Timestamp": 1714567891.456,
    "Signature": "Agent B 的原始签名...",
    "Content": "收到日志分析请求，转发给专家 C"
}

# Agent C 声称它收到的上一跳信息（prev_hop）
prev_hop = {
    "node_did": "did:wba:agent_B",
    "target_did": "did:wba:agent_C",
    "Hop_Count": 1,
    "Timestamp": 1714567891.456,
    "Signature": "Agent B 的签名...",
    "Content": "收到日志分析请求，转发给专家 C"
}

# Agent A 验证
is_valid, error = tracer_a.verify_back_propagation(
    stored_hop=stored_hop,
    prev_hop=prev_hop,
    session_id="sess_001",
    origin_did="did:wba:agent_A"
)

# 如果一切正常 → (True, "")
# 如果 Agent C 篡改了 Content → (False, "节点篡改内容")
# 如果 Agent B 篡改了 pre_content → (False, "节点篡改pre_content")
```

#### Step 6: 恢复完整行为链

```python
# Agent A 查询整个会话的行为追踪
traces = tracer_a.recover_behavior_trace(
    session_id="sess_001",
    origin_did="did:wba:agent_A"
)

# 返回按 hop_count 和 timestamp 排序的完整行为记录：
# [
#   {"hop_count": 0, "node_did": "did:wba:agent_A", "field_type": "A2T",
#    "content": "调用 send_message 工具...", "target": "send_message", ...},
#   {"hop_count": 0, "node_did": "did:wba:agent_A", "field_type": "A2A",
#    "content": "发送消息到 Agent B", "target": "did:wba:agent_B", ...},
#   {"hop_count": 1, "node_did": "did:wba:agent_B", "field_type": "A2T",
#    "content": "调用 send_message 工具...", "target": "send_message", ...},
#   ...
# ]
```

---

## 6. 关键代码索引

| 文件 | 核心内容 |
|------|----------|
| `core/__init__.py` | 模块声明 |
| `core/tracer.py` | `MessageTracer` 门面类，组合三大子模块 |
| `core/authentication/keys.py` | `KeyStore`（公钥/私钥缓存）、`load_private_key()` |
| `core/authentication/signatures.py` | `sign_hash()`、`verify_signature()`（RSA/ECDSA） |
| `core/provenance/hashing.py` | `calculate_genesis_hash()`、`calculate_hop_hash()` |
| `core/provenance/chain.py` | `ChainManager`（append_hop / validate_hop / verify_back_propagation） |
| `core/sessions/session.py` | `Session` 数据类（per-chat 元数据容器） |
| `core/sessions/node_message.py` | `NodeMessage` + `BehaviorEntry`（A2T/A2U/U2A/A2A/T2A 行为溯源） |
| `core/sessions/manager.py` | `SessionManager`（内存会话存储） |
| `core/storage/sqlite_store.py` | `SqliteStore`（behavior_traces 表持久化） |