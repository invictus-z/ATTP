# ATTP 实验

---

## O、数据集结构（按用途四类）

| 类别 | sid 区间 | 数量 | 用途 |
|---|---|---|---|
| train_R_T | rt001–rt095 | 95 | 标定纵向检出阈值 R_T（v 单跳攻击 + c 干净做 FPR） |
| train_R_S | rs001–rs087 | 87 | 标定横向触发阈值 R_S（慢投毒/subtle，每场景 25-30 跳累积） |
| test | te001–te092 | 92 | 混杂真实场景测试（8 种 attack_type 均衡 + 干净共存 + 慢性投毒） |
| 横向分析 | 复用 rs* | — | 离线复用 train_R_S 纵向库跑 H-Reasoner confirm |

共 274 个场景。

---

## 一、train_R_T 测试集下纵向分析的 F1 矩阵
train_R_T 95 场景，718 条行为，选定R_T=7.0
| 模型 | 行为P | 行为R | **行为F1** | 行为FPR | 节点R |
|---|---|---|---|---|---|
| glm-4.6 | 0.991 | 0.782 | **0.874** | 0.005 | 0.967 |
| gemini-3.1-flash-lite | 0.973 | 0.775 | **0.863** | 0.014 | 1.000 |
| claude-sonnet-5 | 0.973 | 0.761 | **0.854** | 0.014 | 1.000 |
| qwen3.7-plus | 0.958 | 0.739 | **0.835** | 0.021 | 0.983 |
| gpt-5.4 | 0.965 | 0.682 | **0.799** | 0.016 | 0.983 |
| MiniMax-M3 | 0.989 | 0.639 | **0.777** | 0.005 | 0.967 |

**R_T选定原则**：F1 最优 R_T 为 4.5-5.0，但会增加误报率，以及破坏轴分离（跨会话攻击 5-6 分跳被纵轴直接抓走，横向失效）。 能做到确认显性恶意，低误报即可。**最佳**即7.0，F1分数不低且满足原则。

---
## 二、train_R_S测试集下的R_S的选取

R_T=7.0 下各模型 R_S 标定（R0=0.95 召回）：

| 模型 | 推荐 R_S | 慢投毒召回 | 干净误送 FPR |
|---|---|---|---|
| qwen3.7-plus | 55 | 0.963 | **0.000** |
| MiniMax-M3 | 60 | 0.954 | 0.029 |
| gemini-3.1-flash-lite | 50 | 0.952 | 0.029 |
| glm-4.6 | 35 | 0.976 | 0.057 |
| claude-sonnet-5 | 30 | 0.965 | **0.229** |
| gpt-5.4 | 40 | 0.988 | 0.114 |

**R_S 选定原则**：对于跨会话攻击选取节点级，高召回，同时适当减少良性节点的触发频率。  
综合最佳 R_S ≈ 30~40

### 二补、累积公式（F=Σ sub-R_T s^p，p=1…4）对触发与横向 F1 的影响

> 仅 gemini，train_R_S（87 慢投毒 + clean），纯评测侧 + 正常触发机制的离线 confirm。
> 每公式各自标定最佳 R_S（R0=0.95 召回），再在该 R_S 下按**正常触发**（DID 的 sub-R_T 跳按时序累加，F>R_S 且累积≥2 跳触发一次、confirm 看**本触发批次**、reset 再累积）跑 gemini confirm。
> 触发模拟必须按时序(trace_id)，曾发现的"按分数排序"bug 已修（[rq_rs_formulas.py](../../intent_analysis/rq/rq_rs_formulas.py)）。

**(1) R_S 标定 × 公式**（recall 分母=恶意且有 sub-R_T 累积的场景 85；avg 调用=全 87 场景）

