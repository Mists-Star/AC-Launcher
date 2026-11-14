"""资源中心兼容性判定：区分「明确冲突」与「作者未标注」。

Modrinth / CurseForge 的 ``game_versions`` 是作者维护的支持列表，缺某个
小版本并不代表模组跑不起来 —— 同一主版本系列（1.20.1 与 1.20.4）的模组
通常可以直接加载。把这类情况一律标成红色「不兼容」会造成大量误报，也会
让「只看兼容」把实际能用的版本过滤掉。跨主版本（1.16 → 1.20）才是真正的
版本不匹配。

加载器不在此列：Fabric 模组在 Forge 上确实无法加载，属于硬约束。
"""
from __future__ import annotations


def same_minor_series(a: str, b: str) -> bool:
    """同为 1.20.x / 1.21.x 视为同一主版本系列；快照串不参与比较。"""
    pa, pb = str(a).split("."), str(b).split(".")
    return (len(pa) >= 2 and len(pb) >= 2
            and pa[0].isdigit() and pa[1].isdigit()
            and pa[0] == pb[0] and pa[1] == pb[1])


def mc_compat(inst_mc: str, declared: list[str]) -> str:
    """返回 ``"ok"`` / ``"unverified"`` / ``"mismatch"``。

    - 声明列表里有精确匹配 → ok
    - 无精确匹配但存在同系列声明 → unverified（不标红，只给提示）
    - 只有其它主版本，或实例版本未知 → mismatch / ok
    """
    if not inst_mc or not declared:
        return "ok"
    versions = [str(g) for g in declared]
    if inst_mc in versions:
        return "ok"
    if any(same_minor_series(inst_mc, g) for g in versions):
        return "unverified"
    return "mismatch"
