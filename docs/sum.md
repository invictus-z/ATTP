# NodeMessage 行为溯源机制

## 概述

`NodeMessage` 是 ATTP 中的**行为溯源数据结构**，用于记录一个节点（Agent）在一次 hop 中发生的所有行为。它与 `BehaviorEntry` 配合，构成了完整的 A2T/A2U/U2A/A2A 四类交互追踪体系，为分布式 Agent 网络提供全链路审计能力。

---

## 核心数据结构

### BehaviorEntry — 单条行为记录

| 字段 | 类型 | 说明 |
|------|------|------|
| `field_type` | `str` | 行为类型，取值 `"A2T"` / `"A2U"` / `"U2A"` / `"A2A"` / `"T2A"` |
| `content` | `str` | 行为内容（消息文本、工具调用描述等） |
| `timestamp` | `float` | 行为发生的时间戳，默认 `time.time()` |
| `target` | `str` | 目标标识：A2T 类型为工具名，A2A 类型为目标 Agent DID，其余为空 |
| `extra` | `dict` | 扩展元数据 |

支持 `to_dict()` / `from_dict()` 序列化。

> 代码位置：[node_message.py:17-43](../src/attp_channel/sessions/node_message.py#L17-L43)

### NodeMessage — 一个节点在一次 hop 中的全部行为

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_did` | `str` | 当前节点的 DID 标识 |
| `session_id` | `str` | 所属会话 ID |
| `hop_count` | `int` | 当前 hop 序号 |
| `origin_did` | `str` | 消息最初发出者的 DID（溯源锚点） |
| `entries` | `list[BehaviorEntry]` | 本节点在本次 hop 中产生的所有行为条目 |

提供 `add_entry()` 方法追加行为条目，以及 `to_dict()` / `from_dict()` 序列化。

> 代码位置：[node_message.py:46-90](../src/attp_channel/sessions/node_message.py#L46-L90)

---

## 行为类型（field_type）

| 类型 | 方向 | 含义 | 记录位置 |
|------|------|------|----------|
| **A2T** | Agent → Tool | Agent 调用工具（如 nanobot 触发 send_message） | [client.py](../src/attp_channel/client.py) |
| **A2U** | Agent → User | Agent 向用户发送回复 | [app.py](../src/attp_channel/web_app/app.py) |
| **U2A** | User → Agent | 用户向 Agent 发送消息 | [app.py](../src/attp_channel/web_app/app.py) |
| **A2A** | Agent → Agent | Agent 之间互发消息 | [client.py](../src/attp_channel/client.py) |
| **T2A** | Tool → Agent | 工具返回结果（预留） | — |

---

## 系统架构与数据流

### 整体流向

```
用户输入(U2A) → 本地Agent → 工具调用(A2T) → 远程Agent(A2A) → 远程Agent回复
                    ↓                              ↓
              NodeMessage                     NodeMessage
              (session内存)                   (序列化传输)
                    ↓                              ↓
              SqliteStore                    record消息回传
              (行为持久化)                   → origin保存
```

### 各模块职责

#### 1. Session — NodeMessage 的生命周期管理

Session 通过 metadata 字典管理每个 hop 对应的 NodeMessage：

- **`get_or_create_node_message()`**：根据 hop_count 获取或创建 NodeMessage，存储 key 为 `"node_msg_{hop_count}"`
- **`get_node_message()`**：按 hop_count 检索已有的 NodeMessage
- **`_current_hop_count()`**：从 metadata 中的 `Hop` 字段推导当前 hop 序号

> 代码位置：[session.py:44-77](../src/attp_channel/sessions/session.py#L44-L77)

#### 2. ATTPClient — 行为记录与传播

客户端是行为记录的核心驱动方：

- **`_record_behavior()`** ([client.py:155-183](../src/attp_channel/client.py#L155-L183))：
  - 从 session 获取/创建 NodeMessage
  - 调用 `nm.add_entry()` 追加行为条目到内存中的 NodeMessage
  - 同时调用 `tracer.save_behavior_entry()` 持久化到 SQLite

- **`send_message()`** ([client.py:189-246](../src/attp_channel/client.py#L189-L246))：
  - 统一入口，先记录 **field A2T**（Agent→Tool），再按目标路由

- **`send_to_agent()`** ([client.py:252-363](../src/attp_channel/client.py#L252-L363))：
  - 记录 **field A2A**（Agent→Agent）
  - 获取完整 NodeMessage 并序列化到 record 消息的 metadata 中
  - 向 origin 发送 record 类型消息，携带 NodeMessage 副本用于溯源

#### 3. ATTPServer — 接收与持久化远端 NodeMessage

服务端在 `receive_message()` 中处理三种消息类型，其中 `record` 类型与 NodeMessage 相关：

```python
# server.py:225-235
node_msg_data = metadata.get("NodeMessage")
if node_msg_data:
    node_message = NodeMessage.from_dict(node_msg_data)
    active_tracer.save_node_message(node_message)
```

流程：从 metadata 反序列化 NodeMessage → 通过 tracer 批量持久化到 SQLite。

> 代码位置：[server.py:217-253](../src/attp_channel/server.py#L217-L253)

#### 4. WebApp — 用户侧行为记录（field A2U/U2A）

Web UI 层负责记录用户与 Agent 之间的交互：

- **`_record_field_b()`** ([app.py](../src/attp_channel/web_app/app.py))：Agent→User（A2U），在 `record_message()` 中触发，排除节点间消息通知
- **`_record_field_c()`** ([app.py](../src/attp_channel/web_app/app.py))：User→Agent（U2A），在 WebSocket 收到用户 chat 消息时触发

两者逻辑一致：获取/创建 NodeMessage → add_entry → tracer 持久化。

#### 5. MessageTracer — 门面模式统一接口

`MessageTracer` 组合了 KeyStore、ChainManager、SqliteStore 三个子模块：

- **`save_behavior_entry()`**：单条行为持久化（委托 SqliteStore）
- **`save_node_message()`**：批量持久化 NodeMessage 中的所有 entries（委托 SqliteStore）
- **`recover_behavior_trace()`**：按 session_id + origin_did 恢复完整行为链

> 代码位置：[tracer.py:50-65](../src/attp_channel/protocol/tracer.py#L50-L65)

#### 6. SqliteStore — 持久化层

存储表 `behavior_traces` 结构：

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | INTEGER PK | 自增主键 |
| `session_id` | TEXT | 会话 ID |
| `origin_did` | TEXT | 消息源 DID |
| `node_did` | TEXT | 行为发生节点 DID |
| `hop_count` | INTEGER | hop 序号 |
| `field_type` | TEXT | A2T/A2U/U2A/A2A/T2A |
| `content` | TEXT | 行为内容 |
| `target` | TEXT | 目标标识 |
| `timestamp` | REAL | 时间戳 |
| `extra` | TEXT | JSON 扩展数据 |

索引：`(session_id, origin_did)` 和 `(session_id, origin_did, hop_count)`

两种持久化方式：
- `save_behavior_entry()`：逐条插入，用于本地实时记录
- `save_node_message()`：批量插入 NodeMessage 的全部 entries，用于接收远端 record 时一次性写入

> 代码位置：[sqlite_store.py:21-134](../src/attp_channel/protocol/storage/sqlite_store.py#L21-L134)

---

## NodeMessage 的传播路径

以 Agent A 调用 Agent B 为例：

```
1. Agent A 的 Client.send_message()
   └─ _record_behavior(field_type="A2T")  → 本地 NodeMessage + SQLite
   └─ send_to_agent()
       └─ _record_behavior(field_type="A2A")  → 本地 NodeMessage + SQLite
       └─ session.get_node_message(hop_count)  → 获取完整 NodeMessage
       └─ remote.receive_message()  → 发送请求到 Agent B
       └─ origin_remote.receive_message(type="record")  → 携带 NodeMessage 副本回传 origin

2. Agent B 的 Server.receive_message(type="record")
   └─ NodeMessage.from_dict(metadata["NodeMessage"])  → 反序列化
   └─ tracer.save_node_message(node_message)  → 批量写入 Agent B 的 SQLite
```

---

## API 查询接口

**`GET /api/behavior/{session_id}?origin_did=xxx`**

返回完整行为追踪，按 hop_count 分组，每组包含各类型行为条目：

```json
{
  "session_id": "...",
  "origin_did": "...",
  "nodes": [
    {
      "hop_count": 0,
      "node_did": "did:wba:...",
      "A2T": [{"content": "...", "target": "...", "timestamp": 1234.5}],
      "A2U": [],
      "U2A": [{"content": "...", "target": "", "timestamp": 1234.6}],
      "A2A": []
    }
  ]
}
```

> 代码位置：[trace.py:10-52](../src/attp_channel/web_app/api/trace.py#L10-L52)

---

## 关键代码索引

| 文件 | 核心内容 |
|------|----------|
| [node_message.py](../src/attp_channel/sessions/node_message.py) | `BehaviorEntry` 和 `NodeMessage` 数据类定义 |
| [session.py](../src/attp_channel/sessions/session.py) | Session 中 NodeMessage 的创建/获取/存储 |
| [client.py](../src/attp_channel/client.py) | Client 侧行为记录（field A2T/A2A）与 NodeMessage 传播 |
| [server.py](../src/attp_channel/server.py) | Server 侧接收远端 NodeMessage 并持久化 |
| [app.py](../src/attp_channel/web_app/app.py) | Web UI 侧行为记录（field A2U/U2A） |
| [tracer.py](../src/attp_channel/protocol/tracer.py) | MessageTracer 门面，统一调度存储 |
| [sqlite_store.py](../src/attp_channel/protocol/storage/sqlite_store.py) | SQLite 持久化，behavior_traces 表 |
| [trace.py](../src/attp_channel/web_app/api/trace.py) | 行为追踪查询 API |