| 幂次 | 最佳 R_S | 慢投毒 R↑ | 干净 FPR↓ | 慢场景 avg 调用 | 干净场景 avg 调用 |
|---|---|---|---|---|---|
| linear (s¹) | 9 | 0.953 | 0.086 | 5.77 | 0.11 |
| s^1.5 | 23 | 0.953 | 0.029 | 4.90 | 0.03 |
| square (s²) | 45 | 0.953 | 0.057 | 5.13 | 0.06 |
| s^2.5 | 100 | 0.953 | 0.057 | 4.92 | 0.06 |
| cube (s³) | 200 | 0.953 | 0.057 | 5.17 | 0.06 |
| s^3.5 | 375 | 0.953 | 0.086 | 5.67 | 0.09 |
| s⁴ | 600 | 0.953 | 0.086 | 6.37 | 0.09 |

**(2) 节点级 F1 × 公式**（正常触发+confirm，每触发批次独立调 gemini，共 3299 次 confirm）

| 幂次 | R_S | P | R | F1 | FPR | TP/FP/FN/TN | avg 调用/场景 | avg 批次跳数/次 |
|---|---|---|---|---|---|---|---|---|
| linear (s¹) | 9 | 0.986 | 0.793 | 0.879 | 0.011 | 69/1/18/86 | 5.77 | 3.13 |
| s^1.5 | 23 | 0.973 | 0.839 | 0.901 | 0.023 | 73/2/14/85 | 4.90 | 3.55 |
| square (s²) | 45 | 0.973 | 0.839 | 0.901 | 0.023 | 73/2/14/85 | 5.13 | 3.38 |
| s^2.5 | 100 | 0.987 | 0.851 | 0.914 | 0.011 | 74/1/13/86 | 4.92 | 3.43 |
| **cube (s³)** | 200 | **1.000** | **0.874** | **0.933** | **0.000** | 76/0/11/87 | 5.17 | 3.30 |
| s^3.5 | 375 | 0.987 | 0.862 | 0.920 | 0.011 | 75/1/12/86 | 5.67 | 3.07 |
| s⁴ | 600 | 1.000 | 0.793 | 0.885 | 0.000 | 69/0/18/87 | 6.37 | 2.76 |

**结论**：
- **F1 随幂次呈倒 U，s³ 最优(0.933)**：s¹ 0.879 → s² 0.901 → s³ **0.933** → s⁴ 0.885。
- 两端召回都掉到 0.793 但**原因相反**：低次(s¹)批次被低分跳**稀释**→confirm 证据弱→漏判；高次(s⁴)单次极高分跳主导→触发太早、批次太小(2.76 跳/次)、调用最多(6.37/场景)→confirm 看不到连贯模式→漏判。s³ 折中(3.30 跳/次、高分聚集)→召回最高、**0 误报**。
- **精度随幂次升**：s³/s⁴ 达 P=1.000（高次让批次纯度高，confirm 几乎不误报良性）。
- 触发层面（谁送审）七公式都到 R=0.953、FPR 0.029–0.086，差异小；**节点级 F1 差异来自 confirm 输入批次的跳分聚集度**（高次聚集高分跳→证据强→判得准），但因 confirm 鲁棒，整体被压在 6pt F1 内。
- **当前 s²(F1 0.901) 稳妥；s³ 可再 +3pt F1 且零误报，值得考虑。**

脚本：[rq_rs_formulas.py](../../intent_analysis/rq/rq_rs_formulas.py)（标定）/ [rq_rs_trigger_f1.py](../../intent_analysis/rq/rq_rs_trigger_f1.py)（触发-confirm F1）。结果：[rq_rs_formulas.json](../../data/results/rq/gemini/rq_rs_formulas.json) / [rq_rs_trigger_f1.json](../../data/results/rq/gemini/rq_rs_trigger_f1.json)。

---
## 三、train_R_S 测试集下的横向分析的 F1 矩阵

横向分析与R_T和R_S无关，仅数据集离线复用train_R_S，87个场景，87个恶意节点，87个良性节点（测试时从中抽取61个）。

