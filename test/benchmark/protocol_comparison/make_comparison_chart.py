"""生成协议溯源能力对比图——标准混淆矩阵热力图（4 协议 × 2×2）。

读取 data/results/protocol_comparison_report.json 的 confusion_matrix，输出
docs/protocol_comparison_chart.png。每格显示 TP/FN/FP/TN 计数；颜色深浅反映该格计数。
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
BENCH_ROOT = HERE.parent                       # test/benchmark
REPORT = BENCH_ROOT / "data" / "results" / "protocol_comparison_report.json"
OUT = BENCH_ROOT / "docs" / "protocol_comparison_chart.png"

for f in ["Microsoft YaHei", "SimHei", "Source Han Sans SC", "Arial Unicode MS"]:
    if any(f in ff.name for ff in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [f]
        break
plt.rcParams["axes.unicode_minus"] = False

PROTOCOLS = ["ANP", "ACP", "A2A", "ATTP"]
TITLES = {"ANP": "ANP", "ACP": "ACP", "A2A": "A2A", "ATTP": "ATTP（本协议）"}


def main():
    data = json.load(open(REPORT, encoding="utf-8"))
    cm = data["confusion_matrix"]

    fig, axes = plt.subplots(1, 4, figsize=(13.5, 4.0), dpi=150)
    fig.patch.set_facecolor("#FFFFFF")

    vmax = 49  # 攻击场景数，统一色阶上限
    for ax, proto in zip(axes, PROTOCOLS):
        c = cm[proto]
        tp, fn, fp, tn = c["tp"], c["fn"], c["fp"], c["tn"]
        # 矩阵：行=实际(攻击/干净)，列=预测(攻击/干净)
        mat = np.array([[tp, fn], [fp, tn]], dtype=float)
        ax.imshow(mat, cmap="Blues", vmin=0, vmax=vmax, aspect="equal")

        labels = [["TP", "FN"], ["FP", "TN"]]
        vals = [[tp, fn], [fp, tn]]
        for i in range(2):
            for j in range(2):
                v = vals[i][j]
                # 文字颜色：深色格用白字
                color = "white" if v > vmax * 0.55 else "#1F2937"
                ax.text(j, i - 0.16, labels[i][j], ha="center", va="center",
                        fontsize=9, color=color, fontweight="bold")
                ax.text(j, i + 0.20, str(v), ha="center", va="center",
                        fontsize=15, color=color, fontweight="bold")

        ax.set_title(f"{TITLES[proto]}\nF1={c['f1']*100:.0f}%  Recall={c['recall']*100:.0f}%  Acc={c['accuracy']*100:.0f}%",
                     fontsize=10, fontweight="bold" if proto == "ATTP" else "normal",
                     color="#0072B2" if proto == "ATTP" else "#111827", pad=8)
        ax.set_xticks([0, 1]); ax.set_xticklabels(["预测=攻击", "预测=干净"], fontsize=8.5, color="#374151")
        ax.set_yticks([0, 1]); ax.set_yticklabels(["实际=攻击", "实际=干净"], fontsize=8.5, color="#374151", rotation=90, va="center")
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_color("#D1D5DB")

    fig.suptitle("ATTP vs ANP/ACP/A2A — 标准混淆矩阵（攻击检出二分类，63 场景 = 49 攻击 + 14 干净）",
                 fontsize=12.5, fontweight="bold", color="#111827", y=1.02)
    fig.text(0.5, -0.04,
             "数据来源：63 场景，deepseek-v3.2 取证审计（ANP/ACP/A2A）；ATTP 复用生产 Cross-Lock 输出。"
             "  ATTP 的 TP=48（攻击几乎全部命中），基线 TP 仅 2–5（绝大多数攻击漏报为 FN）。",
             ha="center", fontsize=7.5, color="#6B7280")

    plt.tight_layout()
    OUT.parent.mkdir(exist_ok=True)
    plt.savefig(OUT, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    print(f"图表已生成: {OUT}")


if __name__ == "__main__":
    main()
