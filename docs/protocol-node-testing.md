# Protocol Node 测试文档

## 概述

Protocol Node 测试套件覆盖 ATTP 协议节点的全部核心功能，包括消息记录、恶意节点检测、行为溯源、API 查询等。共 **132 个测试用例**，分为单元测试和集成测试两层。

## 快速开始

```bash
# 在项目根目录，使用 uv 虚拟环境

# 运行全部测试
.venv/Scripts/python -m pytest python/tests/ -v

# 仅运行单元测试
.venv/Scripts/python -m pytest python/tests/unit/ -v

# 仅运行集成测试
.venv/Scripts/python -m pytest python/tests/integration/ -v

# 运行特定模块
.venv/Scripts/python -m pytest python/tests/unit/test_malicious_detector.py -v

# 运行并显示简短错误
.venv/Scripts/python -m pytest python/tests/ -v --tb=short
```

## 依赖

测试依赖已安装在项目 uv 虚拟环境中：

| 依赖 | 用途 |
|------|------|
| pytest | 测试框架 |
| pytest-asyncio | 异步测试支持 |
| httpx | FastAPI 应用内 HTTP 测试 |
| cryptography | 生成测试密钥对 |
| aiosqlite | 异步 SQLite（已随项目安装） |
| base58 | DID 文档 multibase 解码 |

## 目录结构

```
python/tests/
├── conftest.py                  # 共享 fixtures（密钥、DID mock、会话管理器）
├── fixtures/
│   ├── crypto_helpers.py        # 密钥生成、DID 文档构建工具
│   └── sample_data.py           # 可复用的 BackMessage/RecordedHop 样例数据
├── unit/                        # 单元测试 — 隔离测试单个组件
│   ├── test_signatures.py       # 加密签名/验证
│   ├── test_recorded_hop.py     # RecordedHop 数据模型
│   ├── test_back_message.py     # BackMessage 签名/验证
│   ├── test_node_message.py     # NodeMessage 签名/验证
│   ├── test_middleware.py       # 中间件验证管道 + intercept_record
│   ├── test_malicious_detector.py # 恶意检测器决策树
│   ├── test_behavior_controller.py # 行为控制器分发
│   ├── test_protocol_session.py # 协议会话状态管理
│   ├── test_pending_message.py  # PendingMessage 过期机制
│   └── test_config.py           # 配置加载/保存
└── integration/                 # 集成测试 — 完整 HTTP 请求到数据库写入
    ├── conftest.py              # 集成测试 fixtures（FastAPI app + SQLite）
    ├── test_record_endpoint.py  # POST /record 完整管道
    ├── test_api_endpoints.py    # 全部 API 查询端点
    └── test_full_session_flow.py # 端到端多跳会话 + 恶意检测
```

## 测试原理

### 单元测试

每个测试文件对应一个源代码模块，通过 mock 隔离外部依赖（如 DID 解析器的 HTTP 调用），直接调用函数/方法验证输入输出。

**mock 策略**：
- `DIDResolver` → `AsyncMock`，预配置三个 DID（agent/tool/user）的解析结果
- `ProtocolTracer` → `MagicMock`，不连接真实数据库
- `MaliciousNodeDetector` → `AsyncMock`（在中间件测试中）

### 集成测试

构建完整的 FastAPI 应用，使用真实 SQLite 数据库（临时文件）+ mock DID 解析器。通过 httpx `AsyncClient` + `ASGITransport` 发送真实 HTTP 请求，走完从请求进入到数据库写入的完整管道。

**不绑定端口**：`ASGITransport` 直接在进程内调用 FastAPI，不需要启动真实的 uvicorn 服务器。

**数据库隔离**：每个测试用例使用 `tmp_path` 创建独立的临时 SQLite 文件，测试结束后自动清理。不使用 `:memory:` 模式，因为项目的存储层每次查询新建连接，内存数据库无法跨连接共享数据。

## 测试覆盖的协议功能

### 1. 加密原语（11 个测试）

验证 RSA、secp256k1、P-256 三种密钥的签名和验证：

| 测试 | 验证内容 |
|------|---------|
| 签名往返 | 签名后验证通过 |
| 错误密钥 | 用不同公钥验证 → 失败 |
| 篡改哈希 | 对不同的哈希验证 → 失败 |
| 空签名/损坏签名 | 边界输入处理 |

### 2. 数据模型（24 个测试）

**RecordedHop**：content_hash 确定性、字段敏感性、序列化往返。

**BackMessage**：身份签名（sign_identity/verify_identity）、内容签名（sign_content/verify_content）、身份哈希确定性。

**NodeMessage**：内容签名/验证、序列化往返。

### 3. 中间件管道（23 个测试）

**字段验证** `_validate_back_message`（12 个）：

验证 12 种无效输入被正确拒绝：空 node_did、空 nonce、空 sig_identity、空 session_id、空 sender_did、空 target_did、hop_count 类型/长度/负数、timestamp 为 0、空 sig_content。

**intercept_record 完整管道**（11 个）：

| 场景 | 预期 |
|------|------|
| Branch A：首次回传 | status="stored"，PendingMessage 已存储 |
| Branch A：身份验证通过/失败 | identity_verified = True/False |
| Branch B：验证通过 (U2A/A2T) | status="verified"，behavior_type 正确 |
| Branch B：恶意检测到 | status="malicious" |
| DID 解析失败 | status="error" |
| 节点类型缺失 | status="error" |
| 回传验证失败 | status="error" |
| hop_count=[0,0] 非 U2A | 拒绝 |
| A2A hop_count 递增违规 | 拒绝 |

