# ATTP Protocol Node 代码与功能分析

> 本文档对 `python/attp/protocol_node/` 目录下的所有模块进行全面的代码结构与功能分析，重点聚焦于**消息固化层**和**意图追踪层**（v0.3.0 逐跳有状态改版）。
>
> 适用版本：`dev` 分支（v0.3.0）。文中所有结论均以 `python/attp/protocol_node/` 与其直接调用的 `python/attp/core/analysis/` 源码为准。

## 目录

- [ATTP Protocol Node 代码与功能分析](#attp-protocol-node-代码与功能分析)
  - [目录](#目录)
  - [1. 概述](#1-概述)
  - [2. 模块架构总览](#2-模块架构总览)
    - [模块依赖关系](#模块依赖关系)
    - [启动流程](#启动流程)
  - [3. 消息固化层](#3-消息固化层)
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
      - [3.4.2 统一报告格式](#342-统一报告格式)
      - [3.4.3 端点说明](#343-端点说明)
    - [3.5 行为溯源查询 API（trace）](#35-行为溯源查询-apitrace)
    - [3.6 行为记录分发（behavior\_controller）](#36-行为记录分发behavior_controller)
    - [3.7 消息固化层完整数据流](#37-消息固化层完整数据流)
  - [4. 意图追踪层（逐跳有状态改版）](#4-意图追踪层逐跳有状态改版)
    - [4.1 CrossLockCoordinator 集成与生命周期](#41-crosslockcoordinator-集成与生命周期)
      - [4.1.1 构建条件](#411-构建条件)
      - [4.1.2 注入路径与纵横联动](#412-注入路径与纵横联动)
      - [4.1.3 配置模型](#413-配置模型)
      - [4.1.4 热重载](#414-热重载)
    - [4.2 逐跳异步评分管道](#42-逐跳异步评分管道)
    - [4.3 意图流抽取（U2A 分流）](#43-意图流抽取u2a-分流)
    - [4.4 纵轴 R\_T 单点告警](#44-纵轴-r_t-单点告警)
    - [4.5 横轴 F 累加与跨会话确认](#45-横轴-f-累加与跨会话确认)
    - [4.6 评分量纲与结论推导（core/base\_models）](#46-评分量纲与结论推导corebase_models)
    - [4.7 纵向分析 API 端点](#47-纵向分析-api-端点)
    - [4.8 横向分析 API 端点](#48-横向分析-api-端点)
    - [4.9 十字锁定综合视图 API](#49-十字锁定综合视图-api)
    - [4.10 SSE 事件流（`api/events.py`）](#410-sse-事件流apieventspy)
  - [5. 配置模型与热重载](#5-配置模型与热重载)
    - [5.1 配置模型层级](#51-配置模型层级)
    - [5.2 配置加载](#52-配置加载)
    - [5.3 热重载](#53-热重载)
  - [6. CLI 命令行接口](#6-cli-命令行接口)
  - [7. 错误码体系](#7-错误码体系)
  - [8. API 端点汇总](#8-api-端点汇总)
    - [8.1 Record 接收](#81-record-接收)
    - [8.2 行为溯源与健康检查](#82-行为溯源与健康检查)
    - [8.3 纵向分析（`/api/analysis/v`）](#83-纵向分析apianalysisv)
    - [8.4 横向分析（`/api/analysis/h`）](#84-横向分析apianalysish)
    - [8.5 十字锁定综合视图](#85-十字锁定综合视图)
    - [8.6 SSE 事件流](#86-sse-事件流)
    - [8.7 恶意节点查询](#87-恶意节点查询)
  - [9. 设计模式与总结](#9-设计模式与总结)
    - [9.1 设计模式](#91-设计模式)
    - [9.2 架构特点](#92-架构特点)
    - [9.3 与 Core 层的关系](#93-与-core-层的关系)

---

## 1. 概述

Protocol Node（协议节点/溯源节点）是 ATTP（Agent Trust and Traceability Protocol）协议的**独立溯源服务节点**，承载了 ATTP 四层架构中的两层核心逻辑：

| 协议层 | Protocol Node 对应模块 | 说明 |
|--------|----------------------|------|
| **消息固化层** | `engine/middleware.py`、`engine/malicious_detector.py`、`api/record.py`、`api/malicious.py`、`api/trace.py` | 接收双轮回溯消息、身份验证、内容一致性校验、恶意节点判定、行为溯源查询 |
| **意图追踪层** | `CrossLockCoordinator`（core 层）集成、`api/analysis/vertical.py`、`api/analysis/horizontal.py`、`api/analysis/cross_lock.py`、`api/events.py` | 十字锁定意图追踪：纵轴（Session-Level 逐跳评分）+ 横轴（DID-Level F 累加 + 跨会话确认） |

> v0.3.0 重要变更：意图追踪层由旧版「taint analysis + 批次/累计计数触发」重构为**逐跳有状态模型**——纵轴每条动作跳由 V-Reasoner 打分（s_i∈[0,10]），超过单点阈值 R_T 立即告警；横轴 per-DID 累加 F=Σs²，超过 R_S 触发跨会话确认。`/record` 对 LLM **完全异步**：落库后只把该跳投入会话有界队列即返回，绝不 await LLM。详见第 4 章。

Protocol Node 的核心职责：

| 能力 | 说明 |
|------|------|
| 双轮回溯确认 | 接收通信双方的 BackMessage，通过 nonce 匹配实现不可否认性验证 |
| 恶意节点检测 | 基于决策树的自动恶意判定（身份篡改、内容篡改、可信名单违规等 7 种证据类型） |
| 行为溯源存储 | 将验证通过的行为记录持久化到 SQLite，支持按 session 查询完整行为链 |
| 逐跳意图追踪 | 可选集成十字锁定分析引擎：纵轴逐跳 V-Reasoner 评分 + 横轴 per-DID F 累加与跨会话确认 |
| 恶意节点档案 | 累计恶意行为记录（统一协议审查 / 纵向 R_T 告警 / 横向确认三个来源），维护节点严重等级（clean → warning → dangerous → banned） |
| 实时事件推送 | 通过 SSE（`/api/events`）向用户端推送 trace / analysis / malicious / record 事件，替代前端轮询 |

> 身份管理和加密通信层说明：当前 `dev` 分支的「身份管理和加密通信层」仅指 **DID 身份认证 + 内容签名**（见消息固化层对 `sig_identity` / `sig_content` 的验证）。端到端加密 / 统一 transport+security **不在 `dev` 分支**（位于 `refactor/transport`，属 v0.4.0），本文不将其作为已实现特性描述。

---

## 2. 模块架构总览

```
protocol_node/
├── __init__.py                      # 模块声明，导出 ProtocolNode
├── node.py                          # ProtocolNode 主类 — 生命周期管理 + _build_orchestrator
├── cli.py                           # CLI 入口 — start / init-config
│
├── config/
│   ├── __init__.py
│   └── config.py                    # ProtocolNodeConfigFile — Pydantic 配置模型（含 AnalysisConfig）
│
├── engine/
│   ├── __init__.py
│   ├── middleware.py                 # 消息拦截中间件 — 验证管道核心
│   ├── malicious_detector.py         # 恶意节点判定引擎 — 双回传/单回传决策树
│   └── behavior_controller.py        # 行为记录分发控制器
│
├── ports/
│   ├── __init__.py
│   └── protocol_port.py             # 统一端口 — FastAPI + uvicorn + SSE
│
└── api/
    ├── __init__.py
    ├── record.py                    # /record 接收路由 — 验证 + 落库 + 异步入队
    ├── trace.py                     # /api 行为溯源 + 健康检查
    ├── malicious.py                 # /api/malicious/* 恶意节点查询路由（统一格式）
    ├── events.py                    # /api/events — SSE 事件流
    └── analysis/                    # 意图追踪 API 子路由
        ├── __init__.py
        ├── vertical.py              # /api/analysis/v/* 纵向逐跳评分路由
        ├── horizontal.py            # /api/analysis/h/* 横向 F/确认路由
        └── cross_lock.py            # /api/analysis/cross-lock/* 综合视图路由
```

### 模块依赖关系

```
ProtocolNode (node.py)
  │
  ├── ProtocolNodeConfigFile (config/config.py)
  │     ├── PNWebConfig          — 网络（host/port，默认 9000）
  │     ├── StorageConfig        — 数据目录 + DB 路径
  │     └── AnalysisConfig       — 意图追踪（逐跳）配置：阈值 / 并发 / 队列
  │
  ├── EventBroker (core/sse.py)              — SSE 事件总线，注入 storage + 各 API
  │
  ├── ProtocolTracer (core/pn_tracer.py)
  │     ├── KeyStore             — 公钥缓存
  │     ├── ChainManager         — 溯源链 / 回传验证
  │     └── SqliteStore          — 异步 SQLite 存储（behavior_traces / hop_scores / malicious_reports ...）
  │
  ├── ProtocolSessionManager (core/sessions/protocol_node/)
  │     └── ProtocolSession      — per-session 验证状态 + 纵向隐状态（意图流 / h_i / 游标）
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
  │     ├── FastAPI + uvicorn (+ CORS)
  │     │
  │     ├── record router (api/record.py)
  │     │     └── middleware.intercept_record()  — 验证管道
  │     │           verified → save_behavior_entry + behavior_controller.handle
  │     │                    → orchestrator.enqueue_trace(session_id, hop)  [异步，不等 LLM]
  │     │
  │     ├── behavior router (api/trace.py)
  │     │     └── ProtocolTracer — 健康检查 + 行为溯源查询
  │     │
  │     ├── analysis sub-routers (api/analysis/)
  │     │     ├── vertical.py    — 纵向逐跳评分查询 / 手动触发 / worker 状态
  │     │     ├── horizontal.py  — 横向 F/volume/确认报告 / 手动触发 / 状态
  │     │     └── cross_lock.py  — 纵横聚合综合视图
  │     │
  │     ├── malicious router (api/malicious.py)
  │     │     └── ProtocolTracer — 统一 /reports 查询 + /dossier(s) 档案
  │     │
  │     └── events router (api/events.py) [broker 非空时挂载]
  │           └── EventBroker — SSE 流（trace/analysis/malicious/record）
  │
  └── CrossLockCoordinator (core/analysis/cross_lock.py) [可选，analysis.enabled]
        ├── VerticalOrchestrator (core/analysis/vertical/orchestrator.py)
        │     ├── per-session 有界队列 worker（queue_maxsize，真背压）
        │     ├── 全局并发信号量（concurrency）
        │     ├── VerticalIntentAnalyzer — extract_intent_revision / score_hop（LLM）
        │     ├── VerticalAnalysisManager — 意图流 / 隐状态 / 打分游标持久化
        │     └── R_T 单点告警 → save_malicious_report(source=vertical_analysis)
        │
        └── HorizontalOrchestrator (core/analysis/horizontal/orchestrator.py) [可选，horizontal_enabled]
              ├── on_hop_scored → per-DID F=Σs² 累加（无死区/折扣/封顶）
              ├── F>R_S 且 volume≥_MIN_TRIGGER_VOLUME → 跨会话确认
              ├── α 会话选择（W(σ)=Σs² 降序）+ ρ 高危兜底
              ├── HorizontalIntentAnalyzer — confirm（LLM）
              └── 确认恶意 → save_malicious_report(source=horizontal_analysis)
```

### 启动流程

`ProtocolNode.start()`（`node.py:67`）的实际顺序：

```
ProtocolNode.__init__(config_path)
  │  同步加载配置（ProtocolNodeConfigFile.load）
  │
  └── ProtocolNode.start()
       │
       ├── 1. ProtocolTracer.create(db_path)          → 初始化溯源链 + SQLite
       ├── 1.5 EventBroker() + storage.set_event_broker(broker)  → SSE 事件总线
       ├── 2. ProtocolSessionManager(storage)          → 会话管理（带持久化）
       ├── 3. DIDResolver(key_store) / BehaviorController() / MaliciousNodeDetector(did_resolver)
       ├── 4. ProtocolPort(tracer, session_manager, host, port,
       │     did_resolver, behavior_controller, malicious_detector, event_broker)
       ├── 5. _build_orchestrator() [可选]             → CrossLockCoordinator（纵轴 + [横轴]）
       │     └── 若返回非 None：port.set_orchestrator(coordinator)
       ├── 6. port.start()                             → uvicorn 后台 Task 启动
       └── 7. _periodic_sweep() Task                   → 每 60s 扫描过期 PendingMessage（单回传判定）
```

`stop()`（`node.py:123`）顺序：取消 `_sweep_task` → `orchestrator.shutdown()`（停纵横 worker）→ `port.stop()`（uvicorn `should_exit`，等 5s 后取消 Task）。

---

## 3. 消息固化层

消息固化层是 Protocol Node 的核心，实现了 ATTP 协议的双轮回溯确认机制、恶意节点自动检测和行为溯源存储。

### 3.1 统一端口与 Record 接收入口

#### 3.1.1 ProtocolPort（`ports/protocol_port.py`）

Protocol Node 采用**单端口架构**，合并了原来的 DataPort（`/record`）、ApiPort（`/api/*`）以及 SSE 流（`/api/events`），通过一个 FastAPI 应用统一对外服务（`protocol_port.py:22`）。

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
        event_broker: EventBroker | None = None,
    )
```

**路由挂载**（`_mount_routes`，`protocol_port.py:69`）—— 注意纵向/横向 API 的实际前缀：

```
ProtocolPort._mount_routes()
  │
  ├── /record                         → record router (api/record.py)
  │     └── POST /record              — 接收 BackMessage
  │
  ├── /api                            → behavior router (api/trace.py)
  │     ├── GET  /api/status                    — 健康检查
  │     └── GET  /api/behavior/{session_id}     — 行为溯源链
  │
  ├── /api/malicious                  → malicious router (api/malicious.py)
  │     ├── GET  /api/malicious/reports         — 统一报告查询（session_id/did/source/limit）
  │     ├── GET  /api/malicious/dossier/{did}   — 单个档案（含 source_breakdown）
  │     └── GET  /api/malicious/dossiers        — 全部档案（severity/source 筛选）
  │
  ├── /api/analysis/v                 → vertical router (api/analysis/vertical.py)
  │     ├── GET  /api/analysis/v/report/{session_id}      — 逐跳评分聚合报告
  │     ├── GET  /api/analysis/v/state/{session_id}       — 意图流 / 隐状态 / 游标
  │     ├── GET  /api/analysis/v/aggregate/{session_id}   — traces + hop_scores + R_T 告警
  │     ├── POST /api/analysis/v/trigger/{session_id}     — 手动触发（补打未评分跳）
  │     └── GET  /api/analysis/v/llm-status/{session_id}  — worker 状态（供轮询）
  │
  ├── /api/analysis/h                 → horizontal router (api/analysis/horizontal.py)
  │     ├── POST /api/analysis/h/trigger/{did}     — 手动触发横轴确认
  │     ├── GET  /api/analysis/h/report/{did}      — DID 全部确认报告
  │     ├── GET  /api/analysis/h/state/{did}       — F / volume / 游标 / 批次
  │     └── GET  /api/analysis/h/llm-status/{did}  — 确认任务状态（供轮询）
  │
  ├── /api/analysis                   → cross-lock router (api/analysis/cross_lock.py)
  │     └── GET  /api/analysis/cross-lock/{session_id}  — 纵横聚合综合视图
  │
  └── /api/events [broker 非空时]     → events router (api/events.py)
        └── GET  /api/events          — SSE 事件流（session_id/did/topics 过滤）
```

> FastAPI 启用 CORS（`allow_origins=["*"]`）。`event_broker` 为 `None` 时不挂载 SSE 路由；ProtocolNode 启动时总会创建 broker，故实际总是挂载。

**CrossLockCoordinator Late-Binding**：

Coordinator 在 `port.start()` 之前通过 `set_orchestrator` 注入，且支持运行时热替换（热重载）。ProtocolPort 同时保留两份引用：实例属性 `self._orchestrator` 与可变列表 `self._orch_holder = [None]`（`protocol_port.py:61-62`）。各 analysis 路由通过闭包捕获 `orchestrator_holder` 列表访问最新实例：

```python
self._orch_holder: list = [None]  # 长度为 1 的可变列表

def set_orchestrator(self, orchestrator) -> None:
    self._orchestrator = orchestrator
    self._orch_holder[0] = orchestrator  # 所有路由通过 _orch_holder[0] 访问
```

**生命周期**：

| 方法 | 行为 |
|------|------|
| `start()` | 创建 `uvicorn.Server`（使用 `UVICORN_SILENT_LOG_CONFIG`）并作为 `asyncio.Task` 后台运行 |
| `stop()` | 设置 `should_exit=True`，等待 5 秒；超时则取消 Task |

#### 3.1.2 Record 接收路由（`api/record.py`）

`POST /record` 是整个消息固化层的**唯一写入入口**，接收来自 Agent/Tool/User 的 BackMessage。`get_record_router` 接收 `orchestrator_holder`（延迟绑定）与可选 `event_broker`（用于在错误出口发布 `record.error` 事件）。

**处理流程**（`receive_record`，`record.py:105`）：

```
POST /record
  │
  ├── 1. 解析 JSON body
  │     失败 → 发布 record.error(invalid_json) → 400
  │
  ├── 2. BackMessage.from_dict(body)
  │     失败 → 发布 record.error(invalid_backmessage) → 400
  │
  ├── 3. 调用 middleware.intercept_record(back_msg, did_resolver, tracer,
  │     session_manager, malicious_detector)
  │     │
  │     ├── status == "error"     → ERROR_MAP 映射 → HTTP 错误码（发布 record.error）
  │     ├── status == "stored"    → 200 {"status": "stored", "nonce", "session_id"}
  │     ├── status == "malicious" → 403 {"status": "malicious_detected", ...}
  │     └── status == "verified"  → 继续后续处理
  │
  ├── 4. [verified] 保存行为记录（record.py:189）
  │     trace_id = tracer.save_behavior_entry(
  │         session_id, protocol_node_address=pna,
  │         sender_did=stored.node_did,        # 验证过的真实发送方
  │         target_did=result.sender_did,      # 验证过的真实接收方
  │         hop_count, field_type, content, timestamp)
  │
  ├── 5. [verified] 行为分发（record.py:204）
  │     behavior_controller.handle(result.node_type, body, result)
  │
  ├── 6. [verified] 逐跳异步入队（record.py:210）
  │     _orch = orchestrator_holder[0]
  │     if _orch and session_id:
  │         hop = {trace_id, session_id, sender_did, field_type, hop_count, content, target, timestamp}
  │         await _orch.enqueue_trace(session_id, hop)   # 不 await LLM，仅投入有界队列
  │
  └── 7. 返回 200 {"status": "Record verified and saved"}
```

> **关键差异（v0.3.0）**：verified 分支不再做任何 LLM 同步调用、不再做「U2A 意图提取」或「批次计数」——这些都被 `enqueue_trace` 异步化，由纵轴 worker 在后台按 trace 序串行处理（见 4.2）。`/record` 的延迟与 LLM 无关。

`_publish_record_error`（`record.py:60`）是 None-safe 的事件发布辅助：优先用已解析的 `back_msg`，否则 best-effort 从 raw body 取字段，组装 `record.error` 帧发布到 `Topic.RECORD`。

### 3.2 消息拦截验证管道（middleware）

`engine/middleware.py` 是消息固化层的**核心验证逻辑**。模块顶部注释列出的管线为：基础字段 → DID 解析+节点类型 → Nonce 会话分支（Branch A 暂存 / Branch B 恶意判定 + `verify_back_propagation` + 行为推断 + 可信名单更新）。

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

5 种合法的 `(sender_node_type, receiver_node_type)` → `field_type` 组合（`middleware.py:30`）：

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

`intercept_record`（`middleware.py:95`）的实际步骤序列：

```
intercept_record(back_msg, did_resolver, tracer, session_manager, malicious_detector)
  │
  ╔══════════════════════════════════════════════════════════════════╗
  ║  Step 1: 基础字段完整性（_validate_back_message）                  ║
  ║  - node_did / nonce / sig_identity 非空                           ║
  ║  - session_id / sender_did / target_did 非空                      ║
  ║  - hop_count 为二元组 [a2a, intra] 且 >= 0                        ║
  ║  - timestamp > 0，sig_content 非空                                ║
  ║  失败 → status="error", error="hop_validation:{detail}"           ║
  ╚══════════════════════════════════════════════════════════════════╝
  │
  ╔══════════════════════════════════════════════════════════════════╗
  ║  Step 2: DID 解析 + 节点类型校验（did_resolver.resolve_full）      ║
  ║  - public_key is None → "did_resolution_failed"（404）            ║
  ║  - node_type is None  → "missing_type_field"                      ║
  ║  - node_type ∉ {agent,tool,user} → "invalid_type"                 ║
  ║  - 缓存公钥到 key_store（供后续 verify_back_propagation 复用）     ║
  ╚══════════════════════════════════════════════════════════════════╝
  │
  ╔══════════════════════════════════════════════════════════════════╗
  ║  Step 3: Nonce 会话分支                                           ║
  ║  - session = session_manager.get_or_create(session_id)            ║
  ║  - _sweep_expired_pending(session, ...)  ← 先扫过期（见 3.2.5）   ║
  ║  - stored_msg = session.get_pending_message(nonce)                ║
  ╚══════════════════════════════════════════════════════════════════╝
  │
  ├── stored_msg is None → Branch A（回传 1 先到达，middleware.py:181）
  │     │
  │     ├── identity_ok = back_msg.verify_identity(public_key)
  │     ├── 构造 PendingMessage（含 identity_verified=identity_ok、
  │     │   identity_verification_attempted=True、sender_node_type）
  │     ├── session.store_pending_message(nonce, pending)
  │     ├── session_manager.save(session)
  │     └── 返回 InterceptResult(status="stored", node_type, sender_did)
  │
  └── stored_msg exists → Branch B（回传 2 后到达，middleware.py:210）
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 4: 恶意节点判定引擎                                   ║
        ║  report = malicious_detector.evaluate_dual_back_prop(      ║
        ║      stored_msg, back_msg, session)                        ║
        ║  - report 非空：remove_pending + save_malicious_report     ║
        ║    → 返回 status="malicious"                               ║
        ╚════════════════════════════════════════════════════════════╝
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 5: 内容一致性验证（回传验证）                          ║
        ║  tracer.verify_back_propagation(                           ║
        ║      stored_hop=stored_msg.hop, prev_hop=hop_dict, sid)    ║
        ║  - 由 ChainManager 执行签名/字节比对/哈希一致性             ║
        ║  失败 → remove_pending + status="error",                   ║
        ║         error="back_propagation:{detail}"                  ║
        ╚════════════════════════════════════════════════════════════╝
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 6: 行为类型推断 + hop_count 校验                      ║
        ║  - behavior_type = BEHAVIOR_TYPE_MAP[(sender_type,recv)]   ║
        ║    None → "invalid_type_combination"                       ║
        ║  - [0,0] 必须为 U2A，否则 "hop_zero_must_be_u2a"            ║
        ║  - 基于 session 的 max_a2a / latest_intra 校验：            ║
        ║    A2A:   hc[0]==max_a2a+1 且 hc[1]==0                     ║
        ║           否则 "hop_count_violation_a2a"                   ║
        ║    非A2A: hc[0]≤max_a2a 且 hc[1]==latest_intra+1           ║
        ║           否则 "hop_count_violation_non_a2a"               ║
        ╚════════════════════════════════════════════════════════════╝
        │
        ╔════════════════════════════════════════════════════════════╗
        ║  Step 7: 验证通过 → 更新可信名单                             ║
        ║  session.complete_verification(nonce, hop_count, node_did) ║
        ║  session_manager.save(session)                             ║
        ╚════════════════════════════════════════════════════════════╝
        │
        └── 返回 InterceptResult(status="verified", node_type=receiver_type,
              sender_did=node_did, target_did, behavior_type, stored_msg)
```

> Step 6 中的 hop_count 校验依赖 `ProtocolSession` 的 `get_max_a2a_count()` / `get_latest_intra_count()`（基于会话已验证跳的 `hop_count_map` 推导）。任一失败分支都会先 `session.remove_pending_message(nonce)` 再 `save(session)`，避免脏 PendingMessage 残留。

#### 3.2.4 Branch A vs Branch B 对比

| 阶段 | Branch A（回传 1 先到） | Branch B（回传 2 后到） |
|------|----------------------|----------------------|
| 触发条件 | `session.get_pending_message(nonce)` 返回 `None` | 已有同一 nonce 的 PendingMessage |
| 身份验证 | `back_msg.verify_identity(public_key)` → 结果存入 `identity_verified` | 由恶意检测器在 Step 0a/0b/1 内部处理 |
| 存储行为 | 构造 `PendingMessage`（含 `identity_verification_attempted=True`）并暂存 | 无论后续成功/失败，都 `remove_pending_message(nonce)` |
| 后续动作 | 等待回传 2 到达 | 恶意检测 → 回传验证 → 行为推断 + hop_count 校验 → 更新可信名单 |
| 返回状态 | `"stored"` | `"verified"` / `"malicious"` / `"error"` |

#### 3.2.5 过期 PendingMessage 处理

PendingMessage 默认 TTL 为 300 秒（由 `ProtocolSession.pop_expired_pending_messages()` 依据 `stored_at` 判定）。过期消息通过两条途径清理并送入单回传判定：

1. **实时清理**（`_sweep_expired_pending`，`middleware.py:53`）：在每次 `intercept_record()` 的 nonce 查找**前**触发——扫描当前 session 的过期消息，逐条调用 `malicious_detector.evaluate_single_back_prop(msg, session)`；若返回报告则 `report.node_type = msg.sender_node_type` 并 `tracer.save_malicious_report(report)`。这样可避免 `get_pending_message` 静默丢弃过期消息。
2. **周期清理**（`ProtocolNode._periodic_sweep`，`node.py:142`）：每 60 秒遍历 `session_manager._sessions` 中所有 session，对每个 session 的过期消息跑一次单回传判定；若有过期则 `save(session)` 持久化。

> 单回传判定逻辑见 3.3.4。

### 3.3 恶意节点判定引擎（malicious_detector）

`engine/malicious_detector.py` 实现了 ATTP 协议的**恶意节点自动检测机制**（crypto-level 判定，不涉及 LLM）。该模块在 v0.3.0 未变，仍是双回传 / 单回传两条决策树。

#### 3.3.1 证据类型

```python
class EvidenceType(Enum):   # malicious_detector.py:23
    IDENTITY_TAMPERING = "identity_tampering"          # 身份篡改
    TRUSTED_LIST_VIOLATION = "trusted_list_violation"  # 可信名单违规
    CONTENT_TAMPERING = "content_tampering"            # 内容篡改
    NO_PROPAGATION = "no_propagation"                  # 未传播（接收但不回传）
    FRAMING = "framing"                                # 栽赃（发送方双签）
    INDISTINGUISHABLE_PAIR = "indistinguishable_pair"  # 不可区分对
    SAME_DID_DUPLICATE = "same_did_duplicate"          # 相同 DID 重复回传
```

#### 3.3.2 MaliciousNodeReport — 恶意检测报告

```python
@dataclass
class MaliciousNodeReport:   # malicious_detector.py:33
    malicious_dids: list[str]
    evidence_type: EvidenceType
    evidence_description: str
    session_id: str
    nonce: str
    timestamp: float
    raw_evidence: dict
    node_type: str = ""  # 由 middleware 从 DID 解析结果填入（agent / tool / user）
```

落库时由 `tracer.save_malicious_report` 写入 `malicious_reports` 表，`source="protocol_review"`（与 `vertical_analysis` / `horizontal_analysis` 两个来源共用同一张表）。

#### 3.3.3 双回传判定决策树（evaluate_dual_back_prop）

当同一 nonce 收到两条 BackMessage 时触发（`evaluate_dual_back_prop`，`malicious_detector.py:73`）。完整决策树：

```
evaluate_dual_back_prop(stored_msg, back_msg_2, session)
  │
  │  输入:
  │    stored_msg  = 回传1（先到达，已暂存为 PendingMessage，identity_verified 在其中）
  │    back_msg_2  = 回传2（后到达，当前消息）
  │    session     = ProtocolSession（含可信名单）
  │
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 0a: 回传1 身份签名检查（stored_msg.identity_verified）        ║
  ║  → 失败: IDENTITY_TAMPERING                                        ║
  ║    - 有可信名单: 通报可信名单中所有节点                              ║
  ║    - 无可信名单: 报告回传1的 node_did                               ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 0b: 回传1 可信名单校验（bp1_did ∉ trusted_list）              ║
  ║  → 违规: TRUSTED_LIST_VIOLATION，通报可信名单中所有节点             ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 1: 回传2 身份签名检查                                         ║
  ║  did_resolver.resolve_full(bp2_did) → 公钥                          ║
  ║  - 公钥为 None: IDENTITY_TAMPERING，判定回传1的 target_did 恶意     ║
  ║  - verify_identity 失败: IDENTITY_TAMPERING，判定 target_did 恶意   ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 2: DID 比对（bp1_did == bp2_did?）                            ║
  ║  → 相同: SAME_DID_DUPLICATE，该节点为恶意                           ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过（两条回传来自不同节点）
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 3: 回传1 内容签名自检                                         ║
  ║  解析回传1 sender DID → 公钥；_compute_recorded_hop_content_hash    ║
  ║  + _verify_content_sig 验证回传1内容签名                            ║
  ║  - DID 解析失败 / 签名失败: CONTENT_TAMPERING，回传1节点为恶意      ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 4: 回传2 内容签名交叉验证                                     ║
  ║  用回传1 sender 的公钥验证回传2的内容签名                           ║
  ║  - 失败: INDISTINGUISHABLE_PAIR — 无法区分发送方伪造还是接收方篡改  ║
  ║    两节点一起通报                                                   ║
  ║  - 成功: 进入 Step 4b                                              ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 交叉验证成功
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Step 4b: 发送方双签（栽赃）检测                                    ║
  ║  比对两条回传的 sig_content 是否一致                                 ║
  ║  - 不一致: FRAMING — 两条签名均在 sender 公钥下有效却互不相同，     ║
  ║    仅 sender 私钥持有者可做到 ⇒ sender 恶意                         ║
  ║  - 一致: return None（无恶意，双回传验证通过）                      ║
  ╚════════════════════════════════════════════════════════════════════╝
```

#### 3.3.4 单回传判定决策树（evaluate_single_back_prop）

当 PendingMessage 过期但仅收到一条回传时触发（`evaluate_single_back_prop`，`malicious_detector.py:283`）。

```
evaluate_single_back_prop(pending_msg, session)
  │
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Case A: 身份签名验证失败 → 直接丢弃                                ║
  ║  pending_msg.identity_verified == False?                            ║
  ║  → return None（不通报任何节点）                                    ║
  ║    无主垃圾消息：既未对特定方注入、也非针对具体节点的栽赃，         ║
  ║    按威胁模型原则不予追究；同时杜绝恶意节点借单回传对可信名单       ║
  ║    发起广播栽赃洪流（反例 C1）                                     ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Case B: DID 不在可信名单中（trusted_list and node_did ∉ list）     ║
  ║  → TRUSTED_LIST_VIOLATION，通报可信名单                            ║
  ╚════════════════════════════════════════════════════════════════════╝
  │ 通过（身份 OK 且 DID 在可信名单中）
  ▼
  ╔════════════════════════════════════════════════════════════════════╗
  ║  Case C: 检查后续活动                                               ║
  ║  has_subsequent = session.has_subsequent_activity_after(nonce)      ║
  ║                                                                    ║
  ║  - 有后续活动 + 有不同身份                                         ║
  ║    (has_subsequent_with_different_verified_identity):               ║
  ║    NO_PROPAGATION — 节点接收了但未回传，target_did 为恶意           ║
  ║                                                                    ║
  ║  - 有后续活动 + 无不同身份:                                        ║
  ║    return None — 视为恶意节点自发自弃，不予记录                     ║
  ║                                                                    ║
  ║  - 无后续活动:                                                     ║
  ║    return None — 视为垃圾消息抛弃                                   ║
  ╚════════════════════════════════════════════════════════════════════╝
```

#### 3.3.5 辅助方法

| 方法 | 功能 |
|------|------|
| `_compute_recorded_hop_content_hash(hop)`（静态） | 从 hop dict 按 `{session_id, sender_did, target_did, content, timestamp, hop_count}` 计算 SHA-256（与 `RecordedHop.content_hash()` 逻辑一致） |
| `_verify_content_sig(content_hash, sig_content, public_key)`（静态） | 调用 `core/authentication/signatures.py::verify_signature()` 验证内容签名；空签名直接返回 False |

### 3.4 恶意节点查询 API（malicious）

`api/malicious.py` 提供 3 个恶意节点查询端点。**v0.3.0 变更**：原 `/session/{session_id}` 与 `/did/{did}` 两个端点已合并为统一的 `/api/malicious/reports`，支持 `session_id` / `did` / `source` 组合筛选；`/dossiers` 新增 `source` 筛选与 `source_breakdown` 字段。

#### 3.4.1 DID 规范化（`_normalise_did`）

FastAPI 会自动 URL-decode 路径参数，导致 `localhost%3A8000` 变为 `localhost:8000`，与数据库中存储的 canonical DID 不匹配。`_normalise_did`（`malicious.py:14`）负责还原：

```
did:wba:localhost:8000:path:segment
→ did:wba:localhost%3A8000:path:segment
```

规则：若 DID 已含 `%3A` 直接返回；否则当 `did:wba:` 后第 4 段为纯数字（端口号）时，将其合并到 domain 并用 `%3A` 编码。横向 API（`horizontal.py`）也复用此函数规范化 DID。

#### 3.4.2 统一报告格式

所有报告来自统一的 `malicious_reports` 表，由 `_format_report`（`malicious.py:41`）格式化：

```json
{
  "id": 1,
  "source": "protocol_review",
  "target_did": "did:wba:...",
  "node_type": "agent",
  "session_id": "...",
  "evidence_type": "identity_tampering",
  "severity": "high",
  "taint_score": 0.0,
  "evidence_description": "...",
  "nonce": "...",
  "report_id": null,
  "timestamp": 1234567890.0,
  "raw_evidence": {}
}
```

三种来源（`source`）：

| `source` 值 | 说明 | 写入方 |
|-------------|------|--------|
| `protocol_review` | 双轮回溯确认中由 `MaliciousNodeDetector` 检测到 | `middleware` / `_periodic_sweep` |
| `vertical_analysis` | 纵轴 R_T 单点告警（s_i > R_T） | `VerticalOrchestrator._notify_rt_alert` |
| `horizontal_analysis` | 横轴跨会话确认恶意 | `HorizontalOrchestrator._notify_confirmed` |

#### 3.4.3 端点说明

**统一报告查询**：

```
GET /api/malicious/reports?session_id=...&did=...&source=vertical_analysis&limit=100
→ {
    "total": 1,
    "reports": [_format_report(...)]
  }
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | query, 可选 | 按 session 筛选 |
| `did` | query, 可选 | 按 DID 筛选（自动 `_normalise_did`） |
| `source` | query, 可选 | `protocol_review` / `vertical_analysis` / `horizontal_analysis` |
| `limit` | query, 默认 100（1-1000） | 返回数量上限 |

**单个节点档案（dossier）**：

```
GET /api/malicious/dossier/{did}
→ {
    "found": true,
    "did": "...",
    "total_violations": 3,
    "severity_level": "warning",       // clean/warning/dangerous/banned
    "first_seen_at": ..., "last_seen_at": ...,
    "evidence_breakdown": {...},        // 各 evidence_type 计数
    "source_breakdown": {...},          // 各 source 计数（v0.3.0 新增，由 incidents 现算）
    "last_evidence_type": "...",
    "last_session_id": "...",
    "last_evidence_desc": "...",
    "incidents": [...]                  // 该 DID 全部违规明细（_format_report）
  }
```

未找到时返回 `{"did": "{did}", "found": false}`。

**全部档案**：

```
GET /api/malicious/dossiers?severity=warning&source=protocol_review&limit=100
→ { "total": 5, "dossiers": [...] }
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `severity` | query, 可选 | 按严重等级筛选（clean/warning/dangerous/banned） |
| `source` | query, 可选 | 按来源筛选（透传到 `query_all_dossiers`） |
| `limit` | query, 默认 100（1-1000） | 返回数量限制 |

每条档案附带 `source_breakdown`（各来源违规计数），便于前端打标签。

### 3.5 行为溯源查询 API（trace）

`api/trace.py` 提供健康检查与行为溯源链查询。

**健康检查**：

```
GET /api/status → {"status": "ok", "service": "protocol_node"}
```

**行为溯源链**（`get_behavior_trace`，`trace.py:31`）：

```
GET /api/behavior/{session_id}?protocol_node_address=...
→ {
    "session_id": "...",
    "protocol_node_address": "...",
    "chain": [
      {
        "hop_count": [0, 0],
        "field_type": "U2A",
        "sender_type": "user",           // 由 field_type 首字母映射
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

异常时返回空 chain（不抛 500），便于前端降级。

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

### 3.7 消息固化层完整数据流

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
      │                             │                     Branch A:│
      │                             │                     Step 1-3 基础验证/DID/nonce│
      │                             │                       → 无暂存消息│
      │                             │                     验证B身份签名│
      │                             │                     暂存为 PendingMessage│
      │                             │                     返回 "stored"│
      │                             │                            │
      │  ③ BackMessage Phase 2      │                            │
      │  (A 签名 identity +         │                            │
      │   发送内容副本)               │                            │
      ├─────────────────────────────────────────────────────────→│
      │                             │                     Branch B:│
      │                             │                     Step 1-3 基础验证/DID/nonce│
      │                             │                       → 匹配到暂存│
      │                             │                            │
      │                             │                     Step 4 恶意节点判定│
      │                             │                       0a→0b→1→2→3→4→4b│
      │                             │                  [检测到恶意]│
      │                             │                  → save_malicious_report│
      │                             │                  → 返回 403  │
      │                             │                  [无恶意]    │
      │                             │                     Step 5 verify_back_propagation│
      │                             │                     Step 6 行为推断 + hop_count 校验│
      │                             │                     Step 7 更新可信名单│
      │                             │                            │
      │                             │                  save_behavior_entry → trace_id│
      │                             │                  behavior_controller.handle│
      │                             │                  [可选] orchestrator.enqueue_trace│
      │                             │                     → 投入会话有界队列（不等 LLM）│
      │                             │                  返回 200   │
      │                             │                            │
      │                             │             （后台）纵轴 worker 消费队列：│
      │                             │               U2A → 抽意图 / 动作跳 → 打分│
      │                             │               s_i > R_T → 告警；sub-R_T → 喂横轴 F│
```

---

## 4. 意图追踪层（逐跳有状态改版）

意图追踪层采用**十字锁定（Cross-Lock）架构**，通过可选集成的 `CrossLockCoordinator` 实现 LLM 驱动的语义偏离检测。v0.3.0 重构为**逐跳有状态模型**：

- **纵轴（Session-Level）**：每条动作跳由 V-Reasoner 打分 s_i∈[0,10]（4 维 max 聚合）；`s_i > R_T` 立即告警；同时维护滚动隐状态 h_i 与 append-only 意图流。
- **横轴（DID-Level）**：纵轴每打一跳分即回报横轴 `on_hop_scored`，per-DID 累加 `F=Σs²`（纯平方和，无死区/折扣/封顶）；`F > R_S` 且累积跳数达标即触发跨会话确认。
- **完全异步**：`/record` 落库后只把该跳投入会话有界队列即返回，LLM 调用在后台 worker 进行，绝不阻塞回传验证。

> 已移除（相对旧版）：Chain Verifier、基于计数的「累计 N 次触发」、`/record` 中同步 await LLM、批次化（report_batch_size）/累积阈值（accumulation_threshold）配置项。

### 4.1 CrossLockCoordinator 集成与生命周期

#### 4.1.1 构建条件

`ProtocolNode._build_orchestrator`（`node.py:205`）：

```python
def _build_orchestrator(self):
    analysis_cfg = self._config.analysis
    if not analysis_cfg.enabled or not analysis_cfg.api_key:
        return None  # 未启用或未配置 API Key
    # 构建 VerticalOrchestrator（逐跳评分）
    # 若 horizontal_enabled（默认 True）→ 同时构建 HorizontalOrchestrator
    # 用 CrossLockCoordinator 串联两轴（注入 _on_hop_scored 回调）
```

Coordinator 仅在以下条件同时满足时创建：

| 条件 | 配置字段 | 默认值 |
|------|---------|--------|
| 启用分析 | `analysis.enabled` | `false` |
| 配置 API Key | `analysis.api_key` | `""` |

横轴（HorizontalOrchestrator）额外条件：

| 条件 | 配置字段 | 默认值 |
|------|---------|--------|
| 横轴开关 | `analysis.horizontal_enabled` | `true`（仅当 enabled=True 时才生效） |

构建日志会打印 `(model, R_T, concurrency)` 与（启用横轴时）`(R_S, α, ρ)`。

#### 4.1.2 注入路径与纵横联动

```
ProtocolNode.start()
  │
  ├── _build_orchestrator() → CrossLockCoordinator
  │     ├── VerticalOrchestrator + VerticalAnalysisManager
  │     ├── HorizontalOrchestrator + HorizontalAnalysisManager [可选]
  │     └── CrossLockCoordinator(vertical, horizontal)
  │           └── 若 horizontal 非空：vertical._on_hop_scored_callback = coordinator._on_hop_scored
  │               （纵轴每打一跳分 → 自动喂横轴 F 累加）
  └── port.set_orchestrator(coordinator)
        │
        └── self._orch_holder[0] = coordinator
              │
              ├── record.py 通过 coordinator_holder[0] 访问（enqueue_trace）
              ├── vertical.py 通过 _coord_ref[0] 访问（trigger / llm-status）
              ├── horizontal.py 通过 _coord_ref[0] 访问（trigger / llm-status）
              └── cross_lock.py 只用 tracer（纯查询，不需 coordinator）
```

CrossLockCoordinator 对外接口（`core/analysis/cross_lock.py`）均为委托：

| 方法 | 委托对象 | 说明 |
|------|---------|------|
| `enqueue_trace(session_id, hop)` | vertical | `/record` 落库后调用，投入会话有界队列 |
| `trigger_analysis_async(session_id)` | vertical | 手动触发纵轴补打 |
| `get_analysis_status(session_id)` | vertical | 查询 worker 阶段（供 `/v/llm-status`） |
| `trigger_horizontal_async(did)` | horizontal（空则返回 `horizontal_disabled`） | 手动触发横轴确认 |
| `get_horizontal_status(did)` | horizontal | 查询确认任务状态（供 `/h/llm-status`） |
| `shutdown()` | 两者 | 停所有 worker（`ProtocolNode.stop` 调用） |

#### 4.1.3 配置模型

见第 5 章 `AnalysisConfig`。

#### 4.1.4 热重载

`ProtocolNode.reload_config`（`node.py:177`）：重新 `ProtocolNodeConfigFile.load` → 检测端口变更（仅 warning，需手动重启）→ `_build_orchestrator()` 重建 → `set_orchestrator` 注入。分析配置（含 enabled/api_key/阈值/并发/队列容量）可热更新；端口变更不生效。

### 4.2 逐跳异步评分管道

纵轴核心是 **per-session 有界队列 worker**（`core/analysis/vertical/orchestrator.py`）。`/record` 落库后调用 `coordinator.enqueue_trace(session_id, hop)`（`record.py:222`），其行为：

```
enqueue_trace(session_id, hop)               # vertical/orchestrator.py:80
  ├── _ensure_worker(session_id)             # 若该会话无 worker 则创建
  │     ├── asyncio.Queue(maxsize=queue_maxsize)   # 默认 1000
  │     ├── asyncio.Lock()                          # per-session 串行
  │     └── asyncio.create_task(_worker_loop)
  └── queue.put_nowait(hop)
        └── QueueFull → 仅 warning 日志；hop 已在 DB，由 catch-up 扫描补打（不丢数据、不阻塞 /record）
```

**worker 循环**（`_worker_loop`，`vertical/orchestrator.py:146`）：

```
_worker_loop(session_id):
  try:
    async with lock: await _catchup_scan(session_id)   # 启动即补打崩溃前残留
    while True:
      phase = "idle"
      item = await wait_for(queue.get(), WORKER_IDLE_TIMEOUT=300s)
        └── TimeoutError → catch-up 扫描；仍无新增则退出 worker（下次 enqueue 重建）
      if item is _CATCHUP_SENTINEL:                    # 手动触发哨兵
          async with lock: await _catchup_scan(); continue
      hop = item
      if hop.trace_id <= cursor: continue              # catch-up 可能已处理，按游标去重
      phase = "scoring"
      async with lock: await _process_one(session_id, hop)
  except CancelledError: raise
  except Exception: log error
  finally: 清理 _workers / _phases
```

`_process_one`（`vertical/orchestrator.py:219`）按 `field_type` 分流（见 4.3 / 4.4），**成功或失败都推进打分游标**（`advance_score_cursor(trace_id)`），避免单跳失败卡死整条管线。

**全局并发限流**：`asyncio.Semaphore(concurrency)`（默认 8）——LLM 调用前 `async with self._sem`，即「同时处理的 hop 数」上限。

**catch-up 扫描**（`_catchup_scan`）：从 `last_scored_trace_id` 游标恢复所有未打分的 `behavior_traces`，逐条 `_process_one`。三个触发时机：worker 启动 / 队列空闲超时 / 手动触发（哨兵）。这保证队列溢出、进程崩溃后已落库但未打分的跳不会丢失。

### 4.3 意图流抽取（U2A 分流）

`_process_one` 见到 `field_type == "U2A"` 走 `_handle_u2a`（`vertical/orchestrator.py:236`）：

```
_handle_u2a(session_id, hop):
  state = state_mgr.get_state(session_id)
  initiator = state.initiator_did
  if not initiator:                          # 会话首条 U2A
      state_mgr.set_initiator_did(session_id, hop.sender_did)
      initiator = hop.sender_did
  if hop.sender_did != initiator:
      # 非发起者 U2A：不进意图流，但作为可疑行为照常打分
      # （第二个用户中途注入/越权引导是典型 d3 注入向量，丢弃会留盲区）
      await _handle_action(session_id, hop); return
  # 发起者 U2A → 抽意图增量 Δ（不打分）
  source = IntentRevisionSource(trace_id, did=sender_did, timestamp)
  async with sem:
      revision = analyzer.extract_intent_revision(content, intent_revisions, source)
  state_mgr.append_intent_revision(session_id, revision.to_dict())
  broker.publish(ANALYSIS_PROGRESS, phase="intent_appended")
```

意图流为 **append-only**：`I = [Δ_0, ..., Δ_m]` 只增不改，每条由发起者 DID 的 U2A 追加一个 `IntentRevision`（`core/analysis/base_models.py:131`）：

```python
@dataclass
class IntentRevision:
    goal: str
    constraints: list[str] = []
    prohibitions: list[str] = []
    source: IntentRevisionSource | None = None   # trace_id / did / timestamp
```

要点：
- 只有 **session 发起者 DID** 的 U2A 才能追加意图；非发起者 U2A 不被采信为意图，但照常打分。
- **U2A 不打分**（仅动作跳 A2A/A2T/T2A/A2U 打分）。
- 方法名是 `extract_intent_revision`（单数），每条 U2A 抽一个增量 Δ。

### 4.4 纵轴 R_T 单点告警

`_handle_action`（`vertical/orchestrator.py:272`）处理动作跳：

```
_handle_action(session_id, hop):
  state = state_mgr.get_state(session_id)
  intent_snapshot = state.intent_revisions     # 当前意图流快照
  hidden_prev = state.hidden_state             # 上一跳的 h_{i-1}
  async with sem:
      score = analyzer.score_hop(hop, intent_snapshot, hidden_prev)   # → HopScore
  if score is None: return                     # 评分失败，本次不做（游标已推进）
  tracer.save_hop_score(_hop_score_to_row(score))    # 落 hop_scores 表
  if score.hidden_state:
      state_mgr.set_hidden_state(session_id, score.hidden_state)   # 推进 h_i
  # R_T：单点立即告警
  if score.score > r_t:
      _notify_rt_alert(session_id, score)      # → save_malicious_report(source=vertical_analysis)
  # 报给横轴 F 累加 —— 仅 sub-R_T 的跳（轴职责分离）
  if _on_hop_scored_callback and score.score <= r_t:
      await _on_hop_scored_callback(sender_did, session_id, trace_id, score.score, field_type)
```

**轴职责分离**：`s_i > R_T` 的单跳恶由纵轴 R_T 告警抓；只有 **sub-R_T** 的跳才喂给横轴 F——避免 critical 重复计入 F 导致爆炸、横轴报告与 R_T 重复。F 专门抓「sub-R_T 累积的慢投毒」。

`_notify_rt_alert`（`vertical/orchestrator.py:312`）写入 `malicious_reports`：

```python
{
  "source": "vertical_analysis",
  "target_did": score.sender_did,
  "node_type": FIELD_TYPE_TO_SENDER_NODE_TYPE[field_type],
  "session_id": session_id,
  "evidence_type": score.deviation_type,
  "severity": score.severity,
  "taint_score": score.score,
  "evidence_description": " | ".join(evidence_items) or f"单跳评分 {score} 超过 R_T={r_t}",
  "raw_evidence": {trace_id, dimensions, breadth, evidence_items},
}
```

### 4.5 横轴 F 累加与跨会话确认

横轴（`core/analysis/horizontal/orchestrator.py`）是 **per-DID F 累加 + α 会话确认**。

**F 累加**（`on_hop_scored`，`horizontal/orchestrator.py:101`）：

```
on_hop_scored(did, session_id, trace_id, score, field_type):
  async with per-DID lock:
      f_delta = score ** 2                       # 纯平方和，无死区/折扣/封顶
      node_type = FIELD_TYPE_TO_SENDER_NODE_TYPE[field_type]
      f_value, volume = state_mgr.accumulate(did, f_delta, node_type)
  broker.publish(HORIZONTAL_ACCUMULATED, {f_value, volume, r_s, ...})
  # 触发条件：F > R_S 且累积跳数 ≥ _MIN_TRIGGER_VOLUME(=2)
  if f_value > r_s and volume >= _MIN_TRIGGER_VOLUME:
      triggered, reason = True, "f_threshold"
  elif f_value > r_s:
      # F 已越阈值但体积不足：F 保留累加，等下一跳达标再触发（不丢偏移量）
      log "Horizontal deferred"
  if triggered:
      broker.publish(HORIZONTAL_TRIGGERED, ...)
      await trigger_analysis_async(did, triggered_by=reason)   # fire-and-forget
```

> **最低体积门** `_MIN_TRIGGER_VOLUME = 2`（`horizontal/orchestrator.py:37`）：单跳 critical 已由纵轴 R_T 抓，横轴等累积 ≥2 跳才确认。此门只约束 `on_hop_scored` 的自动触发；手动 `/api/analysis/h/trigger/{did}` 不受限。

**确认主流程**（`run_analysis`，`horizontal/orchestrator.py:157`，由 `trigger_analysis_async` 在 per-DID 锁内 fire-and-forget 调用）：

```
run_analysis(did, triggered_by):
  state = state_mgr.get_state(did); cursor = state.last_trace_id
  phase = "selecting"
  hop_scores = tracer.query_hop_scores_by_did(did, cursor)
  if empty:
      若 F/volume 残留 → reset_accumulation（避免反复空触发）
      publish ANALYSIS_REPORT(triggered=False); return no_new_scores
  推导 node_type（agent 时由 _derive_node_type_from_scores 校正）
  # 选 α 个会话
  selected, w_map = _select_sessions(hop_scores)
  traces = storage.recover_traces_by_did_since(did, cursor)
  max_scored = max(trace_id of hop_scores)          # 游标按"已打分跳"推进（不用 traces.max）
  intents = _load_session_intents(selected, max_scored)   # 各会话截至本批的累积意图基准
  sessions_data = _build_sessions_data(...)          # 每会话 top 高分跳 + 意图基准
  if not sessions_data:
      state_mgr.close(did, max_scored, context); return no_selected_sessions
  # LLM 确认
  phase = "confirming"
  prior_report = _load_prior_report(did)             # 汇入上一次确认报告，防会话集拆分规避
  async with sem:
      verdict = analyzer.confirm(did, node_type, sessions_data,
                                  previous_context, prior_report)
  overall = _derive_overall(verdict)                 # confirmed+high→malicious; confirmed→suspicious; else clean
  报告 = ConfirmationReport(did, node_type, batch_index, from/to_trace_id,
                             sessions_scanned, selected_sessions, verdict, overall, ...)
  phase = "saving_results"
  report_row_id = storage.save_horizontal_report(report_json)
  if verdict.confirmed:
      _notify_confirmed(did, verdict, report_row_id)   # → malicious_reports(source=horizontal_analysis)
  state_mgr.close(did, max_scored, context=verdict.context_summary)   # 重置 F/体积、推进游标、记摘要
  publish ANALYSIS_REPORT(...)
```

**会话选择**（`_select_sessions`，`horizontal/orchestrator.py:266`）：

- 计算每个会话的 `W(σ) = Σ s_i²`（会话内所有 sub-R_T 跳的平方和）。
- 候选会话数 ≤ α（默认 10）→ 直接取全量。
- 否则按 `W(σ)` 降序取 α 个；并叠加**高危兜底**：任一跳 `s ≥ ρ`（默认 8.0）的会话无条件纳入，且**不占 α 名额**。

**告警**（`_notify_confirmed`）：确认存在跨会话攻击时写 `malicious_reports`，`source="horizontal_analysis"`，`evidence_type=verdict.threat_pattern`，含 `selected_sessions` 等原始证据。

> 闭案时无论确认与否都 `state_mgr.close(did, max_scored, context)`：重置 F/volume、推进游标到 `max_scored`、记录上下文摘要。良性闭案保留摘要以便下次确认时汇入（`prior_report`）。

### 4.6 评分量纲与结论推导（core/base_models）

`core/analysis/base_models.py` 定义了共享常量与**代码推导**逻辑（不让 LLM 下 severity / overall_verdict）：

| 常量 | 值 | 说明 |
|------|----|------|
| `SCORE_STEP` / `SCORE_MAX` | 0.5 / 10.0 | 分数步进（21 档）/ 上限 |
| `DIMENSION_NAMES` | `(intent_alignment, capability, injection_manipulation, exfiltration_tampering)` | 4 个正交评分维度（d1..d4） |
| `_SEVERITY_BANDS` | `<1.5 none, <3.5 low, <5.5 medium, <7.5 high, ≤inf critical` | severity 分档（左闭右开，末档闭） |
| `SEVERITY_HIGH_LOWER` / `SEVERITY_CRITICAL_LOWER` | 5.5 / 7.5 | high / critical 下沿（breadth 统计用） |

关键函数：

- `severity_for_score(score)`：由 [0,10] 分数推导 severity 档。
- `overall_verdict_for_severities(severities)`：**会话级 overall_verdict 推导**——任一跳 critical → `malicious`；任一跳 high → `suspicious`；否则 `clean`。被 vertical API 与 cross-lock API 调用。
- `aggregate_score(dims, p)`：聚合 4 维分为单跳 s_i。`p="max"`（默认）取最大维；`p="sum"` 取均值（基线）；数值 p 取 L^p 范数。
- `compute_breadth(dims)`：统计 ≥ `SEVERITY_HIGH_LOWER` 的维度数（仅归因用）。

`HopScore`（`base_models.py:165`）字段：`trace_id, session_id, sender_did, field_type, hop_count, score, dimensions[4], breadth, severity, deviation_type, evidence_items, hidden_state, timestamp`。

### 4.7 纵向分析 API 端点

`api/analysis/vertical.py`（prefix `/api/analysis/v`）提供逐跳评分相关端点。

#### 4.7.1 逐跳评分聚合报告

```
GET /api/analysis/v/report/{session_id}
→ {
    "session_id": "...",
    "initiator_did": "did:wba:...",
    "intent_revisions": [ {goal, constraints, prohibitions, source}, ... ],
    "hidden_state": "...",                 // 滚动隐状态 h_i（字符串）
    "hop_scores": [ {trace_id, score, dimensions, severity, deviation_type, ...}, ... ],
    "overall_verdict": "clean",            // 代码推导（overall_verdict_for_severities）
    "max_score": 7.5,
    "total_hops": 12,
    "last_scored_trace_id": 20
  }
```

`overall_verdict` 与 `max_score` 都在 API 层由 hop_scores 现算（不存库）。异常时返回 `{session_id, hop_scores: [], total_hops: 0}`。

#### 4.7.2 意图流与隐状态

```
GET /api/analysis/v/state/{session_id}
→ {
    "session_id": "...",
    "initiator_did": "...",
    "intent_revisions": [...],
    "has_hidden_state": true,
    "last_scored_trace_id": 20,
    "intent_revision_count": 2
  }
```

状态从 `tracer.load_vertical_state(session_id)` 异步读取（`_astate`，`vertical.py:25`），解析 `intent_revisions_json`。

#### 4.7.3 聚合视图（traces + hop_scores + R_T 告警）

```
GET /api/analysis/v/aggregate/{session_id}?protocol_node_address=...
→ {
    "session_id": "...",
    "traces": {"chain": [...], "total_entries": 15},
    "hop_scores": [...],
    "overall_verdict": "suspicious",
    "alerts": [...],                      // source=vertical_analysis 的恶意报告（R_T 告警）
    "total_hops": 12,
    "total_alerts": 1
  }
```

`alerts` 来自 `tracer.query_malicious_reports(session_id, source="vertical_analysis")`。

#### 4.7.4 手动触发纵向分析

```
POST /api/analysis/v/trigger/{session_id}
→ {"triggered": true, "status": "running", "session_id": "..."}
或 {"triggered": false, "reason": "analysis_disabled"}
```

委托 `coordinator.trigger_analysis_async`（投哨兵触发 catch-up 扫描，补打未评分跳），立即返回。

#### 4.7.5 纵向 worker 状态

```
GET /api/analysis/v/llm-status/{session_id}
→ {"status": "running", "phase": "scoring", "queue_depth": 3, "session_id": "..."}
或 {"status": "idle", "session_id": "..."}
或 {"status": "disabled", "session_id": "..."}    // coordinator 未启用
```

`phase` 取自 worker 的 `_phases`（`idle` / `scoring`）。该端点供前端轮询；SSE 启用后可被 `/api/events` 推送替代。

### 4.8 横向分析 API 端点

`api/analysis/horizontal.py`（prefix `/api/analysis/h`）。

#### 4.8.1 DID 横向确认报告

```
GET /api/analysis/h/report/{did}
→ {
    "did": "did:wba:...",          // 规范化后
    "reports": [
      {
        "id": 1, "batch_index": 0,
        "from_trace_id": 1, "to_trace_id": 50,
        "sessions_scanned": 3,
        "timestamp": ...,
        "report": {                 // 解析自 report_json（ConfirmationReport）
          "did", "node_type", "verdict": {confirmed, severity, threat_pattern, ...},
          "overall_verdict": "suspicious",
          "selected_sessions": [...], "summary": "...", ...
        }
      }
    ],
    "total_batches": 1
  }
```

数据来自 `storage.recover_horizontal_reports(canonical)`。

#### 4.8.2 DID 横向累积状态

```
GET /api/analysis/h/state/{did}
→ {
    "did": "...",
    "f_value": 30.25,        // 累积 F=Σs²
    "volume": 2,             // 自上次闭案以来的 hop 数
    "last_trace_id": 50,     // 确认游标
    "batch_index": 0,        // 已完成确认次数
    "node_type": "agent",
    "has_context": true      // 是否有上下文摘要
  }
```

无状态时返回各字段默认值（`f_value=0.0, volume=0, ...`）。

#### 4.8.3 横向确认任务状态

```
GET /api/analysis/h/llm-status/{did}
→ {"status": "running", "phase": "confirming", "did": "..."}
或 {"status": "completed", "triggered": true, "report": {...}}
或 {"status": "not_found", "did": "..."}
或 {"status": "disabled", "did": "..."}    // coordinator 未启用
```

`phase` 取值：`starting` / `selecting` / `confirming` / `saving_results`（由 `_set_phase` 发布，同时经 SSE 推 `ANALYSIS_PROGRESS`）。

#### 4.8.4 手动触发横向确认

```
POST /api/analysis/h/trigger/{did}
→ {"triggered": true, "status": "running", "did": "..."}
或 {"triggered": true, "status": "already_running", "did": "..."}
或 {"triggered": false, "reason": "analysis_disabled"}
```

委托 `coordinator.trigger_horizontal_async`。注意手动触发**不受** `_MIN_TRIGGER_VOLUME` 限制。

### 4.9 十字锁定综合视图 API

`api/analysis/cross_lock.py`（prefix `/api/analysis`）提供一个聚合端点，把纵向逐跳评分与涉及各 DID 的横向 F/volume 放在一张视图里：

```
GET /api/analysis/cross-lock/{session_id}?protocol_node_address=...
→ {
    "session_id": "...",
    "vertical": {
      "traces": 15,                       // trace 条数
      "hop_scores": [...],
      "overall_verdict": "suspicious",    // 代码推导
      "total_hops": 12,
      "alerts": [...]                     // source=vertical_analysis
    },
    "horizontal": {
      "tracked_dids": [
        {
          "did": "...",
          "f_value": 30.25, "volume": 2, "batch_index": 0,
          "last_horizontal_analysis": {   // 最近一次确认报告摘要
            "batch_index": 0, "confirmed": true,
            "overall_verdict": "malicious", "timestamp": ...
          }
        }
      ]
    }
  }
```

该端点纯查询（通过 `tracer` 直接读库），不依赖 coordinator 是否启用。横向 DID 列表取自本会话 trace 涉及的唯一 DID 集合。

### 4.10 SSE 事件流（`api/events.py`）

`GET /api/events` 是 SSE 推送端点（`events.py`），向用户端实时推送 trace / analysis / malicious / record 事件，替代前端轮询。本模块只做 **HTTP 接线**（`StreamingResponse` + 心跳循环），事件总线与帧序列化在 `core/sse.py`，从而保持 core 框架无关。

```
GET /api/events?session_id=...&did=...&topics=trace,analysis,malicious
```

| 参数 | 说明 |
|------|------|
| `session_id` | 仅接收该 session 的事件（trace / 纵向 analysis） |
| `did` | 仅接收该 DID 的事件（横向 analysis / malicious） |
| `topics` | 逗号分隔的 topic 列表 |

帧格式（标准 SSE）：`id: <单调递增>` / `event: <analysis.progress | analysis.report | malicious.detected | trace.recorded | ...>` / `data: <JSON>`。空闲时每 `HEARTBEAT_SECONDS=15.0` 秒发 `: ping` 心跳，防止反向代理关闭空闲连接。响应头包含 `Cache-Control: no-cache`、`X-Accel-Buffering: no`、`Connection: keep-alive`。

事件来源（由各组件 `broker.publish` 发起）：纵轴 worker（`ANALYSIS_PROGRESS` / intent_appended 等）、横轴（`HORIZONTAL_ACCUMULATED` / `HORIZONTAL_TRIGGERED` / `ANALYSIS_REPORT`）、`/record` 错误出口（`RECORD_ERROR`）、storage 的 trace/malicious 写入等。

---

## 5. 配置模型与热重载

### 5.1 配置模型层级

基于 Pydantic v2 的配置模型（`config/config.py`），`PNBase` 通过 `alias_generator=to_camel` + `populate_by_name=True` 支持 camelCase / snake_case 双格式键名。

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
  └── analysis: AnalysisConfig          （逐跳有状态改版）
        ├── enabled: bool = False
        ├── api_key: str = ""
        ├── base_url: str = "https://api.openai.com/v1"
        ├── model: str = "gpt-4o"
        ├── horizontal_enabled: bool = True       # 横轴开关（依赖 enabled=True）
        │
        ├── # 评分聚合
        ├── dimensions: int = 4                    # 正交维度数（见 base_models.DIMENSION_NAMES）
        ├── aggregation: str = "max"              # "max"(默认) / "sum" / 数值 p 的 L^p 范数
        │
        ├── # 阈值
        ├── r_t: float = 7.5                      # 单点阈值：s_i > R_T 立即告警
        ├── rho: float = 8.0                      # 横轴高危兜底：会话内任一跳 s_j ≥ ρ 无条件纳入确认
        ├── rho_k: float = 8.0                    # 单维 critical 下沿（max 聚合下与 r_t 自动一致；当前未在分析代码中独立使用）
        ├── r_s: float = 25.0                     # 累积阈值：F_d = Σ s_i² > R_S 触发横轴确认（纯平方和）
        ├── alpha: int = 10                       # 横轴确认上限：候选会话 > α 时按 W(σ) 取 α 个
        │
        ├── # 异步
        ├── concurrency: int = 8                  # 全局并发上限（同时处理的 hop 数）
        └── queue_maxsize: int = 1000             # 单会话有界队列容量（真背压）
```

> **已移除字段**（相对旧版）：`report_batch_size`、`accumulation_threshold`。逐跳改版后不再有「批次」概念，横轴改由 F 累加触发。
>
> `rho_k` 虽在配置中声明，但当前 `core/analysis/` 代码未独立读取它（max 聚合下 `s_i ≥ R_T` 已自动覆盖单维 critical），保留供后续 sum/L^p 聚合模式使用。

### 5.2 配置加载

```python
@classmethod
def load(cls, path: str | Path) -> ProtocolNodeConfigFile:   # config.py:82
    # 文件存在且有效 → 解析 JSON 并 model_validate
    # 文件不存在 → 返回默认值（并 log）
    # 解析失败 → log warning，返回默认值
```

`save(path)` 以 `by_alias=True`（camelCase）写出，自动 `mkdir -p`。`get_db_path()` 拼接 `data_dir/db_path`。

### 5.3 热重载

```python
async def reload_config(self) -> None:    # node.py:177
```

| 变化项 | 处理策略 |
|--------|---------|
| 端口（host/port） | 仅记录 warning，需手动重启生效 |
| 分析配置（enabled / api_key / 阈值 / 并发 / 队列容量等） | `_build_orchestrator()` 重建 CrossLockCoordinator（含纵轴 + [横轴]）并 `set_orchestrator` 注入 |

---

## 6. CLI 命令行接口

`cli.py` 提供 Protocol Node 的独立运行入口（`cli.py:21`）。注意子命令是 `protocol-node`（连字符）：

```bash
# 启动协议节点
attp protocol-node start --config path/to/config.json

# 生成默认配置文件
attp protocol-node init-config [--output path/to/config.json]
```

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `start` | `--config`（默认 `~/.attp/protocol_node/config.json`） | 启动协议节点服务 |
| `init-config` | `--output`（默认 `~/.attp/protocol_node/config.json`） | 生成默认配置文件（`ProtocolNodeConfigFile().save`） |

模块导入时即 `set_log_level("DEBUG")`。**启动流程**（`_run_standalone`，`cli.py:67`）：

```
main()
  └── _run_standalone(args)
        ├── ProtocolNode(config_path)
        ├── await node.start()
        ├── 注册 SIGINT/SIGTERM 信号处理（Windows 下 add_signal_handler 抛 NotImplementedError 时静默跳过）
        ├── await stop_event.wait()     # 阻塞直到 Ctrl+C
        └── await node.stop()
```

---

## 7. 错误码体系

`api/record.py` 中定义了 `ERROR_MAP`（`record.py:19`），将中间件错误码映射为 HTTP 状态码。`intercept_record` 返回的 `error` 字段格式为 `"<error_key>[:<detail>]"`，record 路由按 `error.split(":")[0]` 查表：

| 错误码 | HTTP 状态码 | 错误消息 | 触发条件 |
|--------|-----------|---------|---------|
| `missing_record_log` | 400 | Missing Record_Log | — |
| `hop_validation` | 400 | Hop validation failed | 基础字段不完整（Step 1） |
| `did_resolution_failed` | 404 | DID resolution failed | DID 公钥解析失败（Step 2） |
| `missing_type_field` | 400 | Missing ATTPNodeType | DID 文档缺少节点类型 |
| `invalid_type` | 400 | Invalid ATTP node type | 节点类型不在 agent/tool/user 中 |
| `missing_nonce` | 400 | Missing nonce | — |
| `missing_identity_signature` | 400 | Missing Identity_Signature | — |
| `identity_signature_invalid` | 403 | Identity signature invalid | — |
| `sender_mismatch_not_self` | 403 | Sender mismatch | — |
| `receiver_mismatch` | 403 | Receiver mismatch | — |
| `back_propagation` | 403 | Back-propagation verification failed | 回传验证失败（签名/字节/哈希不一致，Step 5） |
| `invalid_type_combination` | 400 | Invalid type combination | sender/recv 类型组合不在 5 种合法映射中（Step 6） |
| `hop_count_violation_a2a` | 400 | Hop count violation (A2A: [0] must +1, [1] must be 0) | A2A 跳 hop_count 不符合 `[max+1, 0]` |
| `hop_count_violation_non_a2a` | 400 | Hop count violation (non-A2A: [0] must stay, [1] must +1) | non-A2A 跳 hop_count 不符合递增规则 |
| `hop_zero_must_be_u2a` | 400 | hop_count=[0,0] must be U2A (user intent) | 首条消息类型错误 |
| `content_signature_invalid` | 403 | Content signature invalid | — |
| `trusted_list_violation` | 403 | Trusted list violation | — |

未命中表的错误码回退为 `(500, result.error)`。所有 error 出口都会发布 `record.error` SSE 事件（若 broker 存在），便于前端实时感知失败。

---

## 8. API 端点汇总

### 8.1 Record 接收

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/record` | 接收并处理 BackMessage（双轮回溯确认入口，verified 后异步入队评分） |

### 8.2 行为溯源与健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 健康检查 |
| GET | `/api/behavior/{session_id}` | 行为溯源链查询 |

### 8.3 纵向分析（`/api/analysis/v`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/analysis/v/report/{session_id}` | 逐跳评分聚合报告（含 overall_verdict，代码推导） |
| GET | `/api/analysis/v/state/{session_id}` | 意图流 / 隐状态 / 打分游标 / 发起者 DID |
| GET | `/api/analysis/v/aggregate/{session_id}` | traces + hop_scores + R_T 告警聚合 |
| POST | `/api/analysis/v/trigger/{session_id}` | 手动触发纵轴（补打未评分跳） |
| GET | `/api/analysis/v/llm-status/{session_id}` | 纵向 worker 状态（供轮询） |

### 8.4 横向分析（`/api/analysis/h`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analysis/h/trigger/{did}` | 手动触发横轴确认（异步，不受体积门限制） |
| GET | `/api/analysis/h/report/{did}` | DID 全部横轴确认报告 |
| GET | `/api/analysis/h/state/{did}` | F / volume / 游标 / 批次 |
| GET | `/api/analysis/h/llm-status/{did}` | 横轴确认任务状态（供轮询） |

### 8.5 十字锁定综合视图

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/analysis/cross-lock/{session_id}` | 纵向 hop_scores + 各 DID 横向 F/volume 聚合视图 |

### 8.6 SSE 事件流

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/events` | SSE 推送（session_id / did / topics 过滤，15s 心跳） |

### 8.7 恶意节点查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/malicious/reports` | 统一报告查询（session_id / did / source / limit 组合筛选） |
| GET | `/api/malicious/dossier/{did}` | 单个节点档案（含 evidence_breakdown + source_breakdown + incidents） |
| GET | `/api/malicious/dossiers` | 全部节点档案（severity / source 筛选，附 source_breakdown） |

---

## 9. 设计模式与总结

### 9.1 设计模式

| 模式 | 应用场景 | 说明 |
|------|---------|------|
| **Facade（门面）** | `ProtocolNode` | 封装所有组件的创建和生命周期管理，对外仅暴露 `start()/stop()` |
| **Coordinator（协调器）** | `CrossLockCoordinator` | 串联纵轴逐跳评分与横轴 F 累加；通过 `_on_hop_scored_callback` 注入实现纵横联动 |
| **Pipeline（管道）** | `middleware.intercept_record()` | 多步顺序验证管线，每步可提前终止 |
| **Strategy（策略）** | `BehaviorController`；横轴按 `node_type` 选择确认策略 | 按 node_type 分发；纵横确认 agent/tool/user 隔离 |
| **Decision Tree（决策树）** | `MaliciousNodeDetector` | 双回传 7 步（0a→4b）+ 单回传 3 分支的树形判定 |
| **Producer-Consumer（有界队列）** | 纵轴 per-session worker | `asyncio.Queue(maxsize)` + per-session worker，真背压；catch-up 扫描保证不丢数据 |
| **Late Binding（延迟绑定）** | `orch_holder: list` / `_coord_ref: list` | 使用可变容器实现 CrossLockCoordinator 的延迟注入与热替换 |
| **Repository** | Core 层 `SqliteStore` | 数据访问抽象，Protocol Node 通过 `ProtocolTracer` 间接访问 |
| **Observer（观察者）** | `EventBroker` + SSE | 纵横 worker / storage / record 路由发布事件，`/api/events` 订阅推送 |
| **State Manager** | `VerticalAnalysisManager` / `HorizontalAnalysisManager` | 将意图流 / 隐状态 / 游标 / F 累积状态从编排器中解耦并持久化 |

### 9.2 架构特点

| 特点 | 说明 |
|------|------|
| **自包含设计** | 传入 `config_path` 即可运行，内部自行加载配置、创建所有依赖 |
| **存储前置** | Branch A 始终暂存，不拒绝，将安全判定延迟到 Branch B |
| **双层恶意检测** | 双回传（实时判定）+ 单回传（过期判定），覆盖所有消息丢失场景 |
| **逐跳异步评分** | `/record` 落库后只投入会话有界队列即返回，LLM 在后台 worker 进行；队列满/崩溃由 catch-up 扫描补打，不阻塞、不丢数据 |
| **轴职责分离** | R_T 抓单跳 critical（纵轴实时告警），F 抓 sub-R_T 累积慢投毒（横轴跨会话确认）；两者不重复 |
| **代码推导结论** | severity 档、overall_verdict 均由 `base_models` 的函数推导，不让 LLM 下判定 |
| **统一恶意报告** | 协议审查 / 纵向 R_T 告警 / 横向确认三个来源写同一张 `malicious_reports` 表，API 支持 `source` 筛选与 `source_breakdown` |
| **实时推送** | SSE（`/api/events`）替代前端轮询，覆盖 trace / analysis / malicious / record 全链路 |
| **可选分析集成** | CrossLockCoordinator 完全可选，未配置时不影响消息追踪功能 |
| **单端口架构** | 合并数据端口、API 端口、SSE 流，简化部署和网络配置 |
| **配置热重载** | 分析配置（含阈值/并发/队列/纵横开关）可热更新；端口变更需手动重启 |

### 9.3 与 Core 层的关系

Protocol Node 是 Core 层的**上层编排者**：

| Core 层组件 | Protocol Node 使用方式 |
|-------------|----------------------|
| `ProtocolTracer` | 溯源链验证 + SQLite 存储门面（behavior_traces / hop_scores / malicious_reports / vertical_state / horizontal_*） |
| `ProtocolSessionManager` / `ProtocolSession` | per-session 验证状态（PendingMessage、可信名单、hop_count_map）+ 纵向隐状态（意图流 / h_i / 打分游标） |
| `DIDResolver` | DID → 公钥解析（带缓存） |
| `EventBroker`（`core/sse.py`） | SSE 事件总线，注入 storage 与各 API |
| `CrossLockCoordinator` | 可选集成，十字锁定意图追踪生命周期（纵轴逐跳 + [横轴 F/确认]） |
| `VerticalOrchestrator` | per-session 有界队列 worker + 全局并发限流 + R_T 告警 |
| `HorizontalOrchestrator` | per-DID F 累加 + α 会话选择 + 跨会话确认 |
| `VerticalAnalysisManager` / `HorizontalAnalysisManager` | 纵横分析状态持久化 |
| `base_models`（评分常量与推导函数） | severity / overall_verdict / aggregate_score 等代码推导 |
| `ChainManager.verify_back_propagation` | 回传验证（签名 → 字节比对 → 哈希一致性） |

Protocol Node 本身不实现加密算法、哈希计算或数据库访问，这些全部委托给 Core 层。Protocol Node 的核心价值在于**验证管线编排**、**恶意节点判定决策树**、**逐跳异步评分管道**和**十字锁定纵横联动**的实现。