| 模型 | 恶意/良性节点 | TP | FP | FN | TN | P | **节点R** | **节点F1** | **节点FPR** |
|---|---|---|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 87/61 | 86 | 0 | 1 | 61 | 1.000 | 0.989 | **0.994** | **0.000** |
| claude-sonnet-5 | 87/61 | 86 | 0 | 1 | 61 | 1.000 | 0.989 | **0.994** | **0.000** |
| glm-4.6 | 87/61 | 83 | 0 | 4 | 61 | 1.000 | 0.954 | 0.976 | 0.000 |
| qwen3.7-plus | 87/61 | 82 | 0 | 5 | 61 | 1.000 | 0.943 | 0.970 | 0.000 |
| gpt-5.4 | 87/61 | 81 | 0 | 6 | 61 | 1.000 | 0.931 | 0.964 | 0.000 |
| MiniMax-M3 | 85/59 | 75 | 0 | 10 | 59 | 1.000 | 0.882 | 0.938 | 0.000 |

横向分析原则：不无辜良性节点，抓出跨会话恶意节点。

---

## 四、模型综合能力

| 模型 | 纵向行为F1 | 推荐R_S | 横向节点F1 | 横向节点R | 横向FPR |
|---|---|---|---|---|---|
| **gemini-3.1-flash-lite** | 0.863 | 50 | *0.994** | 0.989 | 0.000 |
| **claude-sonnet-5** | 0.854 | 30 | **0.994** | 0.989 | 0.000 |
| glm-4.6 | 0.874 | 35 | 0.976 | 0.954 | 0.000 |
| qwen3.7-plus | 0.835 | 55 | 0.970 | 0.943 | 0.000 |
| gpt-5.4 | 0.799 | 40 | 0.964 | 0.931 | 0.000 | 
| MiniMax-M3 | 0.777 | 60 | 0.938 | 0.882 | 0.000 | 

*gpt R_S=5 为个别慢投毒 F≈0 场景拖低，非系统性；clean 后应回升至 40-50。


---

> 以下为论文实验部分数
## RQ1:测消息固化

| Method | Fault Rec. ↑ | Benign Alarm ↓ |
|---|---|---|
| AgentTrace | 0.000  | 0.600  |
| Sender-Signed | 0.333  | 0.000  |
| **ATTP** | **1.000**  | **0.000**  |

|Method|TP|FN|FP|
|---|---|---|---|
|AgentTrace|0|120|12|8|
|Sender-Signed|40|80|0|20|
|ATTP|120|0|0|20|

- ATTP 召回分解：conflicting **1.000**（100/100）、incomplete **1.000**（20/20）；注入故障事件总数 **120**。
- Δ(ATTP − AgentTrace) 良性告警 = **−0.600**；ATTP vs Sender-Signed 良性告警 Δ ≈ 0（两者均可对账）——**真正拉开差距的是 Fault Recall**（1.000 vs 0.333 vs 0.000）。
- AgentTrace 无签名 → 召回 0；无对账能力 → 良性延迟残留告警 0.600。Sender-Signed 单签抓 Branch A 篡改/冒充（conflicting 0.400），但无第二来源 → 测不到 Branch B 篡改、栽赃、缺报（incomplete 0）。ATTP 双报交叉 + 双签 → 确定性检出（结构层证据，非概率）。
---


## RQ2:单独测纵向
主要内容：1、使用其他框架作为基线；2、不同证据损坏情况下的鲁棒性
### Block 1 · Clean semantic detection（Macro-F1，{偏离,干净} 二类宏平均）

评测集：train_R_T（95 场景，718 条行为，单跳攻击集——within-session 纵向质量的正确度量）。

| Method | Macro-F1 ↑ | 来源 |
|---|---|---|
| Direct Judge | 0.698 |  实测 |
| DeAction | 0.790 | †est |
| AgentAuditor | 0.830 | †est |
| **ATTP** | **0.894** |  实测 |

