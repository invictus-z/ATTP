# ATTP 消息通信规范化

## 概述

ATTP 通信层使用三个结构化类规范所有消息格式，定义在 `attp.core.message.event` 中：

- **RecordedHop** — 单跳记录，嵌入 NodeMessage / BackMessage
- **NodeMessage** — 节点间转发消息（A → B）
- **BackMessage** — 回传消息（节点 → 协议节点）

---

## 消息类型定义

### RecordedHop

单跳记录内容，嵌入在 NodeMessage 和 BackMessage 中。

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | str | 会话标识 |
| `sender_did` | str | 发送方 DID |
| `target_did` | str | 接收方 DID |
| `content` | str | 消息内容（结构化 JSON 字符串） |
| `timestamp` | float | Unix 时间戳 |
| `hop_count` | list[int] | 跳数计数 [大跳数, 小跳数]，从 [0, 0] 开始 |
| `sig_content` | str | 发送方对其余字段的签名 |

`sig_content` 的签名输入为 SHA-256(`session_id` + `sender_did` + `target_did` + `content` + `timestamp` + `hop_count`)，由**发送方私钥**签署。

### NodeMessage

A 向 B 发送的节点间转发消息。

| 字段 | 类型 | 说明 |
|---|---|---|
| `protocol_url` | str | 协议节点地址 |
| `nonce` | str | 唯一标识，匹配回传消息 |
| `recorded_hop` | RecordedHop | 单跳记录 |

### BackMessage

节点（A 或 B）向协议节点回传的消息。

| 字段 | 类型 | 说明 |
|---|---|---|
| `protocol_url` | str | 协议节点地址 |
| `node_did` | str | 回传节点的 DID |
| `nonce` | str | 唯一标识，匹配回传消息 |
| `sig_identity` | str | node_did + nonce 的私钥签名 |
| `recorded_hop` | RecordedHop | 单跳记录 |

`sig_identity` 的签名输入为 SHA-256(`node_did` + `nonce`)，由**回传节点自身私钥**签署，仅用于身份确认。

---

## 通信流程

```
A (Client)                           B (Server)                      Protocol Node
    |                                     |                               |
    |  NodeMessage.to_dict() -------->    |                               |
    |     (via remote.receive_message)    |                               |
    |                                     |                               |
    |                                     |  BackMessage.to_dict() -->    |
    |                                     |     ( B签identity)            |  暂存 (Branch A)
    |                                     |                               |
    |  BackMessage.to_dict()--------------|-----------------------------> |
    |     ( A签identity)                  |                               |  匹配验证 (Branch B)
    |                                     |                               |  行为记录保存
```

### 阶段说明

**1. A → B 发送（NodeMessage）**

A 构造 `NodeMessage`，通过 OpenANP SDK 的 `remote.receive_message()` 发给 B。

- `recorded_hop.sig_content` 由 A 的私钥签署（内容完整性）
- `nonce` 由 A 生成（UUID），B 在回传时原样携带

**2. B → 协议节点回传（Phase 1）**

B 收到 NodeMessage 后，构造 `BackMessage` 向 A 的协议节点回传接收确认。

- `node_did` = B 的 DID
- `sig_identity` 由 B 的私钥签署（B 的身份确认）
- `recorded_hop` 原样携带 A 签的内容
- `recorded_hop.sig_content` 仍是 A 的签名（未修改）

协议节点收到后进入 **Branch A**：暂存为 PendingMessage，等待 Phase 2 到达。

**3. A → 协议节点回传（Phase 2）**

A 发送消息后，构造 `BackMessage` 向自己的协议节点发送 record 副本。

- `node_did` = A 的 DID
- `sig_identity` 由 A 的私钥签署（A 的身份确认）
- `recorded_hop` 与发给 B 的内容一致

协议节点收到后进入 **Branch B**：与 Branch A 暂存的 PendingMessage 通过 nonce 匹配，验证内容一致性。

---

## 签名体系

| 签名 | 签名内容 | 签署者 | 用途 |
|---|---|---|---|
| `sig_content` | SHA-256(session_id, sender_did, target_did, content, timestamp, hop_count) | 发送方 A | 内容完整性，防篡改 |
| `sig_identity` | SHA-256(node_did, nonce) | 回传节点自身 | 身份确认 |

两个签名职责分离：`sig_content` 保证内容不变，`sig_identity` 保证是谁在回传。

---

## 协议节点验证管道(待完善，未修改)

协议节点 DataPort 收到 BackMessage 后，middleware 执行 4 步验证：

### Step 1 — 基础字段验证

校验 BackMessage 所有字段非空、类型合法（hop_count >= 0、timestamp > 0）。

### Step 2 — 身份与签名验证

1. DID 解析 `node_did` → 获取公钥 + 节点类型
2. `back_msg.verify_identity(public_key)` — 验证回传节点身份
3. DID 解析 `recorded_hop.sender_did` → 获取发送方公钥
4. `back_msg.verify_content(public_key)` — 验证内容签名

### Step 3 — Nonce 会话分支

- **Branch A**（首次到达）：暂存为 PendingMessage
- **Branch B**（匹配到达）：
  - 校验 stored_msg.target_did == 当前 node_did
  - 验证内容一致性（`verify_back_propagation`）
  - 推断行为类型（A2T / A2U / U2A / A2A / T2A）
  - Hop count 递增校验

### Step 4 — 行为记录

验证通过后保存 BehaviorEntry，U2A 类型触发 intent 提取。

---

## 错误码

| 错误码 | HTTP | 说明 |
|---|---|---|
| `hop_validation` | 400 | 字段校验失败 |
| `did_resolution_failed` | 404 | DID 解析失败 |
| `missing_type_field` | 400 | 缺少节点类型 |
| `invalid_type` | 400 | 无效节点类型 |
| `missing_nonce` | 400 | 缺少 nonce |
| `missing_identity_signature` | 400 | 缺少身份签名 |
| `identity_signature_invalid` | 403 | 身份签名验证失败 |
| `content_signature_invalid` | 403 | 内容签名验证失败 |
| `receiver_mismatch` | 403 | 接收方不匹配 |
| `back_propagation` | 403 | 回传内容验证失败 |
| `invalid_type_combination` | 400 | 无效行为类型组合 |
| `hop_count_violation_a2a` | 400 | A2A 跳数未递增 |
| `hop_count_violation_non_a2a` | 400 | 非A2A 跳数不一致 |
| `hop_zero_must_be_u2a` | 400 | hop_count=0 必须为 U2A |

---

## 涉及文件

| 文件 | 职责 |
|---|---|
| `attp/core/message/event.py` | RecordedHop / NodeMessage / BackMessage 定义 |
| `attp/app/client.py` | 构造 NodeMessage 发送 + BackMessage Phase 2 |
| `attp/app/server.py` | 解析 NodeMessage + BackMessage Phase 1 |
| `attp/protocol_node/data_port.py` | 接收 BackMessage，分发到 middleware |
| `attp/protocol_node/middleware.py` | 4 步验证管道 |
| `attp/core/provenance/chain.py` | 签名一致性验证（verify_back_propagation） |
