# ATTP Protocol Node 代码与功能分析

> 本文档对 `python/attp/protocol_node/` 目录下的所有模块进行全面的代码结构与功能分析，重点聚焦于**消息追踪层**和**污点分析层**。

## 目录

- [ATTP Protocol Node 代码与功能分析](#attp-protocol-node-代码与功能分析)
  - [目录](#目录)
  - [1. 概述](#1-概述)
  - [2. 模块架构总览](#2-模块架构总览)
    - [模块依赖关系](#模块依赖关系)
    - [启动流程](#启动流程)
  - [3. 消息追踪层](#3-消息追踪层)
    - [3.1 统一端口与 Record 接收入口](#31-统一端口与-record-接收入口)
      - [3.1.1 ProtocolPort（`ports/protocol_port.py`）](#311-protocolportportsprotocol_portpy)
      - [3.1.2 Record 接收路由（`api/record.py`）](#312-record-接收路由apirecordpy)
    - [3.2 消息拦截验证管道（middleware）](#32-消息拦截验证管道middleware)
      - [3.2.1 InterceptResult — 拦截结果](#321-interceptresult--拦截结果)
      - [3.2.2 行为类型映射](#322-行为类型映射)
      - [3.2.3 验证管线 — intercept\_record()](#323-验证管线--intercept_record)
      - [3.2.4 Branch A vs Branch B 对比](#324-branch-a-vs-branch-b-对比)
      - [3.2.5 过期 PendingMessage 处理](#325-过期-pendingmessage-处理)
    - [3.3 恶意节点判定引擎（malicious\_detector）](#33-恶意节点判定引擎malicious_detector)
      - [3.3.1 证据类型](#331-证据类型)
      - [3.3.2 MaliciousNodeReport — 恶意检测报告](#332-maliciousnodereport--恶意检测报告)
      - [3.3.3 双回传判定决策树（evaluate\_dual\_back\_prop）](#333-双回传判定决策树evaluate_dual_back_prop)
      - [3.3.4 单回传判定决策树（evaluate\_single\_back\_prop）](#334-单回传判定决策树evaluate_single_back_prop)
      - [3.3.5 辅助方法](#335-辅助方法)
    - [3.4 恶意节点查询 API（malicious）](#34-恶意节点查询-apimalicious)
      - [3.4.1 DID 规范化（`_normalise_did`）](#341-did-规范化_normalise_did)
      - [3.4.2 端点说明](#342-端点说明)
    - [3.5 行为溯源查询 API（trace）](#35-行为溯源查询-apitrace)
    - [3.6 行为记录分发（behavior\_controller）](#36-行为记录分发behavior_controller)
    - [3.7 消息追踪层完整数据流](#37-消息追踪层完整数据流)
  - [4. 污点分析层](#4-污点分析层)
    - [4.1 CrossLockCoordinator 集成与生命周期](#41-crosslockcoordinator-集成与生命周期)
      - [4.1.1 构建条件](#411-构建条件)
      - [4.1.2 注入路径](#412-注入路径)
      - [4.1.3 配置模型](#413-配置模型)
      - [4.1.4 热重载](#414-热重载)
    - [4.2 U2A 意图提取触发](#42-u2a-意图提取触发)
    - [4.3 纵轴批次化分析调度](#43-纵轴批次化分析调度)
    - [4.4 横轴累积触发](#44-横轴累积触发)
    - [4.5 纵向分析 API 端点](#45-纵向分析-api-端点)
      - [4.5.1 纵向分析报告查询](#451-纵向分析报告查询)
      - [4.5.2 意图状态查询](#452-意图状态查询)
      - [4.5.3 聚合查询（traces + reports + alerts）](#453-聚合查询traces--reports--alerts)
      - [4.5.4 手动触发纵向分析](#454-手动触发纵向分析)
      - [4.5.5 纵向分析任务状态](#455-纵向分析任务状态)
    - [4.6 横向分析 API 端点](#46-横向分析-api-端点)
      - [4.6.1 DID 横向分析报告](#461-did-横向分析报告)
      - [4.6.2 DID 横向累积状态](#462-did-横向累积状态)
      - [4.6.3 横向分析任务状态](#463-横向分析任务状态)
      - [4.6.4 手动触发横向分析](#464-手动触发横向分析)
      - [4.6.5 横向分析总览](#465-横向分析总览)
  - [5. 配置模型与热重载](#5-配置模型与热重载)
    - [5.1 配置模型层级](#51-配置模型层级)
    - [5.2 配置加载](#52-配置加载)
    - [5.3 热重载](#53-热重载)
  - [6. CLI 命令行接口](#6-cli-命令行接口)
  - [7. 错误码体系](#7-错误码体系)
  - [8. API 端点汇总](#8-api-端点汇总)
    - [8.1 Record 接收](#81-record-接收)
    - [8.2 行为溯源](#82-行为溯源)
    - [8.3 纵向分析](#83-纵向分析)
    - [8.4 横向分析](#84-横向分析)
    - [8.5 恶意节点查询](#85-恶意节点查询)
  - [9. 设计模式与总结](#9-设计模式与总结)
    - [9.1 设计模式](#91-设计模式)
    - [9.2 架构特点](#92-架构特点)
    - [9.3 与 Core 层的关系](#93-与-core-层的关系)

---

## 1. 概述

Protocol Node（协议节点/溯源节点）是 ATTP（Agents Traceability and Trust Protocol）协议的**独立溯源服务节点**，承载了 ATTP 四层架构中的两层核心逻辑：

| 协议层 | Protocol Node 对应模块 | 说明 |
|--------|----------------------|------|
| **消息追踪层** | `engine/middleware.py`、`engine/malicious_detector.py`、`api/record.py`、`api/malicious.py`、`api/trace.py` | 接收双轮回溯消息、身份验证、内容一致性校验、恶意节点判定、行为溯源查询 |
| **污点分析层** | `CrossLockCoordinator`（core 层）集成、`api/analysis/vertical.py`、`api/analysis/horizontal.py` | 十字锁定污点分析：纵轴（Session-Level）+ 横轴（DID-Level）LLM 驱动的语义检测 |

Protocol Node 的核心职责：

| 能力 | 说明 |
|------|------|
| 双轮回溯确认 | 接收通信双方的 BackMessage，通过 nonce 匹配实现不可否认性验证 |
| 恶意节点检测 | 基于决策树的自动恶意判定（身份篡改、内容篡改、可信名单违规等 7 种证据类型） |
| 行为溯源存储 | 将验证通过的行为记录持久化到 SQLite，支持按 session 查询完整行为链 |
| 语义污点分析 | 可选集成十字锁定分析引擎（纵轴+横轴），对行为链进行意图对齐和全局行为检测 |
| 恶意节点档案 | 累计恶意行为记录（统一协议审查/纵向/横向三个来源），维护节点严重等级（clean → warning → dangerous → banned） |

---

## 2. 模块架构总览

```
protocol_node/
├── __init__.py                      # 模块声明，导出 ProtocolNode
├── node.py                          # ProtocolNode 主类 — 生命周期管理
├── cli.py                           # CLI 入口 — start / init-config
│
├── config/
│   ├── __init__.py
│   └── config.py                    # ProtocolNodeConfigFile — Pydantic 配置模型
│
├── engine/
│   ├── __init__.py
│   ├── middleware.py                 # 消息拦截中间件 — 验证管道核心
│   ├── malicious_detector.py         # 恶意节点判定引擎 — 双回传/单回传决策树
│   └── behavior_controller.py        # 行为记录分发控制器
│
├── ports/
│   ├── __init__.py
│   └── protocol_port.py             # 统一端口 — FastAPI + uvicorn
│
└── api/
    ├── __init__.py
    ├── record.py                    # /record 接收路由 — 双轮回溯确认入口
    ├── trace.py                     # /api/* 溯源查询路由
    ├── malicious.py                 # /api/malicious/* 恶意节点查询路由（统一格式）
    └── analysis/                    # 污点分析 API 子路由
        ├── __init__.py
        ├── vertical.py              # /api/analysis/* 纵向分析路由
        └── horizontal.py            # /api/horizontal/* 横向分析路由
```

### 模块依赖关系

```
ProtocolNode (node.py)
  │
  ├── ProtocolNodeConfigFile (config/config.py)
  │     ├── PNWebConfig          — 网络（host/port）
  │     ├── StorageConfig        — 数据目录 + DB 路径
  │     └── AnalysisConfig       — LLM 分析配置
  │
  ├── ProtocolTracer (core/pn_tracer.py)
  │     ├── KeyStore             — 密钥缓存
  │     ├── ChainManager         — 溯源链管理
  │     └── SqliteStore          — 异步 SQLite 存储
  │
  ├── ProtocolSessionManager (core/sessions/protocol_node/)
  │     └── ProtocolSession      — per-session 验证状态 + 分析状态
  │
  ├── DIDResolver (core/authentication/did_resolver.py)
  │     └── KeyStore             — 公钥缓存
  │
  ├── BehaviorController (engine/behavior_controller.py)
  │
  ├── MaliciousNodeDetector (engine/malicious_detector.py)
  │     └── DIDResolver
  │
  ├── ProtocolPort (ports/protocol_port.py)
  │     ├── FastAPI + uvicorn
  │     │
  │     ├── record router (api/record.py)
  │     │     └── middleware.intercept_record()  — 验证管道
  │     │
  │     ├── behavior router (api/trace.py)
  │     │     └── ProtocolTracer — 行为溯源查询
  │     │
  │     ├── analysis sub-routers (api/analysis/)
  │     │     ├── vertical.py   — 纵向分析 API
  │     │     └── horizontal.py — 横向分析 API
  │     │
  │     └── malicious router (api/malicious.py)
  │           └── ProtocolTracer — 恶意节点查询（统一格式，支持 source 筛选）
  │
  └── CrossLockCoordinator (core/analysis/cross_lock.py) [可选]
        ├── VerticalOrchestrator — 纵向分析编排
        │     ├── VerticalTaintAnalyzer — LLM 纵向污点分析
        │     ├── VerticalAnalysisManager — 纵向状态管理
        │     └── ProtocolTracer
        └── HorizontalOrchestrator [可选] — 横向分析编排
              ├── HorizontalTaintAnalyzer — LLM 横向污点分析
              ├── HorizontalAnalysisManager — 横向状态管理
              └── ProtocolTracer
```

### 启动流程

```
ProtocolNode.__init__(config_path)
  │  同步加载配置
  │
  └── ProtocolNode.start()
       │
       ├── 1. ProtocolTracer.create(db_path)          → 初始化溯源链 + SQLite
       ├── 2. ProtocolSessionManager(storage)          → 会话管理（带持久化）
       ├── 3. DIDResolver(key_store)                   → DID 文档解析器
       ├── 4. BehaviorController()                     → 行为分发
       ├── 5. MaliciousNodeDetector(did_resolver)      → 恶意检测
       ├── 6. ProtocolPort(tracer, session_manager,     → 统一端口
       │     host, port, did_resolver, behavior_controller,
       │     malicious_detector)
       ├── 7. _build_orchestrator() [可选]             → CrossLockCoordinator（纵轴 + 横轴）
       │     ├── VerticalOrchestrator + VerticalAnalysisManager
       │     ├── HorizontalOrchestrator + HorizontalAnalysisManager [可选]
       │     └── CrossLockCoordinator 串联两轴
       │     └── port.set_orchestrator(coordinator)
       │     └── 挂载 vertical / horizontal 分析子路由
       ├── 8. port.start()                             → uvicorn 启动
       └── 9. _periodic_sweep() Task                   → 过期 PendingMessage 扫描
```

---

## 3. 消息追踪层

消息追踪层是 Protocol Node 的核心，实现了 ATTP 协议的双轮回溯确认机制、恶意节点自动检测和行为溯源存储。

### 3.1 统一端口与 Record 接收入口

#### 3.1.1 ProtocolPort（`ports/protocol_port.py`）

Protocol Node 采用**单端口架构**，合并了原来的 DataPort（`/record`）和 ApiPort（`/api/*`），通过一个 FastAPI 应用统一对外服务。

```python
class ProtocolPort:
    def __init__(
        self,
        tracer: ProtocolTracer,
        session_manager: ProtocolSessionManager,
        host: str,
        port: int,
        did_resolver,
        behavior_controller,
        malicious_detector,
    )
```

**路由挂载**：

```
ProtocolPort._mount_routes()
  │
  ├── /record                    → record router (api/record.py)
  │     └── POST /record         — 接收 BackMessage
  │
  ├── /api                       → behavior router (api/trace.py)
  │     ├── GET  /api/status                  — 健康检查
  │     └── GET  /api/behavior/{session_id}   — 行为溯源链
  │
  ├── /api/analysis              → vertical analysis router (api/analysis/vertical.py)
  │     ├── GET  /api/analysis/{session_id}   — 纵向分析报告
  │     ├── GET  /api/analysis/v/state/{session_id}      — 意图与累计状态
  │     ├── GET  /api/analysis/aggregate/{session_id} — 聚合查询（traces+reports+alerts）
  │     ├── POST /api/analysis/trigger/{session_id}  — 手动触发纵向分析
  │     └── GET  /api/analysis/v/llm-status/{session_id}  — 纵向LLM分析任务状态
  │
  ├── /api/horizontal            → horizontal analysis router (api/analysis/horizontal.py)
  │     ├── GET  /api/horizontal/report/{did}         — DID 横向分析报告
  │     ├── GET  /api/horizontal/state/{did}           — DID 横向累积状态
  │     ├── GET  /api/horizontal/status/{did}          — 横向分析任务状态
  │     ├── POST /api/horizontal/trigger/{did}         — 手动触发横向分析
  │     └── GET  /api/horizontal/overview              — 横向分析总览
  │
  └── /api/malicious             → malicious router (api/malicious.py)
        ├── GET  /api/malicious/session/{session_id}?source=...  — 按 session 查询
        ├── GET  /api/malicious/did/{did}?source=...             — 按 DID 查询
        ├── GET  /api/malicious/dossier/{did}         — 单个档案
        └── GET  /api/malicious/dossiers              — 全部档案
```

**CrossLockCoordinator Late-Binding**：

由于 Coordinator 在 `start()` 后可能被动态注入或替换（热重载），ProtocolPort 使用**可变列表** `[None]` 作为 holder 实现延迟绑定：

```python
self._orch_holder: list = [None]  # 长度为 1 的可变列表

def set_orchestrator(self, coordinator) -> None:
    self._orch_holder[0] = coordinator  # 所有路由通过 _orch_holder[0] 访问（CrossLockCoordinator 实例）
```

**生命周期**：

| 方法 | 行为 |
|------|------|
| `start()` | 创建 `uvicorn.Server` 并作为 `asyncio.Task` 后台运行 |
| `stop()` | 设置 `should_exit=True`，等待 5 秒后取消 Task |

#### 3.1.2 Record 接收路由（`api/record.py`）

`POST /record` 是整个消息追踪层的**唯一写入入口**，接收来自 Agent/Tool/User 的 BackMessage。

**处理流程**：

```
POST /record
  │
  ├── 1. 解析 JSON body → BackMessage.from_dict(body)
  │     失败 → 400 "Invalid BackMessage"
  │
  ├── 2. 调用 middleware.intercept_record(back_msg, ...)
  │     │
  │     ├── status == "error"     → ERROR_MAP 映射 → 对应 HTTP 错误码
  │     ├── status == "stored"    → 200 {"status": "stored", "nonce", "session_id"}
  │     ├── status == "malicious" → 403 {"status": "malicious_detected", ...}
  │     └── status == "verified"  → 继续后续处理
  │
  ├── 3. [verified] 保存行为记录
  │     tracer.save_behavior_entry(session_id, pna, sender_did, target_did, ...)
  │
  ├── 4. [verified] 行为分发
  │     behavior_controller.handle(node_type, body, result)
  │
  ├── 5. [verified] U2A 意图提取（hop_count=[0,0] 时）
  │     orchestrator.on_field_U2A_recorded(session_id, content)
  │
  ├── 6. [verified] 批次计数递增
  │     orchestrator.on_record_received(session_id)
  │
  └── 7. 返回 200 {"status": "Record verified and saved"}
```

### 3.2 消息拦截验证管道（middleware）

`engine/middleware.py` 是消息追踪层的**核心验证逻辑**，实现了完整的 7 步验证管线。

#### 3.2.1 InterceptResult — 拦截结果

```python
@dataclass
class InterceptResult:
    status: str             # "stored" / "verified" / "error" / "malicious"
    node_type: str | None
    error: str | None
    sender_did: str | None
    target_did: str | None = None
    behavior_type: str | None = None
    stored_msg: Any = None  # Branch B 时携带的 PendingMessage
    malicious_report: MaliciousNodeReport | None = None
```

#### 3.2.2 行为类型映射

5 种合法的 `(sender_node_type, receiver_node_type)` → `field_type` 组合：

```python
BEHAVIOR_TYPE_MAP = {
    ("agent", "tool"):   "A2T",   # Agent → Tool
    ("agent", "user"):   "A2U",   # Agent → User
    ("user", "agent"):   "U2A",   # User → Agent
    ("agent", "agent"):  "A2A",   # Agent → Agent
    ("tool", "agent"):   "T2A",   # Tool → Agent
}
```

#### 3.2.3 验证管线 — intercept_record()

完整的 7 步验证管线：

```
intercept_record(back_msg, did_resolver, tracer, session_manager, malicious_detector)
  │
  ╔══════════════════════════════════════════════════════════════════╗
  ║  Step 1: 基础字段验证                                           ║
  ║  _validate_back_message(back_msg)                               ║
  ║  检查: node_did, nonce, sig_identity 非空                       ║
  ║  检查: session_id, sender_did, target_did 非空                  ║
  ║  检查: hop_count 为 [a2a, intra] 二元组且 >= 0                  ║
  ║  检查: timestamp > 0, sig_content 非空                          ║
  ╚══════════════════════════════════════════════════════════════════╝
  │
  ╔══════════════════════════════════════════════════════════════════╗
  ║  Step 2: DID 解析 + 节点类型校验                                 ║
  ║  did_resolver.resolve_full(node_did)                            ║
  ║  → 提取公钥 + 节点类型 (agent/tool/user)                         ║
  ║  → 缓存公钥到 key_store                                         ║
  ╚══════════════════════════════════════════════════════════════════╝
  │
  ╔══════════════════════════════════════════════════════════════════╗
  ║  Step 3: Nonce 会话分支                                          ║
  ║  session = session_manager.get_or_create(session_id)            ║
  ║  扫描过期 PendingMessage（_sweep_expired_pending）               ║
  ║  stored_msg = session.get_pending_message(nonce)                ║
  ╚══════════════════════════════════════════════════════════════════╝
  │
  ├── stored_msg is None → Branch A（回传 1 先到达）
  │     │
  │     ├── 验证身份签名: back_msg.verify_identity(public_key)
  │     ├── 构造 PendingMessage（含 identity_verified 结果）
  │     ├── session.store_pending_message(nonce, pending)
  │     ├── session_manager.save(session)
  │     └── 返回 InterceptResult(status="stored")
  │
  └── stored_msg exists → Branch B（回传 2 后到达）
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 4: 恶意节点判定引擎                                  ║
        ║  malicious_detector.evaluate_dual_back_prop(               ║
        ║      stored_msg, back_msg, session                         ║
        ║  )                                                         ║
        ║  → 检测到恶意 → 返回 status="malicious"                     ║
        ╚════════════════════════════════════════════════════════════╝
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 5: 内容一致性验证（回传验证）                          ║
        ║  tracer.verify_back_propagation(stored_hop, prev_hop)      ║
        ║  → 三步验证: 签名验证 → 字节比对 → 哈希一致性               ║
        ╚════════════════════════════════════════════════════════════╝
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 6: 行为类型推断 + hop_count 校验                      ║
        ║  behavior_type = BEHAVIOR_TYPE_MAP[(sender_type, recv_type)]║
        ║  hop_count=[0,0] 必须为 U2A                                 ║
        ║  A2A: a2a_count 必须等于 max_a2a + 1, intra 必须为 0        ║
        ║  non-A2A: a2a_count 不超过 max_a2a, intra 必须递增          ║
        ╚════════════════════════════════════════════════════════════╝
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 7: 验证通过 → 更新可信名单                             ║
        ║  session.complete_verification(nonce, hop_count, trusted_did)║
        ║  session_manager.save(session)                              ║
        ╚════════════════════════════════════════════════════════════╝
        │
        └── 返回 InterceptResult(status="verified", behavior_type, stored_msg)
```

#### 3.2.4 Branch A vs Branch B 对比

| 阶段 | Branch A（回传 1 先到） | Branch B（回传 2 后到） |
|------|----------------------|----------------------|
| 触发条件 | `session.get_pending_message(nonce)` 返回 `None` | 已有同一 nonce 的 PendingMessage |
| 身份验证 | `back_msg.verify_identity(public_key)` → 结果存入 `identity_verified` | 由恶意检测器内部处理 |
| 存储行为 | 构造 `PendingMessage` 并暂存到 session | 移除 PendingMessage |
| 后续动作 | 等待回传 2 到达 | 恶意检测 → 回传验证 → 行为推断 → 更新可信名单 |
| 返回状态 | `"stored"` | `"verified"` / `"malicious"` / `"error"` |

#### 3.2.5 过期 PendingMessage 处理

PendingMessage 默认 TTL 为 300 秒。过期消息通过两种途径清理：

1. **实时清理**（`_sweep_expired_pending`）：在每次 `intercept_record()` 的 nonce 查找前触发
2. **周期清理**（`ProtocolNode._periodic_sweep`）：每 60 秒扫描所有 session 的过期消息

过期消息会被送入 `MaliciousNodeDetector.evaluate_single_back_prop()` 进行单回传恶意判定。

### 3.3 恶意节点判定引擎（malicious_detector）

`engine/malicious_detector.py` 实现了 ATTP 协议的**恶意节点自动检测机制**，覆盖双回传和单回传两种场景。

#### 3.3.1 证据类型

```python
class EvidenceType(Enum):
    IDENTITY_TAMPERING = "identity_tampering"          # 身份篡改
    TRUSTED_LIST_VIOLATION = "trusted_list_violation"  # 可信名单违规
    CONTENT_TAMPERING = "content_tampering"            # 内容篡改
    NO_PROPAGATION = "no_propagation"                  # 未传播（接收但不回传）
    FRAMING = "framing"                                # 栽赃
    INDISTINGUISHABLE_PAIR = "indistinguishable_pair"  # 不可区分对
    SAME_DID_DUPLICATE = "same_did_duplicate"          # 相同 DID 重复回传
```

#### 3.3.2 MaliciousNodeReport — 恶意检测报告

```python
@dataclass
class MaliciousNodeReport:
    malicious_dids: list[str]              # 恶意节点 DID 列表
    evidence_type: EvidenceType            # 证据类型
    evidence_description: str              # 证据描述
    session_id: str                        # 会话 ID
    nonce: str                             # 关联 nonce
    timestamp: float                       # 检测时间
    raw_evidence: dict                     # 原始证据数据
```

#### 3.3.3 双回传判定决策树（evaluate_dual_back_prop）

当同一 nonce 收到两条 BackMessage 时触发双回传判定。完整的决策树（Step 0a → 4b）：

```
evaluate_dual_back_prop(stored_msg, back_msg_2, session)
  │
  │  输入:
  │    stored_msg  = 回传1（先到达，已暂存为 PendingMessage）
  │    back_msg_2  = 回传2（后到达，当前消息）
  │    session     = ProtocolSession（含可信名单）
  │
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 0a: 回传1 身份签名检查                                       ║
  ║  stored_msg.identity_verified == False?                           ║
  ║                                                                    ║
  ║  → 是: IDENTITY_TAMPERING                                         ║
  ║    - 有可信名单: 通报可信名单中所有节点                               ║
  ║    - 无可信名单: 报告回传1的 node_did                               ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 0b: 回传1 可信名单校验                                       ║
  ║  bp1_did ∉ trusted_list?                                          ║
  ║                                                                    ║
  ║  → 是: TRUSTED_LIST_VIOLATION                                     ║
  ║    通报可信名单中所有节点                                           ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 1: 回传2 身份签名检查                                        ║
  ║  did_resolver.resolve_full(bp2_did) → 公钥                        ║
  ║  back_msg_2.verify_identity(public_key)?                          ║
  ║                                                                    ║
  ║  → 公钥为 None: IDENTITY_TAMPERING                                ║
  ║    判定回传1的 target_did 为恶意                                    ║
  ║  → 签名验证失败: IDENTITY_TAMPERING                                ║
  ║    判定回传1的 target_did 为恶意                                    ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 2: DID 比对                                                 ║
  ║  bp1_did == bp2_did?                                              ║
  ║                                                                    ║
  ║  → 是: SAME_DID_DUPLICATE                                        ║
  ║    两条回传来自同一 DID，该节点为恶意                                ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过（两条回传来自不同节点）
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 3: 回传1 内容签名自检                                        ║
  ║  解析回传1发送者 DID → 公钥                                        ║
  ║  验证回传1的内容签名                                                ║
  ║                                                                    ║
  ║  → DID 解析失败: CONTENT_TAMPERING                                ║
  ║  → 签名验证失败: CONTENT_TAMPERING                                ║
  ║    回传1节点为恶意                                                  ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 4: 回传2 内容签名交叉验证                                     ║
  ║  用回传1发送者的公钥验证回传2的内容签名                              ║
  ║                                                                    ║
  ║  → 交叉验证失败: INDISTINGUISHABLE_PAIR                           ║
  ║    无法区分是发送方伪造还是接收方篡改，两节点一起通报                  ║
  ║  → 交叉验证成功: 进入 Step 4b                                       ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 交叉验证成功
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 4b: 发送方双签（栽赃）检测                                    ║
  ║  比对两条回传的 sig_content 是否一致                                 ║
  ║                                                                    ║
  ║  → 不一致: FRAMING                                                ║
  ║    两条签名均在发送方公钥下有效却互不相同，仅发送方私钥持有者可做到， ║
  ║    说明发送方分别向协议节点与接收方各签了一份不同内容 ⇒ 发送方恶意   ║
  ║  → 一致: return None（无恶意，双回传验证通过）                       ║
  ╚════════════════════════════════════════════════════════════════════╝
```

#### 3.3.4 单回传判定决策树（evaluate_single_back_prop）

当 PendingMessage 过期（TTL 300 秒）但仅收到一条回传时触发单回传判定。

```
evaluate_single_back_prop(pending_msg, session)
  │
  │  输入:
  │    pending_msg = 唯一的回传消息
  │    session     = ProtocolSession
  │
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Case A: 身份签名验证失败 → 直接丢弃                               ║
  ║  pending_msg.identity_verified == False?                          ║
  ║                                                                    ║
  ║  → return None（不通报任何节点）                                   ║
  ║    无主垃圾消息：既未对特定方注入、也非针对具体节点的栽赃，         ║
  ║    按威胁模型原则不予追究；同时杜绝恶意节点借单回传对可信名单       ║
  ║    发起广播栽赃洪流（反例 C1）                                     ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Case B: DID 不在可信名单中                                        ║
  ║  node_did ∉ trusted_list?                                         ║
  ║                                                                    ║
  ║  → TRUSTED_LIST_VIOLATION, 通报可信名单                            ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Case C: 身份验证通过且 DID 在可信名单中                            ║
  ║  has_subsequent = session.has_subsequent_activity_after(nonce)    ║
  ║                                                                    ║
  ║  → 有后续活动 + 有不同身份:                                        ║
  ║    NO_PROPAGATION — 节点接收了但未回传，target_did 为恶意            ║
  ║                                                                    ║
  ║  → 有后续活动 + 无不同身份:                                        ║
  ║    return None — 视为恶意节点自发自弃，不予记录                      ║
  ║                                                                    ║
  ║  → 无后续活动:                                                    ║
  ║    return None — 视为垃圾消息抛弃                                   ║
  ╚════════════════════════════════════════════════════════════════════╝
```

#### 3.3.5 辅助方法

| 方法 | 功能 |
|------|------|
| `_compute_recorded_hop_content_hash(hop)` | 从 hop dict 计算 SHA-256 内容哈希（与 `RecordedHop.content_hash()` 逻辑一致） |
| `_verify_content_sig(content_hash, sig_content, public_key)` | 验证内容签名，调用 `core/authentication/signatures.py` 的 `verify_signature()` |

### 3.4 恶意节点查询 API（malicious）

`api/malicious.py` 提供 4 个恶意节点查询端点。

#### 3.4.1 DID 规范化（`_normalise_did`）

FastAPI 会自动 URL-decode 路径参数，导致 `localhost%3A8000` 变为 `localhost:8000`。`_normalise_did()` 负责将解码后的 DID 还原为数据库中存储的 canonical form：

```
did:wba:localhost:8000:path:segment
→ did:wba:localhost%3A8000:path:segment
```

规则：如果 `did:wba:` 后的第 4 段是纯数字（端口号），则将其合并到 domain 并用 `%3A` 编码。

#### 3.4.2 端点说明

所有恶意报告端点现在使用**统一格式**（`malicious_reports` 表），支持 `?source=` 查询参数筛选来源。

**统一报告格式**（`_format_report`）：

```json
{
  "id": 1,
  "source": "protocol_review",
  "target_did": "did:wba:...",
  "node_type": "agent",
  "session_id": "...",
  "evidence_type": "identity_tampering",
  "severity": "high",
  "taint_score": 0.85,
  "evidence_description": "...",
  "nonce": "...",
  "report_id": null,
  "timestamp": 1234567890.0,
  "raw_evidence": {...}
}
```

| `source` 值 | 说明 |
|-------------|------|
| `protocol_review` | 双轮回溯确认中由 `MaliciousNodeDetector` 检测到 |
| `vertical_analysis` | 纵向语义污点分析中由 `VerticalOrchestrator` 检测到 |
| `horizontal_analysis` | 横向行为分析中由 `HorizontalOrchestrator` 检测到 |

**按 session 查询**：

```
GET /api/malicious/session/{session_id}?source=vertical_analysis
→ {
    "session_id": "...",
    "reports": [_format_report(...)],
    "total": 1
  }
```

**按 DID 查询**：

```
GET /api/malicious/did/{did}?source=horizontal_analysis
→ {
    "target_did": "...",
    "reports": [_format_report(...)],
    "total": N
  }
```

**单个节点档案（dossier）**：

```
GET /api/malicious/dossier/{did}
→ {
    "found": true,
    "did": "...",
    "total_violations": 3,
    "severity_level": "warning",       // clean/warning/dangerous/banned
    "first_seen_at": 1234567890.0,
    "last_seen_at": 1234567900.0,
    "evidence_breakdown": {...},        // 各类违规计数
    "last_evidence_type": "...",
    "last_session_id": "...",
    "last_evidence_desc": "...",
    "incidents": [...]                  // 完整违规明细
  }
```

**全部档案**：

```
GET /api/malicious/dossiers?severity=warning&limit=100
→ {
    "total": 5,
    "dossiers": [...]
  }
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `severity` | query, 可选 | 按严重等级筛选（clean/warning/dangerous/banned） |
| `limit` | query, 默认 100 | 返回数量限制（1-1000） |

### 3.5 行为溯源查询 API（trace）

`api/trace.py` 提供行为溯源链查询功能。

**行为溯源链**：

```
GET /api/behavior/{session_id}?protocol_node_address=...
→ {
    "session_id": "...",
    "protocol_node_address": "...",
    "chain": [
      {
        "hop_count": [0, 0],
        "field_type": "U2A",
        "sender_type": "user",           // U→user, A→agent, T→tool
        "sender_did": "did:wba:...",
        "target_did": "did:wba:...",
        "content": "...",
        "timestamp": 1234567890.0
      }
    ]
  }
```

发送者类型映射（`_SENDER_TYPE_MAP`）：

| field_type 首字母 | sender_type |
|-------------------|-------------|
| `A` | `agent` |
| `U` | `user` |
| `T` | `tool` |

### 3.6 行为记录分发（behavior_controller）

`engine/behavior_controller.py` 是一个简单的**策略分发器**，根据 `node_type` 将已验证的行为记录路由到对应处理器。

```python
class BehaviorController:
    async def handle(self, node_type, body, intercept_result, stored_msg=None) -> dict:
        handler = {
            "agent": self._handle_agent,
            "tool": self._handle_tool,
            "user": self._handle_user,
        }.get(node_type, self._handle_unknown)
        return await handler(body, intercept_result, stored_msg)
```

当前三个处理器均返回确认信息，**预留后续扩展**：

| 处理器 | 返回 |
|--------|------|
| `_handle_agent` | `{"status": "ok", "routed_to": "agent"}` |
| `_handle_tool` | `{"status": "ok", "routed_to": "tool"}` |
| `_handle_user` | `{"status": "ok", "routed_to": "user"}` |
| `_handle_unknown` | 记录 warning 日志，返回 `{"status": "ok", "routed_to": "unknown"}` |

### 3.7 消息追踪层完整数据流

```
  Agent A (发送方)              Agent B (接收方)              Protocol Node
      │                             │                            │
      │  ① NodeMessage              │                            │
      │  (A 签名 content)            │                            │
      ├────────────────────────────→│                            │
      │                             │                            │
      │                             │  ② BackMessage Phase 1     │
      │                             │  (B 签名 identity +        │
      │                             │   携带 A 的签名内容)        │
      │                             ├───────────────────────────→│
      │                             │                            │
      │                             │                     Branch A:│
      │                             │                     Step 1: 基础验证│
      │                             │                     Step 2: DID解析│
      │                             │                     Step 3: nonce查找│
      │                             │                       → 无暂存消息│
      │                             │                     验证B身份签名│
      │                             │                     暂存为 PendingMessage│
      │                             │                     返回 "stored"│
      │                             │                            │
      │  ③ BackMessage Phase 2      │                            │
      │  (A 签名 identity +         │                            │
      │   发送内容副本)               │                            │
      ├─────────────────────────────────────────────────────────→│
      │                             │                            │
      │                             │                     Branch B:│
      │                             │                     Step 1: 基础验证│
      │                             │                     Step 2: DID解析│
      │                             │                     Step 3: nonce查找│
      │                             │                       → 匹配到暂存│
      │                             │                            │
      │                             │                     Step 4: 恶意节点判定│
      │                             │                       0a: 回传1身份检查│
      │                             │                       0b: 可信名单校验│
      │                             │                       1: 回传2身份检查│
      │                             │                       2: DID比对│
      │                             │                       3: 回传1内容自检│
      │                             │                       4: 交叉验证│
      │                             │                       4b: 发送方双签检测│
      │                             │                            │
      │                             │                  [检测到恶意]│
      │                             │                  → 保存恶意报告│
      │                             │                  → 返回 403  │
      │                             │                            │
      │                             │                  [无恶意]    │
      │                             │                     Step 5: 回传验证│
      │                             │                     verify_back_propagation│
      │                             │                     Step 6: 行为推断│
      │                             │                     hop_count校验│
      │                             │                     Step 7: 更新可信名单│
      │                             │                            │
      │                             │                  保存 behavior_entry│
      │                             │                  行为分发 → controller│
      │                             │                  [可选] 意图提取/批次计数│
      │                             │                  返回 200   │
```

---

## 4. 污点分析层

污点分析层采用**十字锁定（Cross-Lock）架构**，通过可选集成的 `CrossLockCoordinator` 实现 LLM 驱动的语义污点检测。纵轴在消息追踪层验证通过后自动触发，横轴在纵轴完成后通过累积计数器自动触发。

### 4.1 CrossLockCoordinator 集成与生命周期

#### 4.1.1 构建条件

```python
def _build_orchestrator(self):
    analysis_cfg = self._config.analysis
    if not analysis_cfg.enabled or not analysis_cfg.api_key:
        return None  # 未启用或未配置 API Key
    # 构建 VerticalOrchestrator
    # 如果配置了 accumulation_threshold > 0，同时构建 HorizontalOrchestrator
    # 用 CrossLockCoordinator 串联两轴
```

Coordinator 仅在以下条件同时满足时创建：

| 条件 | 配置字段 | 默认值 |
|------|---------|--------|
| 启用分析 | `analysis.enabled` | `false` |
| 配置 API Key | `analysis.api_key` | `""` |

横轴（HorizontalOrchestrator）额外条件：

| 条件 | 配置字段 | 默认值 |
|------|---------|--------|
| 累积阈值 > 0 | `analysis.accumulation_threshold` | `5` |

#### 4.1.2 注入路径

```
ProtocolNode.start()
  │
  ├── _build_orchestrator() → CrossLockCoordinator
  │     ├── VerticalOrchestrator + VerticalAnalysisManager
  │     ├── HorizontalOrchestrator + HorizontalAnalysisManager [可选]
  │     └── CrossLockCoordinator(vertical, horizontal)
  └── port.set_orchestrator(coordinator)
        │
        └── self._orch_holder[0] = coordinator
              │
              ├── record.py 通过 coordinator 访问（纵向回调）
              ├── vertical.py 通过 coordinator.vertical 访问
              ├── horizontal.py 通过 coordinator.horizontal 访问
              └── Cross-Lock: 纵向完成 → 自动触发横向累积
```

#### 4.1.3 配置模型

```python
class AnalysisConfig(PNBase):
    enabled: bool = False                      # 是否启用污点分析
    api_key: str = ""                          # LLM API Key
    base_url: str = "https://api.openai.com/v1"  # API Base URL
    model: str = "gpt-4o"                      # LLM 模型名称
    report_batch_size: int = 10                # 纵向批次大小（多少条 record 触发一次纵向分析）
    accumulation_threshold: int = 5            # 横向累积阈值（多少次纵向分析后触发横向分析）
```

#### 4.1.4 热重载

```python
async def reload_config(self) -> None:
    # 重新加载配置文件
    self._config = ProtocolNodeConfigFile.load(self._config_path)
    # 重建 CrossLockCoordinator（分析配置可能变化）
    self._orchestrator = self._build_orchestrator()
    self.set_orchestrator(self._orchestrator)
```

### 4.2 U2A 意图提取触发

当收到 `hop_count=[0, 0]` 的 U2A（User → Agent）消息时，Coordinator 委托纵向编排器从用户原始输入中提取结构化意图：

```python
# record.py 中的触发逻辑
if behavior_type == "U2A" and _orch and session_id and stored.hop.get("Hop_Count") == [0, 0]:
    content = stored.hop.get("Content", "")
    await _orch.on_field_U2A_recorded(session_id, content)
```

**触发条件（全部满足）**：

| 条件 | 说明 |
|------|------|
| `behavior_type == "U2A"` | 行为类型为 User → Agent |
| `_orch is not None` | CrossLockCoordinator 已启用 |
| `hop_count == [0, 0]` | 会话的第一条消息（用户原始输入） |

**意图提取流程**：

```
CrossLockCoordinator.on_field_U2A_recorded(session_id, content)
  → VerticalOrchestrator.on_field_U2A_recorded(session_id, content)
      │
      ├── VerticalTaintAnalyzer.extract_intent(content)
      │     → LLM 调用（INTENT_EXTRACTION_PROMPT）
      │     → IntentDescriptor
      │       ├── original_task      — 用户原始输入
      │       ├── core_objective     — 核心目标（一句话）
      │       ├── constraints        — 约束条件列表
      │       ├── involved_capabilities — 涉及的能力域
      │       └── risk_level         — 风险等级 (low/medium/high)
      │
      └── VerticalAnalysisManager.set_intent() → 持久化到 Session + SQLite
```

### 4.3 纵轴批次化分析调度

每条验证通过的 record 都会递增纵向批次计数器，达到 `report_batch_size` 时自动触发纵向分析：

```python
# record.py 中的触发逻辑
if _orch and session_id:
    await _orch.on_record_received(session_id)
```

**纵向批次分析流程**：

```
CrossLockCoordinator.on_record_received(session_id)
  → VerticalOrchestrator.on_record_received(session_id)
      │
      ├── VerticalAnalysisManager.increment_report_count()
      ├── count < batch_size? → 返回，等待更多 record
      │
      └── count >= batch_size → 触发纵向分析
            │
            ├── run_analysis(session_id)
            │     │
            │     ├── 1. 检查 intent 是否已提取
            │     ├── 2. recover_traces_since(session_id, last_trace_id)
            │     │     → 从 SQLite 获取未分析的 behavior_traces
            │     ├── 3. VerticalTaintAnalyzer.analyze(traces, intent)
            │     │     → 按 5 种 field_type 的风险审查:
            │     │       A2A: 指令注入、目标替换、社工欺骗、隐蔽协作
            │     │       A2T: 越权工具调用、参数篡改、数据外泄
            │     │       A2U: 信息误导、数据投毒、认知操控
            │     │       U2A: Prompt注入、越权指令、约束绕过
            │     │       T2A: 返回值篡改、注入传播
            │     │     → VerticalTaintReport（含 analyzed_dids）
            │     │
            │     ├── 4. save_analysis_report() → SQLite（返回 report_row_id）
            │     ├── 5. 更新纵向状态（重置计数、移动游标、存储上下文）
            │     ├── 6. suspicious/malicious?
            │     │     → save_malicious_report(source="vertical_analysis")
            │     └── 7. Cross-Lock: 遍历 analyzed_dids → 触发横向累积
            │
            └── VerticalAnalysisManager.reset_report_count()
```

### 4.4 横轴累积触发

纵轴分析完成后，CrossLockCoordinator 自动为每个涉及的 DID 调用横向累积：

```
CrossLockCoordinator._on_vertical_done(did, session_id)
  → HorizontalOrchestrator.on_vertical_analysis_completed(did, session_id)
      │
      ├── HorizontalAnalysisManager.increment_accumulation(did)
      ├── count < threshold? → 返回，等待更多纵向分析
      │
      └── count >= threshold → 自动触发横向分析
            │
            ├── run_analysis(did)
            │     │
            │     ├── 1. 恢复 per-DID 游标
            │     ├── 2. recover_traces_by_did_since(did, last_trace_id)
            │     ├── 3. 推导 node_type（agent / tool / user）
            │     ├── 4. 构建 CrossSessionProfile
            │     ├── 5. 选择 node_type 专用 Prompt
            │     │     agent: 跨Session指令链 / 缓慢投毒 / 目标替换 / 行为漂移
            │     │     tool: 工具滥用 / 数据泄露 / 接口异常
            │     │     user: 社工攻击 / 长期操控 / 账号异常
            │     ├── 6. HorizontalTaintAnalyzer.analyze()
            │     ├── 7. save_horizontal_report() → SQLite
            │     ├── 8. 更新游标，重置累积计数
            │     └── 9. suspicious/malicious?
            │           → save_malicious_report(source="horizontal_analysis")
            │
            └── HorizontalAnalysisManager.reset_accumulation(did)
```

### 4.5 纵向分析 API 端点

`api/analysis/vertical.py` 提供以下纵向分析相关端点：

#### 4.5.1 纵向分析报告查询

```
GET /api/analysis/{session_id}
→ {
    "session_id": "...",
    "reports": [
      {
        "id": 1,
        "batch_index": 0,
        "from_trace_id": 1,
        "to_trace_id": 10,
        "timestamp": 1234567890.0,
        "report": {                    // 完整 VerticalTaintReport
          "node_verdicts": [...],
          "overall_verdict": "clean",
          "context_summary": "...",
          "analyzed_dids": ["did:wba:..."]
        }
      }
    ],
    "total_batches": 1
  }
```

#### 4.5.2 意图与累计状态查询

```
GET /api/analysis/v/state/{session_id}
→ {
    "session_id": "...",
    "intent": {
      "original_task": "...",
      "core_objective": "...",
      "constraints": [...],
      "involved_capabilities": [...],
      "risk_level": "medium"
    },
    "analysis_state": {
      "batch_index": 2,
      "last_trace_id": 20,
      "report_count": 0,
      "has_context": true
    }
  }
```

#### 4.5.3 聚合查询（traces + reports + alerts）

```
GET /api/analysis/aggregate/{session_id}?protocol_node_address=...
→ {
    "session_id": "...",
    "intent": {...},                     // 用户意图
    "traces": {
      "chain": [...],                    // 完整行为链
      "total_entries": 15
    },
    "reports": [...],                    // 所有纵向分析报告
    "alerts": [                          // 仅 suspicious/malicious 的告警
      {
        "report_id": 2,
        "batch_index": 1,
        "verdict": "suspicious",
        "summary": "...",
        "from_trace_id": 11,
        "to_trace_id": 20,
        "timestamp": 1234567890.0,
        "suspicious_nodes": [
          {
            "node_did": "did:wba:...",
            "severity": "high",
            "taint_score": 0.85,
            "evidence": "..."
          }
        ]
      }
    ],
    "total_batches": 2,
    "total_alerts": 1
  }
```

**Alert 过滤规则**：仅提取 `overall_verdict` 为 `suspicious` 或 `malicious` 的报告，且仅包含 `severity` 为 `medium` 或 `high` 的节点。

#### 4.5.4 手动触发纵向分析

```
POST /api/analysis/trigger/{session_id}
→ {"triggered": true, "session_id": "...", "task_id": "..."}
或 {"triggered": false, "reason": "analysis_disabled"}
```

Fire-and-forget 模式，立即返回，分析在后台异步执行。

#### 4.5.5 纵向分析任务状态

```
GET /api/analysis/status/{session_id}
→ {
    "status": "running",       // running / completed / not_found
    "session_id": "...",
    "phase": "analyzing",      // extracting_intent / analyzing / saving / ...
    "started_at": 1234567890.0
  }
```

### 4.6 横向分析 API 端点

`api/analysis/horizontal.py` 提供以下横向分析相关端点：

#### 4.6.1 DID 横向分析报告

```
GET /api/horizontal/report/{did}
→ {
    "did": "did:wba:...",
    "reports": [
      {
        "id": 1,
        "batch_index": 0,
        "node_type": "agent",
        "from_trace_id": 1,
        "to_trace_id": 50,
        "sessions_scanned": 3,
        "timestamp": 1234567890.0,
        "report": {                    // 完整 HorizontalTaintReport
          "did_verdict": {...},
          "overall_verdict": "suspicious",
          "context_summary": "..."
        }
      }
    ],
    "total_batches": 1
  }
```

#### 4.6.2 DID 横向累积状态

```
GET /api/horizontal/state/{did}
→ {
    "did": "did:wba:...",
    "accumulated_count": 3,
    "last_trace_id": 50,
    "batch_index": 0,
    "has_context": false
  }
```

#### 4.6.3 横向分析任务状态

```
GET /api/horizontal/status/{did}
→ {
    "status": "running",       // running / completed / not_found
    "did": "did:wba:...",
    "phase": "analyzing"       // recovering_traces / analyzing / saving_results / ...
  }
```

#### 4.6.4 手动触发横向分析

```
POST /api/horizontal/trigger/{did}
→ {"triggered": true, "did": "did:wba:...", "status": "running"}
或 {"triggered": false, "reason": "horizontal_disabled"}
```

#### 4.6.5 横向分析总览

```
GET /api/horizontal/overview
→ {
    "horizontal_enabled": true,
    "accumulation_threshold": 5,
    "horizontal_dids": [
      {
        "did": "did:wba:...",
        "accumulated_count": 3,
        "last_horizontal_analysis": {
          "batch_index": 0,
          "verdict": "clean",
          "timestamp": 1234567890.0
        }
      }
    ],
    "total_dids": 3
  }
```

---

## 5. 配置模型与热重载

### 5.1 配置模型层级

基于 Pydantic v2 的配置模型，支持 camelCase/snake_case 双格式键名：

```
ProtocolNodeConfigFile (~/.attp/protocol_node/config.json)
  ├── web: PNWebConfig
  │     ├── host: str = "0.0.0.0"
  │     └── port: int = 9000
  │
  ├── storage: StorageConfig
  │     ├── data_dir: str = "~/.attp/protocol_node"
  │     └── db_path: str = "attp.db"
  │
  └── analysis: AnalysisConfig
        ├── enabled: bool = False
        ├── api_key: str = ""
        ├── base_url: str = "https://api.openai.com/v1"
        ├── model: str = "gpt-4o"
        ├── report_batch_size: int = 10
        └── accumulation_threshold: int = 5      # 横向分析累积阈值（0 = 禁用横轴）
```

### 5.2 配置加载

```python
@classmethod
def load(cls, path: str | Path) -> ProtocolNodeConfigFile:
    # 文件存在且有效 → 解析 JSON 并验证
    # 文件不存在或解析失败 → 返回默认值
```

### 5.3 热重载

```python
async def reload_config(self) -> None:
```

| 变化项 | 处理策略 |
|--------|---------|
| 端口（host/port） | 仅记录 warning，需手动重启生效 |
| 分析配置（enabled/api_key/model 等） | 重建 `CrossLockCoordinator`（含纵轴 + 横轴）并注入 |

---

## 6. CLI 命令行接口

`cli.py` 提供 Protocol Node 的独立运行入口：

```bash
# 启动协议节点
attp protocol-node start --config path/to/config.json

# 生成默认配置文件
attp protocol-node init-config [--output path/to/config.json]
```

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `start` | `--config` (默认 `~/.attp/protocol_node/config.json`) | 启动协议节点服务 |
| `init-config` | `--output` (默认 `~/.attp/protocol_node/config.json`) | 生成默认配置文件 |

**启动流程**：

```
main()
  └── _run_standalone(args)
        ├── ProtocolNode(config_path)
        ├── await node.start()
        ├── 注册 SIGINT/SIGTERM 信号处理（Windows 兼容）
        ├── await stop_event.wait()     # 阻塞直到 Ctrl+C
        └── await node.stop()
```

---

## 7. 错误码体系

`api/record.py` 中定义了 `ERROR_MAP`，将中间件错误码映射为 HTTP 状态码：

| 错误码 | HTTP 状态码 | 错误消息 | 触发条件 |
|--------|-----------|---------|---------|
| `missing_record_log` | 400 | Missing Record_Log | — |
| `hop_validation` | 400 | Hop validation failed | 基础字段不完整 |
| `did_resolution_failed` | 404 | DID resolution failed | DID 公钥解析失败 |
| `missing_type_field` | 400 | Missing ATTPNodeType | DID 文档缺少节点类型 |
| `invalid_type` | 400 | Invalid ATTP node type | 节点类型不在 agent/tool/user 中 |
| `missing_nonce` | 400 | Missing nonce | — |
| `missing_identity_signature` | 400 | Missing Identity_Signature | — |
| `identity_signature_invalid` | 403 | Identity signature invalid | — |
| `sender_mismatch_not_self` | 403 | Sender mismatch | — |
| `receiver_mismatch` | 403 | Receiver mismatch | — |
| `back_propagation` | 403 | Back-propagation verification failed | 回传验证失败（签名/哈希不一致） |
| `invalid_type_combination` | 400 | Invalid type combination | sender/reader 类型组合不在 5 种合法映射中 |
| `hop_count_violation_a2a` | 400 | Hop count violation (A2A) | A2A 跳 hop_count 不符合 `[max+1, 0]` |
| `hop_count_violation_non_a2a` | 400 | Hop count violation (non-A2A) | non-A2A 跳 hop_count 不符合递增规则 |
| `hop_zero_must_be_u2a` | 400 | hop_count=[0,0] must be U2A | 首条消息类型错误 |
| `content_signature_invalid` | 403 | Content signature invalid | — |
| `trusted_list_violation` | 403 | Trusted list violation | — |

---

## 8. API 端点汇总

### 8.1 Record 接收

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/record` | 接收并处理 BackMessage（双轮回溯确认入口） |

### 8.2 行为溯源

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 健康检查 |
| GET | `/api/behavior/{session_id}` | 行为溯源链查询 |

### 8.3 纵向分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/analysis/{session_id}` | 纵向分析报告查询 |
| GET | `/api/analysis/v/state/{session_id}` | 意图与累计状态查询 |
| GET | `/api/analysis/aggregate/{session_id}` | 聚合查询（traces + reports + alerts） |
| POST | `/api/analysis/trigger/{session_id}` | 手动触发纵向分析 |
| GET | `/api/analysis/v/llm-status/{session_id}` | 纵向LLM分析任务状态 |

### 8.4 横向分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/horizontal/report/{did}` | DID 横向分析报告 |
| GET | `/api/analysis/h/state/{did}` | DID 横向累积状态（batch_index 即报告批次/次数） |
| GET | `/api/analysis/h/llm-status/{did}` | 横向LLM分析任务状态 |
| POST | `/api/horizontal/trigger/{did}` | 手动触发横向分析 |
| GET | `/api/horizontal/overview` | 横向分析总览 |

### 8.5 恶意节点查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/malicious/session/{session_id}?source=...` | 按 session 查询恶意报告（支持 source 筛选） |
| GET | `/api/malicious/did/{did}?source=...` | 按 DID 查询恶意报告（支持 source 筛选） |
| GET | `/api/malicious/dossier/{did}` | 单个节点档案（含违规明细） |
| GET | `/api/malicious/dossiers` | 全部节点档案（可按 severity 筛选） |

---

## 9. 设计模式与总结

### 9.1 设计模式

| 模式 | 应用场景 | 说明 |
|------|---------|------|
| **Facade（门面）** | `ProtocolNode` | 封装所有组件的创建和生命周期管理，对外仅暴露 `start()/stop()` |
| **Coordinator（协调器）** | `CrossLockCoordinator` | 串联纵轴和横轴的触发关系，解耦纵横编排器 |
| **Pipeline（管道）** | `middleware.intercept_record()` | 7 步顺序验证管线，每步可提前终止 |
| **Strategy（策略）** | `BehaviorController`；横向分析按 `node_type` 选择 Prompt | 按 node_type 分发到不同处理器；agent/tool/user 隔离审查 |
| **Decision Tree（决策树）** | `MaliciousNodeDetector` | 双回传 5 步 + 单回传 3 分支的树形判定逻辑 |
| **Late Binding（延迟绑定）** | `orchestrator_holder: list` | 使用可变容器实现 CrossLockCoordinator 的延迟注入和热替换 |
| **Repository** | Core 层 `SqliteStore` | 数据访问抽象，Protocol Node 通过 `ProtocolTracer` 间接访问 |
| **Observer（观察者）** | Coordinator 回调 | `on_field_U2A_recorded` / `on_record_received` 由 record 路由触发 |
| **State Manager** | `VerticalAnalysisManager` / `HorizontalAnalysisManager` | 将分析状态管理从编排器中解耦 |

### 9.2 架构特点

| 特点 | 说明 |
|------|------|
| **自包含设计** | 传入 `config_path` 即可运行，内部自行加载配置、创建所有依赖 |
| **存储前置** | Branch A 始终暂存，不拒绝，将安全判定延迟到 Branch B |
| **双层恶意检测** | 双回传（实时判定）+ 单回传（过期判定），覆盖所有消息丢失场景 |
| **十字锁定分析** | 纵轴（Session-Level）+ 横轴（DID-Level）双维度污点分析，纵轴完成后自动累积触发横轴 |
| **统一恶意报告** | 协议审查、纵向分析、横向分析三个来源写入同一张 `malicious_reports` 表，API 支持 `source` 筛选 |
| **可选分析集成** | CrossLockCoordinator 完全可选，未配置时不影响消息追踪功能 |
| **单端口架构** | 合并数据端口和 API 端口，简化部署和网络配置 |
| **配置热重载** | 分析配置可热更新（包括纵轴/横轴），端口变更需手动重启 |

### 9.3 与 Core 层的关系

Protocol Node 是 Core 层的**上层编排者**：

| Core 层组件 | Protocol Node 使用方式 |
|-------------|----------------------|
| `ProtocolTracer` | 溯源链验证 + SQLite 存储门面 |
| `ProtocolSessionManager` | per-session 验证状态管理（PendingMessage、可信名单、hop_count） |
| `DIDResolver` | DID → 公钥解析（带 TTL 缓存） |
| `CrossLockCoordinator` | 可选集成，十字锁定污点分析生命周期管理（纵轴 + 横轴） |
| `VerticalAnalysisManager` | 纵向分析状态持久化管理 |
| `HorizontalAnalysisManager` | 横向分析状态持久化管理 |
| `ChainManager.verify_back_propagation` | 回传验证三步检查（签名→字节比对→哈希一致性） |

Protocol Node 本身不实现加密算法、哈希计算或数据库访问，这些全部委托给 Core 层。Protocol Node 的核心价值在于**验证管线的编排**、**恶意节点判定决策树**和**十字锁定污点分析**的实现。