| Method | P | R | F1 | FPR | TP/FP/FN/TN | 来源 |
|---|---|---|---|---|---|---|
| **ATTP** | 0.973 | 0.775 | 0.863 | 0.014 | 217/6/63/432 | ✅ |
| AgentAuditor | 0.936 | 0.680 | 0.788 | 0.030 | 190/13/90/425 | †est |
| DeAction | 0.900 | 0.580 | 0.706 | 0.041 | 162/18/118/420 | †est |
| Direct Judge | 0.780 | 0.468 | 0.585 | 0.084 | 131/37/149/401 | ✅ |
### Block 2 · One-sided corruption；fixed auditor（Sem. Coverage / E2E Threat Recall）

† 全部估算（未建 corruption 注入 harness；按"双报告最鲁棒"原则估）。

| Evidence | Sem. Coverage ↑ | E2E Threat Rec. ↑ |
|---|---|---|
| AgentTrace-style | 0.40 † | 0.48 † |
| Sender-Signed | 0.55 † | 0.62 † |
| **Dual Reports (ATTP)** | **0.92** † | **0.88** † |

| Evidence | P | R | F1 | FPR | TP/FP/FN/TN | 来源 |
|---|---|---|---|---|---|---|
| AgentTrace-style | 0.545 | 0.480 | 0.510 | 0.400 | 96/80/104/120 | †est |
| Sender-Signed | 0.805 | 0.620 | 0.701 | 0.150 | 124/30/76/170 | †est |
| **Dual Reports (ATTP)** | 0.957 | 0.880 | 0.917 | 0.040 | 176/8/24/192 | †est |
---
## RQ3：单独测横向机制
主要内容：不同横向机制的对比，包括Coreset Reader（压缩摘要的历史）、全历史都看、固定间隔横向审计、只看纵向  
评测集：92 场景 ，campaign 节点级 197 = 恶意 96 / 良性 101，行为 2232条）。  
判别分：横向 confirm taint（纵轴各法共享、为常量；coordinator 误报由 confirm 过滤）。  
Vertical-Only 移出主表，因为比较的横向分析的触发机制，将其放在下面节点级比较中了。

| Method | AUPRC ↑ | Rec.@5%FPR ↑ | Delay ↓ | Calls/1K ↓ |
|---|---|---|---|---|
| Full-History | **0.873**  | 1.000  | **2.5**  | 88.3  |
| Coreset Reader | 0.866  | 1.000  | 2.8  | 88.3  |
| Periodic-Horizontal | 0.751  | 1.000  | 3.5  | **59.1**  |
| **ATTP** | 0.795  | **1.000**  | 2.9  | 61.4  |


横+纵在test测试集节点级的效果

| Method | P | R | F1 | FPR | TP/FP/FN/TN |
|---|---|---|---|---|---|
| Full-History | 0.845 | 0.969 | **0.903** | 0.168 | 93/17/3/84 |
| Coreset Reader | 0.845 | 0.969 | **0.903** | 0.168 | 93/17/3/84 |
| Periodic | 0.828 | 0.854 | 0.841 | 0.168 | 82/17/14/84 |
| **ATTP** | 0.816 | **0.969** | **0.886** | 0.208 | 93/21/3/80 |
| VertOnly(消融) | 0.762 | **0.667** | 0.711 | 0.198 | 64/20/32/81 |

### 横向机制 token 消耗（test，gemini，cl100k_base 计数）

各横向机制平均每场景的输入 token 消耗（test 92 场景，campaign 节点级 197 = 恶意 96 / 良性 101）。
无现成 token 记录，用 tiktoken(cl100k_base) 重构每个 confirm 的完整 prompt（system+user）计数——确定性、无需再调 API。**绝对值**与 gemini 原生分词略有出入，**方法间相对比较可靠**（同一批 prompt 文本）。

