"""场景注册表聚合入口。

按类别导入 5 个数据文件，重整为 4 类 + 连续编号 (rt/rs/te)：
  train_R_T : R_T 标定（行为级偏离）—— v/c 的 60%
  train_R_S : R_S 标定（慢投毒送横向）—— 慢投毒/subtle/boundary 触发类
  test      : 独立测试 —— te001-060(多样) + te061-092(SLOW_TEST 慢投毒)

ALL_SCENARIOS / SID_MAP / DROPPED_SIDS 由 _renumber_to_categories 产生
（逻辑自原 registry.py 逐字搬移；仅 SLOW_TEST 由参数注入）。原始顺序与原聚合公式一致。
"""
from __future__ import annotations

from ..lib.benchmark_lib import assign_split
from .vertical import VERTICAL
from .horizontal import HORIZONTAL
from .clean import CLEAN
from .boundary import BOUNDARY
from .slow import SLOW, SLOW_TEST

# 原始并集（顺序 == 原 registry.py 的 ALL_SCENARIOS 求和公式）
_RAW = VERTICAL + HORIZONTAL + CLEAN + BOUNDARY + SLOW


def _select_diverse_test(pool, orig_target=60, extra_slow=32):
    """test 池选择：原 orig_target 个保持不变（attack_type 轮询多样，与历史 te001-060 一致），
    再追加 extra_slow 个 horizontal 以提高慢累积比例。确定性。
    返回：[原 orig 个 按(attack_type,sid)] + [新增 extra 个 按 sid]。"""
    import collections
    def sort_key(s):
        mixed = 0 if (s.clean_coexist_dids or s.extra_malicious_dids) else 1
        return (mixed, s.sid)
    by_at = collections.defaultdict(list)
    for s in pool:
        by_at[s.attack_type].append(s)
    for at in by_at:
        by_at[at].sort(key=sort_key)
    orig, orig_ids, types = [], set(), sorted(by_at.keys())
    i = 0
    while len(orig) < orig_target:
        progressed = False
        for at in types:
            if i < len(by_at[at]):
                s = by_at[at][i]
                if id(s) not in orig_ids:
                    orig.append(s); orig_ids.add(id(s)); progressed = True
                if len(orig) >= orig_target:
                    break
        if not progressed:
            break
        i += 1
    orig = orig[:orig_target]
    extra = sorted([s for s in pool if id(s) not in orig_ids and s.category == "horizontal"],
                   key=sort_key)[:extra_slow]
    return (sorted(orig, key=lambda s: (s.attack_type, s.sid))
            + sorted(extra, key=lambda s: s.sid))


def _renumber_to_categories(scenarios, slow_test, orig_target=60):
    """按四类重分类 + 连续编号。test = 原 orig 个(te001-060) + slow_test(te061-092)。就地改 sid/split。"""
    rt, rs, te_pool = [], [], []
    for sp in scenarios:
        sp.split = assign_split(sp)
        if sp.split == "train_horiz":
            sp.split = "test"
        {"train_R_T": rt, "train_R_S": rs, "test": te_pool}[sp.split].append(sp)
    te_orig = _select_diverse_test(te_pool, orig_target, 0)
    te_keep = te_orig + list(slow_test)
    te_keep_ids = {id(s) for s in te_keep}
    dropped = [sp.sid for sp in te_pool if id(sp) not in te_keep_ids]
    keep = {"train_R_T": rt, "train_R_S": rs, "test": te_keep}
    prefix = {"train_R_T": "rt", "train_R_S": "rs", "test": "te"}
    mapping, out = {}, []
    for split in ("train_R_T", "train_R_S"):
        for i, sp in enumerate(sorted(keep[split], key=lambda s: (s.attack_type, s.sid)), 1):
            mapping[sp.sid] = (new := f"{prefix[split]}{i:03d}")
            sp.sid, sp.split = new, split
            out.append(sp)
    for i, sp in enumerate(keep["test"], 1):
        sp.sid, sp.split = f"te{i:03d}", "test"
        out.append(sp)
    return out, mapping, dropped


ALL_SCENARIOS, SID_MAP, DROPPED_SIDS = _renumber_to_categories(list(_RAW), SLOW_TEST, orig_target=60)


def by_id(sid: str):
    """按（重编号后的）sid 取场景。"""
    for s in ALL_SCENARIOS:
        if s.sid == sid:
            return s
    raise KeyError(sid)


if __name__ == "__main__":
    from collections import Counter
    print(f"Total scenarios: {len(ALL_SCENARIOS)}")
    print("By split:", dict(Counter(s.split for s in ALL_SCENARIOS)))
    print("By category:", dict(Counter(s.category for s in ALL_SCENARIOS)))
    print(f"Dropped sids: {len(DROPPED_SIDS)}")
