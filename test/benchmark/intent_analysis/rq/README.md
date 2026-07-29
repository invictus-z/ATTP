# RQ 补充实验（`intent_analysis.rq`）

论文 RQ1–RQ4 的补充实验脚本。**主模型固定 gemini-3.1-flash-lite**，只读现有 gemini 评测结果，新 LLM 调用隔离输出到 `data/results/rq/gemini/`，绝不污染 `data/results/eval/`。

## 前置条件

1. **场景库就绪**：`data/scenarios/*.db`（由 `python -m intent_analysis.runners.generate_all` 生成）。
2. **gemini 评测结果就绪**：`data/results/eval/gemini/{sid}_llm.db`（由
   `python -m intent_analysis.runners.evaluate --mode llm --model gemini-3.1-flash-lite --provider-dir gemini` 生成）。
3. 阈值已标定：`R_T`、`R_S` 见 `rq_common.py`（gemini 标定值）。

所有脚本统一从 `test/benchmark/` 以模块方式调用，例如 `python -m intent_analysis.rq.rq1_evidence`。

## 公共件

| 文件 | 角色 |
|------|------|
| [rq_common.py](rq_common.py) | 常量（`MODEL` / `R_T` / `TAU_DEV` / `R_S`）、路径（`GEMINI_RES` 只读 / `RQ_RES` 隔离输出）、读数 helper（`scen_files` / `load_ideal` / `load_did_hops` / `macro_f1_binary` / `save_json` / `make_client`）。所有 rq 脚本 `from intent_analysis.rq import rq_common as c`。 |

## 文件清册（按 RQ）

| RQ | 脚本 | 测什么 | 依赖 |
|----|------|--------|------|
| **RQ1** | [rq1_evidence.py](rq1_evidence.py) | 三方案（AgentTrace / Sender-Signed / ATTP）注入 fault 的证据完整性 + 证据层存储开销 | `rq_common`, `attp.core.authentication/message` |
| **RQ2** | [rq2_attp_macro.py](rq2_attp_macro.py) | ATTP Macro-F1（从 gemini train_R_T hop_scores 纯重算，零新 LLM） | `rq_common`, `evaluate` |
| | [rq2_direct_judge.py](rq2_direct_judge.py) | Direct Judge 基线（gemini 直接逐行为判偏离，无意图流/隐状态） | `rq_common` |
| **RQ3** | [rq3_scorer.py](rq3_scorer.py) | Full-History / Coreset / Periodic 三法横向 confirm 打分（新 LLM，断点续） | `rq_common`, `attp.core.analysis.horizontal` |
| | [rq3_recompute.py](rq3_recompute.py) | 最终重算（无 LLM）：横向 confirm taint 作判别分；支持 `--split train_R_S\|test` | `rq_common` |
| | [rq3_tokens.py](rq3_tokens.py) | 各横向机制输入 token 消耗（test，tiktoken，无 API） | `rq_common`, `attp.core.analysis.horizontal` |
| | [rq_rs_formulas.py](rq_rs_formulas.py) | R_S × 累积公式（s¹/s¹·⁵/s²/…）敏感性扫描：recall/FPR/调用次数（纯评测） | `rq_common` |
| | [rq_rs_trigger_f1.py](rq_rs_trigger_f1.py) | 各公式最佳 R_S 下节点级 F1（每批次独立调 gemini） | `rq_common`, `rq3_scorer._confirm` |
| **RQ4** | [rq4_overhead.py](rq4_overhead.py) | 系统开销 Part A（ΔP95 转发延迟 + 吞吐）+ Part B（alert staleness） | `rq_common`, `attp.core` |
| | [rq4_rtt_live.py](rq4_rtt_live.py) | 实测 `/record` 回环 RTT（真 ProtocolPort + httpx，内存 DID 解析器不联网） | `rq_common`, `attp.core/protocol_node` |
| 消融 | [rq_ablation_vreasoner.py](rq_ablation_vreasoner.py) | 打分侧消融：动态意图 / 历史摘要 对 V-Reasoner 评分的贡献（test，gemini，跨 RQ2/3） | `rq_common`, `evaluate`, `attp.core.analysis.vertical` |
| 数据 | [rq_test_vertical.py](rq_test_vertical.py) | RQ3-test 第 1 步：test split(te001-060) 纵向 V-Reasoner，隔离到 `RQ_RES`，防卡死 + 可续跑 | `rq_common`, `evaluate` |

## 运行顺序

产物通过共享 db 传递（脚本间几乎不互调，仅 `rq_rs_trigger_f1` 复用 `rq3_scorer._confirm`）。

```
# 前置：gemini 评测已落盘到 data/results/eval/gemini/

# RQ1
python -m intent_analysis.rq.rq1_evidence

# RQ2
python -m intent_analysis.rq.rq2_attp_macro        # 零 LLM
python -m intent_analysis.rq.rq2_direct_judge      # 新 LLM

# RQ3（test split 子流水线）
python -m intent_analysis.rq.rq_test_vertical                  # 第 1 步：产 test 纵向 db
python -m intent_analysis.rq.rq3_scorer --split test           # 三法打分
python -m intent_analysis.rq.rq3_recompute --split test        # 重算判别分
python -m intent_analysis.rq.rq3_tokens                        # token 消耗
python -m intent_analysis.rq.rq_rs_formulas                    # R_S × 公式敏感性
python -m intent_analysis.rq.rq_rs_trigger_f1                  # 触发 confirm F1

# RQ4
python -m intent_analysis.rq.rq4_overhead
python -m intent_analysis.rq.rq4_rtt_live

# 消融（跨 RQ2/3）
python -m intent_analysis.rq.rq_ablation_vreasoner
```

所有产物（JSON / .db）写入 `data/results/rq/gemini/`，详见 [Experiment.md](../../docs/intent_analysis/EXPERIMENT.md) 各 RQ 小节的「结果」链接。