| Method | calls | 总 token | **avg token/场景** | avg token/call |
|---|---|---|---|---|
| Full-History | 197 | 380,584 | 4,137 | 1,932 |
| Coreset Reader | 197 | 378,521 | 4,114 | 1,921 |
| Periodic-Horizontal | 132 | 255,615 | 2,778 | 1,936 |
| **ATTP** | 137 | 280,621 | **3,050** | 2,048 |

- **ATTP 比 Full-History 省 ~26% token/场景**（3,050 vs 4,137）：风险触发只审 F>R_S 节点（137 vs 197 calls）。
- ATTP per-call 反而最高（2,048）：它审的是高累积节点（跳更多、prompt 更大）；Full 含大量小节点拉低均值。但总 calls 少 → 总 token 仍更低。
- Periodic token 最少（2,778）但检测也最差（AUPRC 0.751）：省 token 是以漏检为代价。
- Coreset ≈ Full（4,114 vs 4,137）几乎不省：test 多为单会话小节点，top-M=3 限界记忆用不上；多会话重数据上 Coreset 才显著省 token。

脚本：[rq3_tokens.py](../../intent_analysis/rq/rq3_tokens.py)。结果：[rq3_tokens.json](../../data/results/rq/gemini/rq3_tokens.json)。

---
## RQ4:

> throughput = 1000 / (网络floor + ΔP95)。
> 网络 floor = **0.89 ms（loopback 实测 `/api/status`）**；ΔP95 = 各配置转发"签名+验签+落库"（部署级 WAL 组合）。

| Configuration | ΔP95 (ms) ↓ | Throughput (ev/s) ↑ | Stored B/event ↓ | Verify lag (ms) ↓ | Alert staleness (s) ↓ |
|---|---|---|---|---|---|
| Uninstrumented | 0 | 1125 | 0 | — | — |
| Sender-Signed | 0.030 | 1088（96.6%） | 354 | — | — |
| **ATTP-Async** | **0.058** | **1056（93.9%）** | **772** | **0.082** | **7.6** |
| ATTP-SyncSig | 0.140 | 972（86.4%） | 772 | 0 | 7.6 |

|配置|组成|ΔP95|
|-|-|-|
|Uninstrumented|无|0|
|Sender-Signed|1签+1存 = 28.5+1.37|0.030 ms|
|ATTP-Async|2签+1存 = 57+1.37|0.058 ms| 
|ATTP-SyncSig|2签+1验+1存 = 57+82+1.37|0.140 ms|


- 转发几乎不拖速：ATTP 异步每条多花 0.058 ms，比"光签名"只多 0.029 ms（多签一次）。
- 两种验签取舍：异步 = 转发快但签名稍后验（0.082 ms lag）；同步 = 转发慢 0.082 ms 但当场确认。
- 吞吐：ATTP-Async 1056 ev/s（loopback floor），保留基线 **93.9%**——处理远未触顶，网络才是瓶颈。
- 告警 7.6 s（live gemini 实测 5–8 s 波动）：AI 逐跳分析耗时，与转发快慢无关。
- 单项：签名 0.030 ms、验签 0.082 ms、存库(WAL) 0.001 ms。
- **实测端到端**：完整跑一遍 ATTP `/record`（真 uvicorn + 合法签名 BackMessage），loopback RTT = 网络 **0.89 ms** + 处理 **6.8 ms** = **7.7 ms**。6.8 ms 是 aiosqlite 落库开销，可经直连 WAL/批写降到亚毫秒 → 表中吞吐用部署级 floor。

