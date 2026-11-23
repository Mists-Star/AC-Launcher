"""实例元数据的矛盾检测与自愈（round-245）。

为什么需要：用户实测一个整合包导入的实例 ``game_version=1.21.4 / loader=vanilla``，
但 ``version_id=1.20.1-forge-47.4.0``。补全按 loader=vanilla 去装 1.21.4 原版，
启动却按 version_id 找 1.20.1-forge —— 永远 ``Version ... was not found``。
这种矛盾来自：编辑面板手改字段没走装/卸流程、旧版本残留、导入时只回写了一半。

这里给出**单一真理源**：判断 version_id 是否与 loader/game_version 相容。
调用方（启动前、补全前、体检）共用，发现矛盾就把陈旧的 version_id 清掉，
让后续 install_instance 按当前 loader/game_version 正确补全。
"""
from __future__ import annotations

import os
import re

#: 各加载器在版本 id 里的典型标记（大小写不敏感）
_LOADER_MARKERS = {
    "fabric": ("fabric",),
    "quilt": ("quilt",),
    "forge": ("forge",),
    "neoforge": ("neoforge",),
    "legacyfabric": ("legacyfabric",),
    "liteloader": ("liteloader",),
    "optifine": ("optifine",),
    "cleanroom": ("cleanroom",),
}
_MC_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _norm_loader(value: str) -> str:
    return (value or "").strip().lower() or "vanilla"


def loader_mismatch(inst) -> str:
    """返回矛盾原因（空串 = 相容）。

    检测两条规则：
    1. ``version_id`` 带加载器标记，但实例 loader 是 vanilla（或另一种加载器）
       —— 典型的「卸了加载器但 version_id 没清」。
    2. ``version_id`` 里的 MC 版本与 ``game_version`` 不一致（如 1.20.1 vs
       1.21.4）—— 典型的「改了游戏版本但没重装」。
    """
    vid = str(getattr(inst, "version_id", "") or "").strip()
    if not vid:
        return ""
    loader = _norm_loader(getattr(inst, "loader", ""))
    game = str(getattr(inst, "game_version", "") or "").strip()
    low = vid.lower()

    # 规则 1：version_id 声明了加载器，实例却说没有/是别的加载器
    markers = set()
    for name, keys in _LOADER_MARKERS.items():
        if any(k in low for k in keys):
            markers.add(name)
    if "neoforge" in markers:
        markers.discard("forge")     # neoforge 的 id 里也含 "forge"
    if "legacyfabric" in markers:
        markers.discard("fabric")
    if markers:
        if loader == "vanilla":
            return "version_id 带加载器标记 %s，但实例是原版" % ", ".join(sorted(markers))
        if loader not in markers:
            return "version_id 的加载器 %s 与实例 %s 不一致" % (
                ", ".join(sorted(markers)), loader)

    # 规则 2：MC 版本不一致。
    # ☠ 不能简单取 version_id 里第一个 x.y.z —— "fabric-loader-0.16.9-1.21.4"
    # 的第一个是 loader 版本，"neoforge-21.1.0" 的第一个是 NeoForge 版本，
    # 都会被误判。可靠判据：game_version 作为子串出现就算相容；否则只在
    # version_id 里找 "1.x.y" 这种明确的 MC 版本格式（不碰 21.1.0 / 0.16.9）。
    if game:
        g = game.lower()
        if g not in low:
            # 只把 1.x 当 MC 主版本：0.x 是 loader 版本，21.x 是 NeoForge 版本
            mc_like = [v for v in _MC_RE.findall(low) if v.startswith("1.")]
            if mc_like:
                return "version_id 的 MC 版本 %s 与实例 %s 不一致" % (mc_like[0], game)
    return ""


def heal_version_id(inst, *, persist=None) -> bool:
    """发现矛盾就清空 ``version_id`` 并可选落盘。返回是否改动。"""
    if not loader_mismatch(inst):
        return False
    inst.version_id = ""
    if persist is not None:
        try:
            persist(inst)
        except Exception:  # noqa: BLE001 - 落盘失败不阻断启动；下次还会自愈
            pass
    return True


def version_json_exists(inst) -> bool:
    """启动前「已安装」判据的同款：版本 json 是否在两个合法位置之一。"""
    vid = str(getattr(inst, "version_id", "") or "").strip() or \
        str(getattr(inst, "game_version", "") or "").strip()
    mc = str(getattr(inst, "mc_dir", "") or "").strip()
    if not vid or not mc:
        return False
    return any(os.path.isfile(os.path.join(mc, rel, f"{vid}.json"))
               for rel in ("versions", ".", ""))
