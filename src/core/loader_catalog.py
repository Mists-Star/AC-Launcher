"""加载器 × MC 版本可用性目录（round-186）。

用户报：「修改的选项中会出现不存在的加载器与版本」。

根因不是单选/多选做错了，是**从来没按 MC 版本筛过**：

* 编辑面板的加载器下拉直接把 ``LOADERS`` 全列出来 —— 1.12.2 的实例也能选
  NeoForge（它 1.20.1 才有）、能选 Quilt（1.14+）；
* 版本列表里，Fabric 走的是 ``get_all_loader_versions()``（**全历史版本**），
  NeoForge 走 ``get_loader_versions()``（**全 MC 版本**）—— 于是下拉里出现
  「这个 MC 版本根本装不上」的版本号。

本模块只做**静态**判断（不发网络）：先按版本号区间把明显不可能的滤掉，
再由调用方拿「拉回来的版本列表是否为空」兜底 —— 光有静态规则会误伤快照版
和 OptiFine 这种「有版本才有得装」的加载器。

规则来源：
* Fabric / Quilt：1.14 起（Fabric 官方支持表从 1.14 开始）
* NeoForge：1.20.1 起（首个正式版 20.1.x）
* LiteLoader：止于 1.12.2；Legacy Fabric：止于 1.13.2
* Cleanroom：**只** 1.12.2（它就是 Forge 1.12.2 的现代重编译版）
* OptiFine：1.7.2 ~ 最新（具体有没有得看列表，静态只挡上古版本）
"""
from __future__ import annotations

import re

#: 名称 → (最低 MC, 最高 MC)；``None`` 表示不限。区间是**闭区间**。
_RULES: dict[str, tuple[str | None, str | None]] = {
    "vanilla": (None, None),
    "fabric": ("1.14", None),
    "quilt": ("1.18", None),
    "forge": ("1.6", None),
    "neoforge": ("1.20.1", None),
    # 上界写 1.12.9 而不是 1.12.2 —— MC 的 1.12.x 最后一个是 1.12.9，
    # 写 1.12.2 会把 1.12.3~1.12.9 全部误杀（LiteLoader 在这些版本上都有）。
    "liteloader": (None, "1.12.9"),
    "legacyfabric": (None, "1.13.2"),
    "cleanroom": ("1.12.2", "1.12.2"),
    "optifine": ("1.7.2", None),
}

_SNAP = re.compile(r"^\d{2}w\d{2}[a-z]$")


def parse_mc(version: str) -> tuple[int, ...] | None:
    """``"1.20.1"`` → ``(1, 20, 1)``；快照/预发布返回 ``None``（不参与比较）。"""
    v = (version or "").strip()
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", v)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _cmp_key(p: tuple[int, ...], width: int = 3) -> tuple[int, ...]:
    """补零到同一长度，避免 ``(1,20) < (1,20,1)`` 这类长度差导致的误判。"""
    return p + (0,) * (width - len(p))


def supports(loader: str, mc_version: str) -> bool:
    """这个加载器在这个 MC 版本上**可能**存在（只看静态区间）。

    返回 True 不代表一定有构建 —— 还要看拉回来的版本列表是否为空。
    """
    lid = (loader or "vanilla").strip().lower()
    lo, hi = _RULES.get(lid, (None, None))
    if lo is None and hi is None:
        return True
    cur = parse_mc(mc_version)
    if cur is None:
        # 快照 / 预发布：不做静态判断，交给「列表为空」兜底
        return True
    curk = _cmp_key(cur)
    if lo is not None and curk < _cmp_key(parse_mc(lo) or (0,)):
        return False
    if hi is not None and curk > _cmp_key(parse_mc(hi) or (999,)):
        return False
    return True


def loaders_for(mc_version: str, all_loaders) -> list[str]:
    """按支持情况筛一遍加载器列表（保持传入顺序）。"""
    return [lid for lid in all_loaders if supports(lid, mc_version)]


def neoforge_prefix(mc_version: str) -> str:
    """NeoForge 的版本号前缀与 MC 版本一一对应。

    ``1.20.1`` → ``20.1.``、``1.21`` → ``21.0.``、``1.21.4`` → ``21.4.``。
    拿它去过滤 ``Neoforge.get_loader_versions()`` 那个**全 MC 版本**的大列表。
    """
    p = parse_mc(mc_version)
    if not p or len(p) < 2:
        return ""
    minor = p[1]
    patch = p[2] if len(p) > 2 else 0
    return "%d.%d." % (minor, patch)


#: NeoForge 的**第一个**正式版对应 MC 1.20.1（版本号 20.1.x）。
NEOFORGE_MIN_MC = "1.20.1"


def filter_neoforge(versions, mc_version: str) -> list[str]:
    """把 NeoForge 版本列表裁到「本 MC 版本可装」的那些。

    光按版本号前缀裁是不够的：NeoForge 的 20.x 对应 MC 1.20.x，但 1.19.2
    也会算出前缀
    所以先卡下限，再按前缀裁。
    """
    if not supports("neoforge", mc_version):
        return []
    pre = neoforge_prefix(mc_version)
    if not pre:
        return []
    return [v for v in versions if str(v).startswith(pre)]
