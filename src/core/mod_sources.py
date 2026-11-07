"""模组来源记录（round-191）—— 区分「资源中心下的」与「自己放进去的」。

用户要求「区分模组下载」。之前所有 jar 一视同仁：更新检测靠**文件名猜 slug**，
玩家自己丢进 mods/ 的和启动器下载的也看不出区别。

做法：下载完成时把 `文件名 → {project_id, slug, title, version, ts, source}`
记到 ``data/instance_mods/<实例id>.json``（**不写进游戏目录**，外部实例的
mods 目录可能只读，且不该污染玩家文件）。

带来的好处：
* 模组列表能标「资源中心」or「本地」；
* 更新检测对已知来源直接用 project_id，不用再猜文件名（猜错的经典案例：
  ``fabric-api-0.92.2+1.20.1.jar`` 会被剥成 ``fabric-api``，但 ``sodium-fabric-...``
  常常剥错）。
"""
from __future__ import annotations

import json
import os
import time

from ..paths import get_data_dir


def _path(inst) -> str:
    d = os.path.join(get_data_dir(), "instance_mods")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.json" % getattr(inst, "id", "inst"))


def load(inst) -> dict:
    """``{文件名: 记录}``；没有记录返回空 dict。"""
    try:
        with open(_path(inst), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        pass
    return {}


def save(inst, mapping: dict) -> None:
    """原子写（tmp + os.replace），坏在半路也不会留下半个 json。"""
    p = _path(inst)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def record(inst, entries) -> int:
    """登记一批下载（``entries``: 每项含 filename 与 project_id/slug/title）。

    返回实际写入条数。同名文件覆盖（重装/更新后仍然指向同一个 project）。
    """
    if not entries:
        return 0
    mapping = load(inst)
    n = 0
    now = time.time()
    for e in entries:
        fn = os.path.basename(str(e.get("filename") or ""))
        pid = str(e.get("project_id") or "")
        if not fn or not pid:
            continue
        mapping[fn] = {
            "project_id": pid,
            "slug": str(e.get("slug") or ""),
            "title": str(e.get("title") or ""),
            "version": str(e.get("version") or ""),
            "source": str(e.get("source") or "modrinth"),
            "ts": now,
        }
        n += 1
    if n:
        save(inst, mapping)
    return n


def forget(inst, filename: str) -> None:
    mapping = load(inst)
    if mapping.pop(os.path.basename(filename), None) is not None:
        save(inst, mapping)


def prune(inst, existing_names) -> None:
    """删掉已经不存在的文件记录（玩家手删/更新改名后留的孤儿）。"""
    mapping = load(inst)
    keep = {k: v for k, v in mapping.items() if k in set(existing_names)}
    if len(keep) != len(mapping):
        save(inst, keep)


def slug_map(inst) -> dict:
    """``{文件名: slug}`` —— 给更新检测用（优先真 slug，别再猜文件名）。"""
    return {fn: str(v.get("slug") or "") for fn, v in load(inst).items()
            if v.get("slug")}