### 4. 恶意检测器（15 个测试）

**双重回传决策树**（9 个）—— 覆盖完整决策路径：

```
Step 0a: BP1 身份伪造 + 有信任列表 → IDENTITY_TAMPERING（通报信任列表）
Step 0a: BP1 身份伪造 + 无信任列表 → IDENTITY_TAMPERING（报告 bp1_did）
Step 0b: BP1 DID ≠ 最新信任名单 → TRUSTED_LIST_VIOLATION
Step 1:  BP2 DID 解析失败 → IDENTITY_TAMPERING（报告 target）
Step 1:  BP2 身份验证失败 → IDENTITY_TAMPERING
Step 2:  相同 DID → SAME_DID_DUPLICATE
Step 3:  BP1 内容签名无效 → CONTENT_TAMPERING
Step 4:  交叉验证成功 → None（干净）
Step 4:  交叉验证失败 → INDISTINGUISHABLE_PAIR
```

**单次回传决策树**（6 个）：

```
Case A: 身份伪造 + 有信任列表 → IDENTITY_TAMPERING
Case A: 身份伪造 + 无信任列表 → IDENTITY_TAMPERING
Case B: DID ≠ 最新名单 → TRUSTED_LIST_VIOLATION
Case C: 后续不同身份 → NO_PROPAGATION
Case C: 后续相同身份 → None（视为恶意节点自发自弃）
Case C: 无后续活动 → None（抛弃）
```

### 5. 协议会话（14 个测试）

PendingMessage 存储/检索/过期/移除、完成验证更新状态、信任列表操作、后续活动检测、分析状态管理。

### 6. POST /record 集成（8 个测试）

通过 HTTP 请求验证完整管道：无效 JSON、缺少字段、Branch A 存储、Branch B 验证通过（U2A/A2T）、同 DID 恶意检测、DID 解析失败、hop_zero 校验。

### 7. API 端点集成（12 个测试）

| 端点 | 测试 |
|------|------|
| `GET /api/status` | 返回 ok |
| `GET /api/behavior/{sid}` | 空会话 / 有数据 |
| `GET /api/analysis/{sid}` | 无报告 |
| `GET /api/analysis/aggregate/{sid}` | 合并 traces + reports + alerts |
| `POST /api/analysis/trigger/{sid}` | 禁用时返回 triggered=false |
| `GET /api/analysis/status/{sid}` | not_found |
| `GET /api/malicious/session/{sid}` | 空会话 / 有报告 |
| `GET /api/malicious/did/{did}` | 空 DID / 有报告 |
| `GET /api/malicious/dossier/{did}` | 未找到 / 完整档案 |
| `GET /api/malicious/dossiers` | 全部档案 |

### 8. 端到端场景（5 个测试）

| 场景 | 验证 |
|------|------|
| U2A → A2T 多跳会话 | 两跳均验证通过，behavior API 返回正确数据 |
| 行为轨迹排序 | 按 hop_count 排序 |
| 身份伪造端到端 | 检测到恶意 |
| 同 DID 重复端到端 | same_did_duplicate |
| 严重度递增 | 4 次违规后 severity 升至 dangerous/banned |

## 测试数据构造说明

### 密钥对

每个测试会话独立生成密钥对：

| Fixture | 密钥类型 | 代表节点 |
|---------|---------|---------|
| `agent_keys` | secp256k1 | Agent 节点 |
| `tool_keys` | P-256 | Tool 节点 |
| `user_keys` | secp256k1 | User 节点 |

> DID 解析器仅支持 EC 和 Ed25519 密钥提取，不支持 RSA。因此测试中所有节点均使用 EC 密钥。

### BackMessage 构造

集成测试中的 `_make_signed_bp` 辅助函数处理两个关键点：

1. **身份签名与内容签名使用不同密钥**：`private_key` 签名身份（回传节点），`content_key` 签名内容（原始发送者）
2. **共享 sig_content**：两条 BackMessage 必须携带完全相同的 `sig_content` 字节（通过 `content_sig` 参数传入预计算的签名值）

```python
# 构造共享的内容签名
sig = _content_sig(sender_priv, session_id, sender_did, target_did, hc=[0, 0])

# BP1（发送方回传）
bp1 = _make_signed_bp(node_did=SENDER_DID, ..., private_key=sender_priv, content_sig=sig)

# BP2（接收方回传）— 共享相同的 sig
bp2 = _make_signed_bp(node_did=RECEIVER_DID, ..., private_key=receiver_priv, content_sig=sig)
```

### 时间戳

集成测试使用固定时间戳 `FIXED_TS = 1000000.0`，确保内容哈希计算与签名一致。`_content_sig` 和 `_make_signed_bp` 必须使用相同的时间戳值。

## 已知限制

以下功能暂未覆盖，后续补充：

| 模块 | 说明 |
|------|------|
| `ChainManager.validate_hop()` | 字段完整性、类型、超时校验 |
| `ChainManager.verify_back_propagation()` | 集成测试间接覆盖，缺独立单元测试 |
| `_periodic_sweep` | 后台过期消息清理和单次回传评估 |
| `AnalysisOrchestrator` | LLM 驱动的语义分析（需 mock LLM） |
| `ProtocolNode` 生命周期 | start/stop/reload_config |
| CLI 命令 | init-config / start |
| DID 真实网络解析 | 当前全部 mock |
| SqliteStore 错误处理 | 数据库异常路径 |
