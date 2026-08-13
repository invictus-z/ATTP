# ATTP Benchmark

> ATTP 协议的两套独立基准实验：**意图审计能力评测** + **协议溯源能力对比**。
> **274 个标注场景**（train_R_T 95 / train_R_S 87 / test 92），覆盖纵向检出、横向关联、误报控制、协议可见性前沿对比等维度。

---

## 1. 两套子实验

本目录包含两组互相独立、共享同一数据目录（`data/`）的实验：

| 子实验 | 目录 | 测什么 | 入口 |
|--------|------|--------|------|
| **A. 意图审计** | [intent_analysis/](intent_analysis/) | Cross-Lock 子系统（纵向 + 横向意图审计）的检出 / 误报 / 归因 / 校准能力 | `python -m intent_analysis.runners.evaluate` |
| **B. 协议对比** | [protocol_comparison/](protocol_comparison/) | ATTP vs ANP/ACP/A2A 在「用户侧定位恶意节点」能力上的差距 | `protocol_comparison/compare_protocols.py` |

两者共享 `data/scenarios/`（场景库）；协议对比的 ATTP 列复用意图审计的 LLM 评测结果（`data/results/eval/<model>/`）。

> 📄 规格：意图审计见 [docs/intent_analysis/SPEC.md](docs/intent_analysis/SPEC.md)；**当前实验记录（274 场景 / RQ1-4）见 [docs/intent_analysis/EXPERIMENT.md](docs/intent_analysis/EXPERIMENT.md)**；v1 历史测量报告见 [docs/intent_analysis/MEASUREMENT_REPORT.md](docs/intent_analysis/MEASUREMENT_REPORT.md)；协议对比报告见 [docs/protocol_comparison/PROTOCOL_COMPARISON_REPORT.md](docs/protocol_comparison/PROTOCOL_COMPARISON_REPORT.md)。测试数据发布在 [ATTP-benchmark](https://github.com/violet0630/ATTP-benchmark)。

---

## 2. 目录结构

```
test/benchmark/
├── README.md                          # 本文件
├── intent_analysis/                   # ★ 意图审计基准（Python 包）
│   ├── lib/                           #   共享核心库
│   │   └── benchmark_lib.py           #     ScenarioDB / ScenarioSpec / 表结构 / S·A·C 模板
│   ├── scenarios/                     #   场景定义（纯数据，按类别分文件）
│   │   ├── __init__.py                #     聚合 → ALL_SCENARIOS（重编号 rt/rs/te + 4-split）
│   │   ├── vertical.py / horizontal.py / slow.py / clean.py / boundary.py
│   ├── runners/                       #   流水线可执行脚本
│   │   ├── generate_all.py            #     数据集生成器（--split 可只重建某一划分）
│   │   ├── evaluate.py                #     评测器（dry / llm / eval-only）
│   │   ├── calibrate_R_T.py / calibrate_R_S.py   # R_T / R_S 阈值标定
│   │   └── confirm_eval.py / offline_horizontal.py  # 横向 confirm 判准率
│   └── rq/                            #   RQ1-4 补充实验（主模型 gemini，隔离输出）
│       ├── README.md                  #     运行顺序 + 文件清册
│       ├── rq_common.py               #     公共件（常量/路径/读数 helper）
│       └── rq1_*.py / rq2_*.py / rq3_*.py / rq4_*.py / rq_ablation_*.py / rq_rs_*.py
├── protocol_comparison/               # ★ 协议对比基准（独立）
│   ├── compare_protocols.py           #   ATTP vs ANP/ACP/A2A 主驱动
│   ├── protocol_frontiers.py          #   四层可见性前沿 brief 构造
│   ├── forensic_audit.py              #   取证审计 LLM
│   ├── make_comparison_chart.py       #   混淆矩阵图生成
│   └── structural_defense_test.py     #   协议层七步验证流水线
├── data/                              # 数据产物（输入/输出分离）
│   ├── scenarios/                     #   输入：274 个场景 *.db（可由代码重建）
│   └── results/                       #   输出
│       ├── eval/<model>/              #     逐模型评测结果（{sid}_llm.db + 报告 json）
│       └── rq/gemini/                 #     RQ1-4 实验隔离输出
└── docs/                              # 文档（按 benchmark 分子目录）
    ├── intent_analysis/{SPEC.md, EXPERIMENT.md, MEASUREMENT_REPORT.md}
    └── protocol_comparison/{PROTOCOL_COMPARISON_REPORT.md, protocol_comparison_chart.png}
```

---

## 3. 数据与代码分离

数据集是**构建产物**，可由代码重建——`generate_all.py` 仅依赖 Python 标准库，从 `intent_analysis.scenarios` 确定性生成全部 274 个 `data/scenarios/*.db`：

```bash
cd test/benchmark
python -m intent_analysis.runners.generate_all               # 全部 274
python -m intent_analysis.runners.generate_all --split test  # 仅 test 集（取代旧 rq_gen_test.py）
```

---

## 4. 路径自定位

`intent_analysis` 是一个 Python 包。所有脚本顶部用统一 bootstrap 把 `test/benchmark/` 与 `<repo>/python/` 加入 `sys.path`，因此 clone 后**无需修改任何路径常量**即可运行：

```python
HERE = Path(__file__).resolve().parents[2]          # test/benchmark（从 runners/ 或 rq/ 上溯）
sys.path.insert(0, str(HERE))                        # intent_analysis 包
sys.path.insert(0, str(HERE.parent.parent / "python"))  # attp.core.*（被测系统）
```

统一从 `test/benchmark/` 以模块方式调用：`python -m intent_analysis.runners.<script>`。`attp.core.*` 按脚本相对路径解析；每场景独立 coordinator + 独立结果 DB，并发无状态污染。

---

## 5. 子实验 A：意图审计（[intent_analysis/](intent_analysis/)）

量化评测 ATTP 协议节点 **Cross-Lock 意图审计子系统**（纵向 `VerticalIntentAnalyzer` + 横向 `HorizontalIntentAnalyzer` + `CrossLockCoordinator`）。真实攻击载荷（`rm -rf /etc/security`、`curl ... | bash`、`zip -rm -P` 加密外泄等）按失准类型转译为 ATTP 多智能体协议消息流，并扩展至金融 / 医疗 / DevOps / 电商客服领域。

### 5.1 数据集概览（274 场景，4-split）

| 划分 | 数量 | 用途 |
|------|------|------|
| `train_R_T` | 95 | R_T 标定（行为级偏离阈值）—— v/c 场景 |
| `train_R_S` | 87 | R_S 标定（慢投毒送横向）—— 慢投毒/subtle/boundary 触发类 |
| `test` | 92 | 独立测试（te001-060 多样 + te061-092 慢投毒） |

类别分布：纵向 82 / 横向 126（含慢投毒）/ 干净 43 / 边界 23。8 项能力（F1–F8）与攻击分类体系定义见 [SPEC.md](docs/intent_analysis/SPEC.md)。

### 5.2 运行

```bash
cd test/benchmark

# (0) 准备数据集
python -m intent_analysis.runners.generate_all

# (1) dry：不调 LLM，用理想数据自测评测逻辑（秒级，期望全指标 = 1.0 / MAE = 0）
python -m intent_analysis.runners.evaluate --mode dry

# (2) llm：真实 LLM 全量评测（并发 8）
python -m intent_analysis.runners.evaluate --mode llm --concurrency 8
# 指定模型 / 结果目录：--model <name> --provider-dir <dir>
python -m intent_analysis.runners.evaluate --mode llm --model gemini-3.1-flash-lite --provider-dir gemini

# (3) eval-only：复用已生成结果，秒级重评（改 R_T 后快速重算）
python -m intent_analysis.runners.evaluate --mode eval-only

# (4) 阈值标定（读 {sid}_llm.db）
python -m intent_analysis.runners.calibrate_R_T --model <name>           # → R_T
python -m intent_analysis.runners.calibrate_R_S --model <name> --r-t <R_T> # → R_S

# (5) 横向 confirm 判准率
python -m intent_analysis.runners.confirm_eval --model <name> --r-t <R_T>
```

环境：Python ≥ 3.13；依赖 `openai`（AsyncOpenAI）、`aiosqlite` 及本仓库 `python/` 下的 ATTP 核心包。LLM 配置见 [§7](#7-凭证配置)。RQ1-4 补充实验见 [rq/README.md](intent_analysis/rq/README.md)。

### 5.3 评测指标

| 类别 | 指标 | 定义 |
|------|------|------|
| 判定级 | Precision / Recall / F1 / FPR | 行为级（跳·纵向）与节点级（DID·联合纵向∪横向） |
| 评分级 | Score MAE | mean(\|llm_score − ideal_score\|) |
| 横向 | Precision / Recall / F1 | 横向 confirmed 判定 |
| 证据/归因 | Evidence Trace Hit / Attribution Accuracy | 证据定位 + 多 agent 锁定真凶 |

判定阈值：`overall_verdict ∈ {malicious, suspicious}` 为阳性，`clean` 为阴性。完整结果（含 R_T/R_S 标定、RQ1-4、消融）见 [EXPERIMENT.md](docs/intent_analysis/EXPERIMENT.md)。

---

## 6. 子实验 B：协议对比（[protocol_comparison/](protocol_comparison/)）

在同一批场景的会话上，比较四种协议下「用户侧能否定位恶意节点」。ANP / ACP / A2A 用同一个取证审计 LLM 在各自可见性 brief 下判断；**ATTP 直接复用意图审计的 Cross-Lock 纵向输出**（`data/results/eval/<model>/{sid}_llm.db`），不重跑。

> ⚠️ **执行顺序**：协议对比的 ATTP 列依赖意图审计先跑出结果。需先执行 `evaluate --mode llm`，再运行 `compare_protocols.py`。

```bash
cd test/benchmark
python protocol_comparison/compare_protocols.py
python protocol_comparison/make_comparison_chart.py   # → docs/protocol_comparison/ 混淆矩阵图
python protocol_comparison/structural_defense_test.py  # 协议层七步验证（无需网络/大模型）
```

四层「可见性前沿」（ANP < ACP < A2A < ATTP）由 [protocol_frontiers.py](protocol_comparison/protocol_frontiers.py) 构造。结果详见 [PROTOCOL_COMPARISON_REPORT.md](docs/protocol_comparison/PROTOCOL_COMPARISON_REPORT.md)。

---

## 7. 凭证配置

| 用途 | 位置 | 说明 |
|------|------|------|
| 意图审计 LLM | `~/.attp/protocol_node/config.json` 的 `analysis` 段 | `evaluate.py` 读取（生产 ATTP 节点配置，含 `apiKey` / `baseUrl` / `model`） |
| 协议对比 LLM | `protocol_comparison/compare_config.local.json` | `forensic_audit.py` 读取（gitignore，含密钥） |

环境变量覆盖：`BLTCY_API_KEY` / `BLTCY_BASE_URL` / `ATTP_BENCHMARK_MODEL`。

---

## 8. 可复现性保障

- **数据集 = 构建产物，可逐字节重建**：`generate_all.py` 仅用 Python 标准库，从 `intent_analysis.scenarios` 确定性生成全部 274 个 `data/scenarios/*.db`。
- **评测逻辑自检**：真实 LLM 前先以 `--mode dry` 用理想数据自测（期望全指标 = 1.0）。
- **结果落盘可复现**：每次 LLM 运行存入 `data/results/eval/<provider>/{sid}_llm.db`，支持 `--mode eval-only` 秒级重评。
- **路径自定位**：见 [§4](#4-路径自定位)，clone 后免改路径常量。
- **并发隔离**：每场景独立 coordinator + 独立结果 DB，无状态污染。

---

## 9. 如何扩展（新增意图审计场景）

1. 在 [intent_analysis/scenarios/](intent_analysis/scenarios/) 对应类别文件（`vertical.py` / `horizontal.py` / `slow.py` / `clean.py` / `boundary.py`）的列表中追加一个 `ScenarioSpec`，填写 `sid` / `name` / `category` / `attack_type` / `difficulty` / `field_channel` / `mal_agent` / `user_name` / `sessions`（用 `S()` / `A()` / `C()` 模板）+ 理想标注。新增场景会自动经 `scenarios/__init__.py` 的 `_renumber_to_categories` 归入 4-split 并重编号。
2. `python -m intent_analysis.runners.generate_all` 重新生成 DB。
3. `python -m intent_analysis.runners.evaluate --mode dry` 自检（应保持全 1.0）。

模板与字段语义参见 [lib/benchmark_lib.py](intent_analysis/lib/benchmark_lib.py) 与 [SPEC.md](docs/intent_analysis/SPEC.md)。

---

## 10. 仓库分工（dataset vs. methodology）

本目录（主仓库 `test/benchmark/`）只保留**代码与文档**——场景定义、生成器、评测器、RQ 脚本与规格/报告文档；**数据集资源单独发布**到数据仓库：

> 📦 数据集仓库：**<https://github.com/violet0630/ATTP-benchmark>**

数据仓库结构（与主仓库 `data/` 对应）：
- `benchmark/scenarios/` —— 274 场景库（对应主仓库 `data/scenarios/`）
- `benchmark/results/eval/<model>/` —— 6 模型意图审计结果（对应 `data/results/eval/`）
- `benchmark/results/rq/gemini/` —— RQ1-4 实验产物（对应 `data/results/rq/`）
- `archive/v1/` —— 早期 63 场景 / 5 模型快照（含协议对比、结构防御、论文 latex 表格）

> ⚠️ **时效**：数据仓库当前 `benchmark/results/eval/` 为 **pre-cubic** 结果（旧平方和 + R_S 配置）；主仓库现已将横向累计改为三次方 F=Σs³、R_S=200（实验最佳）。eval 结果后续用新配置重跑后更新，`results/rq/` 已基于三次方分析。
