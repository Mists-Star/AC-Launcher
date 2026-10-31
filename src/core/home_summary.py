"""Home summary（首页两问）— Qt-free「继续哪个 / 哪些挡住你」。

对齐 LumilioCL 的 ``HomeSummary``：

* ``continue_with`` —— 最近玩过、且**没有 Error 级问题**的实例。
  「启动不了的实例不提供继续」。
* ``needs_attention`` —— 有 Warning 及以上问题的实例，每个实例只显示
  **最严重的一条** + 还有几条；Info（如「还没安装」）不计。排序口径：
  严重级 → 最近玩过 → 实例 id（稳定）。

本模块不导入 Qt。``summarize`` 是纯函数（只依赖入参）；磁盘/Java 探测
集中在 ``diagnose_instance``，健康扫描走 ``scan_health_cached``（TTL 缓存，
避免首页每次刷新都把模组 jar 读一遍）。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .mod_check import SEV_CRITICAL, SEV_INFO, SEV_WARNING

# 严重级排序：数字越小越严重；Info 不进入汇总。
_SEV_RANK = {SEV_CRITICAL: 0, SEV_WARNING: 1}

# 健康扫描 TTL（秒）。首页刷新频繁，但模组目录不变时没必要重扫。
_HEALTH_TTL = 90.0
_HEALTH_CACHE: dict[str, tuple[float, tuple, dict]] = {}


@dataclass
class Problem:
    """一条「挡住你」的问题（已归一到首页可展示的形状）。"""
    kind: str
    severity: str
    title_key: str
    meta: dict = field(default_factory=dict)
    action: str = "instances"          # fix / java / login / instances
    action_key: str = "home.attn.action.view"
    fix: dict | None = None


@dataclass
class AttentionItem:
    """首页一行「需要留意」。"""
    instance_id: str
    instance_name: str
    severity: str
    kind: str
    title_key: str
    meta: dict = field(default_factory=dict)
    more: int = 0                      # 同一实例另有几条（Warning 及以上）
    action: str = "instances"
    action_key: str = "home.attn.action.view"
    fix: dict | None = None


@dataclass
class HomeSummary:
    continue_with: str = ""
    needs_attention: list[AttentionItem] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0


# --------------------------------------------------------------------------- #
# diagnosis
# --------------------------------------------------------------------------- #
def _game_dir_ok(inst) -> bool:
    try:
        return os.path.isdir(getattr(inst, "mc_dir", "") or "")
    except OSError:
        return False


def _action_for(finding) -> tuple[str, str]:
    """Finding → 首页动作（fix 优先；Java 类问题去设置页）。"""
    fix = getattr(finding, "fix", None)
    if fix:
        return "fix", (fix.get("label") or "health.fix")
    if (getattr(finding, "kind", "") or "").startswith("java"):
        return "java", "home.attn.action.install_java"
    return "instances", "home.attn.action.view"


def diagnose_instance(inst, settings: dict | None = None, *,
                      findings: list | None = None,
                      session: dict | None = None) -> list[Problem]:
    """Lightweight per-instance diagnosis（只产出首页需要的 Warning+）。

    ``findings`` 为空时用 ``instance_health.quick_check``（Java / 内存 /
    启动参数，不扫模组）；传 ``scan_health`` 的结果可获得完整问题。
    """
    problems: list[Problem] = []

    if not _game_dir_ok(inst):
        problems.append(Problem(
            kind="game_dir_missing", severity=SEV_CRITICAL,
            title_key="home.attn.game_dir_missing",
            action="instances", action_key="home.attn.action.view"))

    if findings is None:
        try:
            from .instance_health import quick_check
            findings = quick_check(inst, settings)
        except Exception:  # noqa: BLE001 - 首页聚合绝不因单项检查失败而空
            findings = []

    for f in findings or []:
        sev = getattr(f, "severity", "")
        if sev not in _SEV_RANK:
            continue  # Info 不计
        action, action_key = _action_for(f)
        problems.append(Problem(
            kind=getattr(f, "kind", "") or "health",
            severity=sev,
            title_key=getattr(f, "title", "health.dialog_title"),
            meta=dict(getattr(f, "meta", None) or {}),
            action=action, action_key=action_key,
            fix=getattr(f, "fix", None)))

    if isinstance(session, dict):
        outcome = (session.get("outcome") or "").strip()
        if outcome in ("failed", "crashed"):
            reason = (session.get("reason") or "").strip()[:80]
            problems.append(Problem(
                kind="last_session_failed", severity=SEV_WARNING,
                title_key=("home.attn.last_session_failed" if reason
                           else "home.attn.last_session_failed_generic"),
                meta={"reason": reason} if reason else {},
                action="instances", action_key="home.attn.action.view"))
    return problems


def _mods_stamp(inst) -> int:
    try:
        mods = getattr(inst, "mods_dir", None) or os.path.join(
            getattr(inst, "mc_dir", "") or "", "mods")
        return int(os.stat(mods).st_mtime_ns)
    except (OSError, TypeError, ValueError):
        return 0


def _settings_sig(settings: dict | None) -> tuple:
    s = settings or {}
    return (s.get("ram_mb"), s.get("java_auto"), s.get("java_path"),
            s.get("jvm_preset"))


def scan_health_cached(inst, settings: dict | None = None) -> dict:
    """``instance_health.scan_health`` + 90s 缓存（模组/设置不变即复用）。"""
    from .instance_health import scan_health

    settings = settings or {}
    key = (getattr(inst, "id", ""), getattr(inst, "mc_dir", ""),
           _mods_stamp(inst), _settings_sig(settings),
           getattr(inst, "java_path", ""), getattr(inst, "ram_mb", 0),
           getattr(inst, "jvm_preset", ""), getattr(inst, "jvm_args", ""),
           getattr(inst, "game_args", ""), getattr(inst, "perf_g1gc", True))
    now = time.time()
    hit = _HEALTH_CACHE.get(key[0])
    if hit is not None and hit[0] > now and hit[1] == key:
        return hit[2]
    result = scan_health(inst, settings)
    _HEALTH_CACHE[key[0]] = (now + _HEALTH_TTL, key, result)
    return result


def diagnose_instances(instances, settings: dict | None = None, *,
                       health_ids=None, with_account: bool = True,
                       has_account: bool = True,
                       sessions: dict | None = None) -> HomeSummary:
    """Convenience layer used by the home page（I/O 只发生在本次调用）。"""
    health_ids = set(health_ids or ())
    sessions = sessions or {}
    problems: dict[str, list[Problem]] = {}
    for inst in instances or []:
        iid = getattr(inst, "id", "")
        if not iid:
            continue
        if iid in health_ids:
            try:
                findings = scan_health_cached(inst, settings).get("findings") or []
            except Exception:  # noqa: BLE001 - 健康扫描失败退回廉价检查
                findings = None
        else:
            findings = None
        sess = sessions.get(iid)
        if sess is None:
            try:
                from .last_session import load as load_session
                sess = load_session(iid)
            except Exception:  # noqa: BLE001 - 会话记录缺失不影响聚合
                sess = None
        problems[iid] = diagnose_instance(inst, settings,
                                          findings=findings, session=sess)
    return summarize(instances, problems, with_account=with_account,
                     has_account=has_account)


# --------------------------------------------------------------------------- #
# pure aggregation
# --------------------------------------------------------------------------- #
def summarize(instances, problems_by_id: dict[str, list[Problem]], *,
              with_account: bool = True,
              has_account: bool = True) -> HomeSummary:
    """Turn per-instance problems into ``HomeSummary``（纯函数）。

    ``instances`` 只需 ``id/name/last_played`` 三个属性（摘要索引即可）。
    """
    instances = list(instances or [])
    names = {getattr(i, "id", ""): getattr(i, "name", "") for i in instances}
    last = {getattr(i, "id", ""): float(getattr(i, "last_played", 0) or 0)
            for i in instances}

    blocked: set[str] = set()
    errors = warnings = 0
    items: list[AttentionItem] = []

    for iid, problems in (problems_by_id or {}).items():
        shown = [p for p in problems if p.severity in _SEV_RANK]
        if not shown:
            continue
        shown.sort(key=lambda p: (_SEV_RANK[p.severity], p.kind))
        worst = shown[0]
        if worst.severity == SEV_CRITICAL:
            blocked.add(iid)
            errors += 1
        else:
            warnings += 1
        items.append(AttentionItem(
            instance_id=iid,
            instance_name=names.get(iid, ""),
            severity=worst.severity,
            kind=worst.kind,
            title_key=worst.title_key,
            meta=dict(worst.meta),
            more=max(0, len(shown) - 1),
            action=worst.action,
            action_key=worst.action_key,
            fix=worst.fix))

    if with_account and not has_account and instances:
        items.append(AttentionItem(
            instance_id="", instance_name="", severity=SEV_WARNING,
            kind="no_account", title_key="home.attn.no_account",
            action="login", action_key="home.attn.action.login"))
        warnings += 1

    # 继续 = 最近玩过、且没有 Error 的实例（没有游玩记录就不提供）。
    candidates = [iid for iid in last
                 if last[iid] > 0 and iid not in blocked]
    continue_with = max(candidates, key=lambda x: (last[x], x)) if candidates else ""

    items.sort(key=lambda it: (
        _SEV_RANK.get(it.severity, 2),
        -last.get(it.instance_id, 0),
        it.instance_id or "~"))

    return HomeSummary(continue_with=continue_with,
                       needs_attention=items,
                       errors=errors, warnings=warnings)