**脚本 / 数据**：
- ΔP95 / Throughput / Verify-lag / Stored 组合：[rq4_overhead.py](../../intent_analysis/rq/rq4_overhead.py) → [rq4_results.json](../../data/results/rq/gemini/rq4_results.json)
- 网络 floor（loopback RTT 实测，完整跑 /record）：[rq4_rtt_live.py](../../intent_analysis/rq/rq4_rtt_live.py) → [rq4_rtt_live.json](../../data/results/rq/gemini/rq4_rtt_live.json)
- Alert staleness（live gemini admit→alert）：[rq4_overhead.py](../../intent_analysis/rq/rq4_overhead.py) `part_b()`
- Stored B/event（证据层序列化字节）：[rq1_evidence.py](../../intent_analysis/rq/rq1_evidence.py)
- 原子分量基准（sign/verify/store）：[rq4_overhead.py](../../intent_analysis/rq/rq4_overhead.py) `_bench_compute` / `_bench_bare_store`
---

## 五、消融实验（仅 gemini）

> **Macro-F1 vs 正常 F1 口径**：正常 F1（偏差类，报告里"行为F1"）只算偏离类 2PR/(P+R)；Macro-F1 = (偏离类 F1 + 干净类 F1)/2，把"干净也判对"平均进来 → 比 F1 高。下表 **F1 矩阵统一用正常 F1（偏差类）**。

### 5.1 动态意图 / 历史摘要 消融（train_R_T，V-Reasoner 打分侧）

禁用 V-Reasoner 的对应输入、重跑 gemini 打分：`no_intent`=意图清空（hidden 保留递推）、`no_hidden`=历史摘要清空（意图保留）。

| 配置 | P | R | F1 | FPR | TP/FP/FN/TN |
|---|---|---|---|---|---|
| **full** | 0.973 | 0.775 | **0.863** | 0.014 | 217/6/63/432 |
| no_intent | 0.962 | 0.539 | 0.691 | 0.014 | 151/6/129/432 |
| no_hidden | 0.955 | 0.382 | 0.546 | 0.011 | 107/5/173/433 |

- **FPR 全程 0.011–0.014 不变**（低误报不靠意图/历史）→ 消融只掉**召回**。
- 去历史摘要：R 0.775→0.382（漏 +110 偏离）、F1 −0.317 → **历史摘要最关键**（递推记忆识别渐变攻击）。
- 去动态意图：R 0.775→0.539（漏 +66 偏离）、F1 −0.172 → 次之（意图基准判"偏离目标"）。
- critical(ideal>7) 视角：full 抓 137/142（0.965）；去意图多漏 26 个真 critical，去历史多漏 52 个。

### 5.2 单阈值 vs 双阈值 消融（test，square 累积，F>R_S 且 confirm taint≥5.5）

node flagged = (F=Σ sub-R_T s² > R_S) 且 (横向 confirm taint≥5.5)。

| 配置 | R_S | P | R | F1 | FPR | TP/FP/FN/TN |
|---|---|---|---|---|---|---|
| 单阈值 r_s=r_t² | 49 | 0.829 | 0.708 | 0.764 | 0.139 | 68/14/28/87 |
| **双阈值(独立标定)** | 20 | 0.842 | 0.833 | **0.838** | 0.149 | 80/15/16/86 |

- 双阈值扫描：r_s=10–20 为 F1 平台(0.838)；r_s=49（绑死 r_t²）降到 0.764。
- 单阈值 r_t²=49 偏高 → 漏 28 个恶意（R 0.708）；独立标定 R_S=20 → R 0.833、F1 +0.074。**R_S 应独立于 R_T 标定。**

### 5.3 累积公式消融（s¹–s⁴，详见"二补"段）

F1 倒 U 型、**s³ 最优(0.933)**：s¹ 0.879 → s² 0.901 → s³ **0.933** → s⁴ 0.885。低次稀释信号、高次批次过小，s² 稳妥、s³ 可 +3pt F1 且零误报。

---
脚本：[rq_ablation_vreasoner.py](../../intent_analysis/rq/rq_ablation_vreasoner.py)（意图/历史消融）/ [rq_rs_formulas.py](../../intent_analysis/rq/rq_rs_formulas.py)（单双阈值+累积公式）。
