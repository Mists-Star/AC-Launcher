"""Source chain（来源链）— Qt-free 候选展开 + 逐源失败记录。

对齐 LumilioCL 的传输模型：来源不是「全局布尔开关」，而是一条
``SourceProvider → SourceChain`` 的提供者链：

    候选列表 = 所有 provider 依次展开、去重、去空；顺序即优先级。

* ``OfficialProvider`` —— 原样返回官方 URL；
* ``PrefixMirrorProvider`` —— 按 ``MirrorRule`` 数据表把官方前缀替换成镜像前缀
  （AC 现有 BMCLAPI 规则原样搬进来，加镜像 = 加一条规则）；
* ``SourceChain`` —— 按偏好（仅官方 / 官方优先 / 镜像优先）+ 本次安装的
  失效主机集合生成最终候选。

``SourceTrace`` 记录「每个试过的来源 + 失败原因」，供任务记录 / 下载详情
显示；它只记失败（成功只记最后一条），避免上千个文件的成功把失败挤出窗口。

本模块不导入 Qt，可无头测试；也不发任何请求。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# 来源偏好（对齐 Lumilio 的三档）。
OFFICIAL_ONLY = "official_only"
OFFICIAL_FIRST = "official_first"
MIRROR_FIRST = "mirror_first"

_PREFS = {OFFICIAL_ONLY, OFFICIAL_FIRST, MIRROR_FIRST}


@dataclass(frozen=True)
class MirrorRule:
    """一条镜像规则（纯数据，不写代码分支）。"""
    official_prefix: str
    mirror_prefix: str
    name: str = "mirror"

    def match(self, url: str) -> str | None:
        """前缀匹配且落在路径边界上时返回替换后的 URL，否则 None。"""
        if not url.startswith(self.official_prefix):
            return None
        rest = url[len(self.official_prefix):]
        if rest and not rest.startswith("/"):
            return None
        return self.mirror_prefix + rest


@dataclass(frozen=True)
class Candidate:
    """一个候选来源 + URL。

    ``origin_host`` + ``mirrored`` 用于失效主机过滤 —— 只跳过**镜像**候选，
    官方候选即使同主机曾被镜像拒绝也必须保留（它就是回退目标）。
    """
    source: str
    url: str
    origin_host: str = ""
    mirrored: bool = False


class SourceProvider:
    """来源提供者协议：给定原始 URL → 若干候选（顺序即优先级）。"""
    name = "provider"
    max_concurrency = 16

    def candidates(self, url: str) -> list[Candidate]:  # pragma: no cover - 协议
        raise NotImplementedError


class OfficialProvider(SourceProvider):
    """官方源：原样返回（空 URL / 非 http 不产出）。"""
    name = "official"
    max_concurrency = 0      # 0 = 不限制（官方源没有并发上限语义）

    def candidates(self, url: str) -> list[Candidate]:
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return []
        try:
            host = url.split("/")[2]
        except IndexError:
            host = ""
        return [Candidate(self.name, url, host)]


class PrefixMirrorProvider(SourceProvider):
    """前缀镜像提供者：规则命中才产出镜像候选。"""

    def __init__(self, rules: list[MirrorRule], *, name: str = "bmclapi",
                 max_concurrency: int = 16) -> None:
        self._rules = list(rules or [])
        self.name = name
        self.max_concurrency = max(1, int(max_concurrency or 16))

    def candidates(self, url: str) -> list[Candidate]:
        if not isinstance(url, str):
            return []
        out: list[Candidate] = []
        for rule in self._rules:
            mirrored = rule.match(url)
            if mirrored is None:
                continue
            try:
                origin = url.split("/")[2]
            except IndexError:
                origin = ""
            # 规则级名字优先：同一 provider 下可以有多条不同镜像。
            src = rule.name if rule.name != "mirror" else self.name
            out.append(Candidate(src, mirrored, origin, mirrored=True))
        return out


class SourceChain:
    """把 provider 展开成候选链；偏好决定顺序。"""

    def __init__(self, providers: list[SourceProvider],
                 prefer: str = OFFICIAL_FIRST) -> None:
        self._providers = list(providers or [])
        self.prefer = prefer if prefer in _PREFS else OFFICIAL_FIRST

    def preferred_concurrency(self) -> int:
        """取第一个提供者的并发上限（0 = 不限制 → 不采用）。"""
        for p in self._providers:
            n = int(getattr(p, "max_concurrency", 0) or 0)
            if n > 0:
                return n
        return 0

    def candidates(self, url: str, *, dead: set | None = None,
                   prefer: str | None = None) -> list[Candidate]:
        """返回去重后的候选列表；``dead`` 里的主机名会被跳过。"""
        pref = prefer if prefer in _PREFS else self.prefer
        official: list[Candidate] = []
        mirror: list[Candidate] = []
        for provider in self._providers:
            if pref == OFFICIAL_ONLY and provider.name != "official":
                continue
            try:
                got = provider.candidates(url)
            except Exception:  # noqa: BLE001 - 单个 provider 坏掉不影响链
                got = []
            if provider.name == "official":
                official.extend(got)
            else:
                mirror.extend(got)
        if pref == MIRROR_FIRST:
            rows = mirror + official
        elif pref == OFFICIAL_ONLY:
            rows = official
        else:
            rows = official + mirror
        seen: set[str] = set()
        out: list[Candidate] = []
        for c in rows:
            if not c or not c.url or c.url in seen:
                continue
            if dead and c.mirrored and c.origin_host and c.origin_host in dead:
                continue
            seen.add(c.url)
            out.append(c)
        return out


@dataclass
class SourceAttempt:
    """一次来源尝试（失败时保留原因）。"""
    source: str
    url: str
    reason: str = ""
    status: int | None = None
    ok: bool = False
    t: float = field(default_factory=time.time)

    def line(self) -> str:
        """人读一行（技术详情用；不翻译产品名 / HTTP 状态）。"""
        bits = [self.source]
        if self.status:
            bits.append("HTTP %s" % self.status)
        if self.reason and self.reason != ("HTTP %s" % self.status if self.status else ""):
            bits.append(self.reason)
        return " ".join(bits)


class SourceTrace:
    """一次安装的逐源记录（线程安全）。只保留最近 N 条失败。"""
    __slots__ = ("_lock", "_failures", "_last_ok", "_max", "__weakref__")

    def __init__(self, max_failures: int = 20) -> None:
        self._lock = threading.Lock()
        self._failures: list[SourceAttempt] = []
        self._last_ok: SourceAttempt | None = None
        self._max = max(1, int(max_failures or 20))

    def failure(self, source: str, url: str, reason: str = "",
                status: int | None = None) -> None:
        with self._lock:
            self._failures.append(SourceAttempt(
                source=source, url=url, reason=reason or "",
                status=status, ok=False))
            if len(self._failures) > self._max:
                self._failures = self._failures[-self._max:]

    def success(self, source: str, url: str) -> None:
        with self._lock:
            self._last_ok = SourceAttempt(source=source, url=url, ok=True)

    def failures(self) -> list[SourceAttempt]:
        with self._lock:
            return list(self._failures)

    def last_ok(self) -> SourceAttempt | None:
        with self._lock:
            return self._last_ok

    def sources(self) -> list[str]:
        """本次安装出现过的来源名（失败 + 最后成功），按首次出现排序。"""
        with self._lock:
            rows = list(self._failures)
            if self._last_ok is not None:
                rows.append(self._last_ok)
        seen: list[str] = []
        for a in rows:
            if a.source and a.source not in seen:
                seen.append(a.source)
        return seen

    def summary(self) -> list[str]:
        """TaskRecord.sources 用：最多 4 条失败 + 1 条最后成功。"""
        with self._lock:
            fails = list(self._failures)[-4:]
            ok = self._last_ok
        out = [a.line() for a in fails]
        if ok is not None:
            out.append("ok " + ok.source)
        return out[:5]

    def describe(self) -> str:
        """下载详情里的一行：失败来源 + 最后成功来源。"""
        with self._lock:
            fails = list(self._failures)[-3:]
            ok = self._last_ok
        parts = []
        for a in fails:
            text = a.line()
            if a.reason and a.reason not in text:
                text += " (%s)" % a.reason
            parts.append(text)
        if ok is not None:
            parts.append("→ " + ok.source)
        return " · ".join(parts)

    def reset(self) -> None:
        with self._lock:
            self._failures = []
            self._last_ok = None
