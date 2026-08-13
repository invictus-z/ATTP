"""ATTP 意图审计基准（intent analysis benchmark）。

子包：
  lib/       — 共享核心库（ScenarioDB / ScenarioSpec / 表结构）
  scenarios/ — 场景定义（纯数据，按类别分文件）
  runners/   — 流水线可执行脚本（generate / evaluate / calibrate / confirm）
  rq/        — RQ1-4 补充实验脚本

运行入口统一从 ``test/benchmark/`` 目录以模块方式调用，例如::

    python -m intent_analysis.runners.generate_all
    python -m intent_analysis.runners.evaluate --mode dry
"""
