"""生成场景数据库（数据集真值来源 = intent_analysis.scenarios）。

默认生成全部 274 个场景；``--split`` 可只重建某一划分（不动其余），
例如刷新 test 集而不重跑 train（取代旧 rq_gen_test.py）。

运行（从 ``test/benchmark`` 目录）::

    python -m intent_analysis.runners.generate_all               # 全部 274
    python -m intent_analysis.runners.generate_all --split test  # 仅 test(te001-092)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # intent_analysis/runners
BENCH_ROOT = HERE.parent.parent                     # test/benchmark
sys.path.insert(0, str(BENCH_ROOT))                 # intent_analysis 包

from intent_analysis.lib.benchmark_lib import ScenarioDB
from intent_analysis.scenarios import ALL_SCENARIOS

SCENARIOS_DIR = BENCH_ROOT / "data" / "scenarios"

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    return _ILLEGAL.sub("_", name)


def generate_all(split: str | None = None):
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = [s for s in ALL_SCENARIOS if (split is None or s.split == split)]
    # 按 category 自动归组
    groups = [(name, [s for s in scenarios if s.category == cat])
              for name, cat in [("VERTICAL", "vertical"), ("HORIZONTAL", "horizontal"),
                                ("CLEAN", "clean"), ("BOUNDARY", "boundary")]]

    scope = "ALL" if split is None else f"split={split}"
    print("=" * 72)
    print(f"  Generating {len(scenarios)} ATTP benchmark scenarios  ({scope})")
    print("=" * 72)

    total_traces = 0
    for gname, group in groups:
        if not group:
            continue
        print(f"\n[{gname}] {len(group)} scenarios")
        for spec in group:
            fname = f"{spec.sid}_{safe_filename(spec.name)}.db"
            db_path = str(SCENARIOS_DIR / fname)
            if os.path.exists(db_path):
                os.unlink(db_path)
            sdb = ScenarioDB(db_path, spec)
            sdb.build()
            n_traces = sdb._tid
            n_sess = len(spec.sessions)
            mal = spec.mal_agent if spec.category != "clean" else "(clean)"
            print(f"  {spec.sid:<5} {spec.name:<22} | {n_sess} sess | {n_traces:>3} traces | "
                  f"{spec.difficulty:<8} | mal={mal}")
            total_traces += n_traces

    print("\n" + "=" * 72)
    print(f"  Done. {len(scenarios)} scenarios, {total_traces} total traces.")
    print(f"  Output: {SCENARIOS_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成 ATTP 基准场景数据库")
    ap.add_argument("--split", default=None,
                    choices=["train_R_T", "train_R_S", "test"],
                    help="只重建某一划分（默认全部）；取代旧 rq_gen_test.py")
    args = ap.parse_args()
    generate_all(split=args.split)
