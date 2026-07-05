"""生成全部 50 个场景数据库。

运行: cd e:/work/ATTP && python test/benchmark/taint_analysis/generate_all.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from benchmark_lib import ScenarioDB
from registry import ALL_SCENARIOS, VERTICAL, HORIZONTAL, CLEAN, BOUNDARY

SCENARIOS_DIR = HERE.parent / "data" / "scenarios"

# Windows 非法文件名字符
_ILLEGAL = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    """清洗 Windows 非法文件名字符。"""
    return _ILLEGAL.sub("_", name)


def generate_all():
    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    groups = [("VERTICAL", VERTICAL), ("HORIZONTAL", HORIZONTAL),
              ("CLEAN", CLEAN), ("BOUNDARY", BOUNDARY)]

    print("=" * 72)
    print(f"  Generating {len(ALL_SCENARIOS)} ATTP benchmark scenarios")
    print("=" * 72)

    total_traces = 0
    for gname, group in groups:
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
            print(f"  {spec.sid:<5} {spec.name:<22} | {n_sess} sess | {n_traces:>3} traces | {spec.difficulty:<8} | mal={mal}")
            total_traces += n_traces

    print("\n" + "=" * 72)
    print(f"  Done. {len(ALL_SCENARIOS)} scenarios, {total_traces} total traces.")
    print(f"  Output: {SCENARIOS_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    generate_all()
