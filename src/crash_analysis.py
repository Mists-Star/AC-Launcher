"""Crash analysis — turn raw game logs / crash reports into plain-language
reasons + fix suggestions, and link them to the launcher's self-repair.

Two inputs are read for a given instance:
  - ``<mc_dir>/logs/latest.log`` — the run the game died on
  - ``<mc_dir>/crash-reports/*.txt`` — Mojang's structured crash dumps

Patterns are matched against both and folded into a single list of
``CrashFinding`` items, each with a severity, a human-readable cause, a fix
suggestion, and whether the launcher can attempt an automatic repair.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

SEV_CRITICAL = "critical"
SEV_WARNING = "warning"
SEV_INFO = "info"


@dataclass
class CrashFinding:
    kind: str                  # stable id, e.g. "mod_dep_missing"
    severity: str              # critical / warning / info
    title: str                 # short label
    reason: str                # what happened (plain language)
    suggestion: str            # what the player can do
    repairable: bool = False   # launcher can attempt auto-fix
    detail: str = ""           # raw log line / stack excerpt
    meta: dict = field(default_factory=dict)
    # round-204：从日志里猜出的「最可疑 mod / jar」——用户要的是「哪个模组」，
    # 不是「日志里有 Exception」。
    culprit: str = ""


# --------------------------------------------------------------------------- #
# pattern library
# --------------------------------------------------------------------------- #
# Each rule: (kind, severity, title_i18n_key, reason_i18n_key,
#             suggestion_i18n_key, repairable, regex_flags)
# The *text* is resolved later (analysis returns keys; UI localizes). To keep
# this module UI-free we store i18n keys and let the dialog translate.

_RULES = [
    # ---- Fabric / Quilt mandatory dependencies ----
    (
        "mod_dep_missing", SEV_CRITICAL, "crash.kind.mod_dep_missing",
        "crash.reason.mod_dep_missing", "crash.fix.mod_dep_missing", True,
        re.compile(r"(Missing or unsupported mandatory dependencies|"
                   r"requires .* but could not find|"
                   r"Mod resolution failed|"
                   r"FormattedException: Mod resolution|"
                   r"requires .+ of .+ which is missing|"
                   r"missing dependency)", re.IGNORECASE),
    ),
    # ---- NoClassDefFound / NoSuchMethod (loader/version mismatch) ----
    (
        "loader_mismatch", SEV_CRITICAL, "crash.kind.loader_mismatch",
        "crash.reason.loader_mismatch", "crash.fix.loader_mismatch", True,
        re.compile(r"(NoClassDefFoundError|NoSuchMethodError|NoSuchFieldError|"
                   r"IncompatibleClassChangeError|"
                   r"ClassNotFoundException: .*Mod|"
                   r"Failed to load mod .* was compiled for|"
                   r"EntryPointNotFoundException)", re.IGNORECASE),
    ),
    # ---- Java version too old / too new ----
    (
        "java_version", SEV_CRITICAL, "crash.kind.java_version",
        "crash.reason.java_version", "crash.fix.java_version", True,
        re.compile(r"(UnsupportedClassVersionError|"
                   r"Bad class file|Java (SE )?Runtime Environment version|"
                   r"Unsupported major\.minor version|"
                   r"class file version \d+|"
                   r"requires Java \d+)", re.IGNORECASE),
    ),
    # ---- OutOfMemory ----
    (
        "out_of_memory", SEV_CRITICAL, "crash.kind.out_of_memory",
        "crash.reason.out_of_memory", "crash.fix.out_of_memory", True,
        re.compile(r"(OutOfMemoryError|Java heap space|Metaspace|"
                   r"not enough memory|Unable to create new native thread|"
                   r"GC overhead limit exceeded)", re.IGNORECASE),
    ),
    # ---- Graphics / driver ----
    (
        "gpu_driver", SEV_WARNING, "crash.kind.gpu_driver",
        "crash.reason.gpu_driver", "crash.fix.gpu_driver", False,
        re.compile(r"(GLFW error|OpenGL [Ee]rror|Failed to create window|"
                   r"Couldn't initialize GL|D3D11 device removed|"
                   r"Pixel format not accelerated)", re.IGNORECASE),
    ),
    # ---- Mixin / transformer ----
    (
        "mixin_error", SEV_WARNING, "crash.kind.mixin_error",
        "crash.reason.mixin_error", "crash.fix.mixin_error", False,
        re.compile(r"(Mixin apply for mod|Mixin transformation of|"
                   r"MixinTransformerError|InvalidMixin|"
                   r"Mixin apply failed|@Inject.*failed|"
                   r"mixin.*injection.*error)", re.IGNORECASE),
    ),
    # ---- Generic fatal exception ----
    (
        "fatal_exception", SEV_CRITICAL, "crash.kind.fatal_exception",
        "crash.reason.fatal_exception", "crash.fix.fatal_exception", False,
        re.compile(r"(Exception in thread \"(main|Client thread|Render thread)\"|"
                   r"A fatal error has been detected|"
                   r"ModLoadingException|Failed to load mod|"
                   r"E \[Terraria|Caused by: java\.)", re.IGNORECASE),
    ),
]


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def _read_text(path: str, limit: int = 4_000_000) -> str:
    """Read a file up to *limit* chars; never raise on missing/unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def latest_log_path(mc_dir: str) -> str:
    return os.path.join(mc_dir, "logs", "latest.log")


def crash_report_paths(mc_dir: str) -> list[str]:
    """Newest-first crash report files under crash-reports/."""
    d = os.path.join(mc_dir, "crash-reports")
    if not os.path.isdir(d):
        return []
    try:
        files = [
            os.path.join(d, n) for n in os.listdir(d)
            if n.lower().endswith((".txt", ".log"))
        ]
    except OSError:
        return []
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[:3]


# --------------------------------------------------------------------------- #
# round-204：结构化线索提取
# --------------------------------------------------------------------------- #
# 旧实现只在整段文本里 `rx.search()` 一次，把「命中了一行」当成结论，既不
# 说明是哪个模组，也不展示那一行原文 —— 玩家看到的就是「崩溃了，可能是
# Java 版本」这种废话。下面这组纯函数负责把日志变成「类别 + 可疑对象 +
# 原始证据行」，UI 只负责排版。
_JAR_RX = re.compile(r"([A-Za-z0-9_.+\-]+\.jar)", re.IGNORECASE)
# Fabric 崩溃报告 / 日志里出现过的「指名道姓」格式。
_CULPRIT_PATTERNS = (
    re.compile(r"Suspected mods?\s*:\s*([^\n]+)", re.IGNORECASE),
    re.compile(r"Mod File\s*:\s*([^\n]+?\.jar)", re.IGNORECASE),
    re.compile(r"Mod file\s+(\S+\.jar)", re.IGNORECASE),
    re.compile(r"Failed to load mod\s+[\"'`]?([^\s\"'`,]+)", re.IGNORECASE),
    re.compile(r"Mixin apply (?:for|to) (?:mod )?[\"'`]?([^\s\"'`]+)", re.IGNORECASE),
    re.compile(r"mixin\s+\S+\s+from\s+(?:mod\s+)?[\"'`]?([^\s\"'`]+)",
               re.IGNORECASE),
    re.compile(r"from\s+([^\s/\\]+\.jar)", re.IGNORECASE),
)


def guess_culprit(text: str, mods_dir: str = "") -> str:
    """从崩溃文本里猜「最可疑的 mod / jar」。

    优先采信日志/崩溃报告自己写出来的指名信息（``Suspected mods``、
    ``Mod File``、``Failed to load mod``、Mixin 的 from），最后才退回
    「文本里第一个 .jar」。``mods_dir`` 给出时，只把真实存在的 jar 当强证据，
    避免把 ``1.20.1.jar`` 这种游戏本体当成模组。
    """
    if not text:
        return ""
    real_jars: set[str] = set()
    if mods_dir and os.path.isdir(mods_dir):
        try:
            real_jars = {n.lower() for n in os.listdir(mods_dir)
                         if n.lower().endswith(".jar")}
        except OSError:
            real_jars = set()

    def _clean(value: str) -> str:
        v = (value or "").strip().strip("\"'`")
        v = v.split(",")[0].split(":")[0].strip()
        if not v:
            return ""
        base = os.path.basename(v.replace("\\", "/"))
        if base.lower().endswith(".jar"):
            return base
        return base

    for rx in _CULPRIT_PATTERNS:
        for m in rx.finditer(text):
            cand = _clean(m.group(1))
            if cand and cand.lower().endswith(".jar"):
                if real_jars and cand.lower() not in real_jars:
                    continue
                return cand
    # 指名信息里拿到的 mod id（没有 .jar 后缀）也值得展示
    for rx in _CULPRIT_PATTERNS:
        m = rx.search(text)
        if m:
            cand = _clean(m.group(1))
            if not cand:
                continue
            if (cand.lower().endswith(".jar") and real_jars
                    and cand.lower() not in real_jars):
                continue
            return cand
    # 最后：文本里真实存在于 mods 目录的 jar
    for m in _JAR_RX.finditer(text):
        cand = m.group(1)
        if cand.lower() in real_jars:
            return cand
    return ""


def _last_exception(text: str) -> str:
    """取最后一条「有信息量」的异常行（跳过 at ... 栈帧、空行与收尾日志）。"""
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not s or s.startswith("at ") or s.startswith("..."):
            continue
        # 只认真正的异常/失败行；"[main/ERROR]: Crash report saved ..." 这种
        # 收尾日志里有 ERROR 但不是错误本身，必须排除（否则弹窗会把它当
        # 「关键错误」展示，等于什么也没说）。
        if re.search(r"(Caused by:|(?:Exception|Error):|\bException\b|"
                     r"\bMixin apply\b|requires\b|FAILED)", s):
            return s[:260]
    return ""


def _gather_evidence(text: str, rx, limit: int = 6) -> list[str]:
    """收集某个规则匹配行 + 紧随的栈行 + Caused by 链，去重截断。

    旧实现只存 ``m.group(0)[:160]``：`OutOfMemoryError` 这一行本身通常没有
    任何上下文，玩家看不出是哪个模组/哪一步炸的。
    """
    lines = text.splitlines()
    out: list[str] = []
    hits = [i for i, ln in enumerate(lines) if rx.search(ln)]
    for i in hits[-2:]:
        for j in range(i, min(len(lines), i + 4)):
            s = lines[j].strip()
            if s and s not in out:
                out.append(s[:220])
    for m in re.finditer(r"Caused by: [^\n]+", text):
        s = m.group(0).strip()[:220]
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out[:limit]


def diagnose_latest(mc_dir: str) -> dict:
    """崩溃弹窗用的轻量结论：类别 + 可疑对象 + 关键错误行 + 证据。

    只读 latest.log 尾部与最近一份 crash-report，不扫 jar 目录，因此可以在
    UI 线程里直接调用（几十毫秒）。字段全部可能为空字符串 —— 调用方负责
    兜底文案，不要假设一定有值。
    """
    if not mc_dir:
        return {}
    parts: list[str] = []
    log = _read_text(latest_log_path(mc_dir))
    if log:
        parts.append(log[-20000:])
    for cp in crash_report_paths(mc_dir)[:1]:
        text = _read_text(cp, limit=1_500_000)
        if text:
            parts.append(text[:20000])
    text = "\n".join(parts)
    if not text:
        return {}
    matched: list[tuple[int, str, object]] = []
    for kind, _sev, _tk, _rk, _fk, _rep, rx in _RULES:
        m = rx.search(text)
        if m:
            matched.append((m.start(), kind, rx))
    # 按「首次出现位置」取最靠前的类别：日志里先炸的那一步才是根因
    # （Mixin 注入失败常带一条 Caused by: NoSuchMethodError，若按规则表顺序
    # 会误报成「加载器不匹配」）。
    matched.sort(key=lambda x: x[0])
    kind = matched[0][1] if matched else ""
    rx = matched[0][2] if matched else None
    return {
        "kind": kind,
        "kinds": [k for _pos, k, _r in matched],
        "culprit": guess_culprit(
            text, os.path.join(mc_dir, "mods")),
        "exception": _last_exception(text),
        "evidence": _gather_evidence(text, rx) if rx else [],
    }


def analyze_instance(inst) -> list[CrashFinding]:
    """Analyze an instance's logs + crash reports. Returns findings (may be empty)."""
    mc_dir = getattr(inst, "mc_dir", None) or ""
    if not mc_dir:
        return []
    findings: list[CrashFinding] = []
    seen_kinds: set[str] = set()
    evidence: dict[str, list[str]] = {}
    texts: list[str] = []

    # ---- latest.log (the run the game died on) ----
    log = _read_text(latest_log_path(mc_dir))
    if log:
        texts.append(log)
        for kind, sev, tkey, rkey, fkey, rep, rx in _RULES:
            if rx.search(log):
                seen_kinds.add(kind)
                evidence.setdefault(kind, []).extend(_gather_evidence(log, rx))
        # crash marker at the very end of a successful shutdown is normal
        if not seen_kinds:
            tail = log[-4000:].strip()
            if tail and "Stopping!" not in tail[-200:]:
                # generic "something happened" fallback only if it looks abnormal
                if re.search(r"(Exception|Error|FATAL)", tail, re.IGNORECASE):
                    seen_kinds.add("fatal_exception")
                    evidence.setdefault("fatal_exception", []).append(tail[-160:])

    # ---- crash-reports (structured dumps are more specific) ----
    for cp in crash_report_paths(mc_dir):
        text = _read_text(cp, limit=1_500_000)
        if not text:
            continue
        texts.append(text)
        for kind, sev, tkey, rkey, fkey, rep, rx in _RULES:
            if kind in seen_kinds:
                continue
            if rx.search(text):
                seen_kinds.add(kind)
                # round-204：不再只存命中片段，带上匹配行后面的栈帧与
                # Caused by 链 —— 玩家才能看到真正炸在哪。
                evidence.setdefault(kind, []).extend(_gather_evidence(text, rx))
                break  # one kind per report, most specific first
        # extract the top "Caused by" chain for the report's primary finding
        if "fatal_exception" not in seen_kinds and \
                re.search(r"(Exception in thread|Description:|java\.)", text):
            seen_kinds.add("fatal_exception")
            for m in re.finditer(r"(Caused by: [^\n]+)", text):
                evidence.setdefault("fatal_exception", []).append(m.group(1)[:160])
                if len(evidence["fatal_exception"]) >= 3:
                    break

    # round-204：整段日志找一个「最可疑的 mod / jar」，所有结论都带上它。
    # 没有它时玩家只知道「崩溃了」，无法判断该删哪个模组。
    joined = "\n".join(texts)
    culprit = guess_culprit(joined, os.path.join(mc_dir, "mods"))

    # ---- build findings ----
    for kind, sev, tkey, rkey, fkey, rep, _rx in _RULES:
        if kind not in seen_kinds:
            continue
        # round-71 展示打码：崩溃证据也可能含 accessToken/用户名，展示前过滤
        from .log_mask import mask_launch_text
        detail = mask_launch_text("\n".join(evidence.get(kind, [])))
        findings.append(CrashFinding(
            kind=kind, severity=sev,
            title=tkey, reason=rkey, suggestion=fkey,
            repairable=rep,
            detail=detail,
            culprit=culprit,
            meta={"culprit": culprit, "exception": _last_exception(joined)},
        ))
    # severity ordering: critical first
    findings.sort(key=lambda f: 0 if f.severity == SEV_CRITICAL else 1)
    return findings


# --------------------------------------------------------------------------- #
# mod dependency scan (auto-repair target)
# --------------------------------------------------------------------------- #
def scan_mod_manifests(inst) -> list[dict]:
    """Read dependency declarations from every jar in the instance's mods dir.

    Returns list of {mod_id, name, version, depends: [dep_id, ...]}.
    Recognises Fabric (fabric.mod.json) and Forge/NeoForge
    (META-INF/mods.toml) manifests.

    round-40 P2-14 性能：jar 超过 _MAX_SCAN_JARS 时跳过深扫（读 jar 元数据很
    慢，mod 上百个时 UI 线程会卡死）——调用方对空结果提示「mod 过多已跳过」。
    """
    import zipfile

    _MAX_SCAN_JARS = 60

    mods_dir = getattr(inst, "mods_dir", None) or os.path.join(
        getattr(inst, "mc_dir", ""), "mods")
    out: list[dict] = []
    if not os.path.isdir(mods_dir):
        return out
    jars = sorted(n for n in os.listdir(mods_dir) if n.lower().endswith(".jar"))
    if len(jars) > _MAX_SCAN_JARS:
        return []  # mod 极多时跳过，避免 UI 线程卡死
    for name in jars:
        path = os.path.join(mods_dir, name)
        try:
            with zipfile.ZipFile(path) as z:
                info = _manifest_from_zip(z)
        except (OSError, zipfile.BadZipFile):
            continue
        if info:
            out.append(info)
    return out


def _manifest_from_zip(z) -> dict | None:
    import json

    names = set(z.namelist())
    # ---- Fabric ----
    for cand in ("fabric.mod.json", "Fabric.mod.json", "fabric_mod.json"):
        if cand in names:
            try:
                data = json.loads(z.read(cand).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return None
            deps = []
            for d in (data.get("depends") or {}):
                deps.append(str(d))
            # round-201：provides 是「本 jar 对外提供的额外 id」——Cloth Config
            # 等改名项目会靠它兼容旧 dep id，判断「已装」时必须算进去。
            provides = [str(p) for p in (data.get("provides") or [])
                        if isinstance(p, str)]
            return {
                "mod_id": str(data.get("id", "")),
                "name": str(data.get("name") or data.get("id", "")),
                "version": str(data.get("version", "")),
                "depends": deps,
                "provides": provides,
            }
    # ---- Forge / NeoForge (mods.toml) ----
    if "META-INF/mods.toml" in names:
        try:
            text = z.read("META-INF/mods.toml").decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
        mod_id = _toml_attr(text, "modId")
        deps = re.findall(r"^\s*modId\s*=\s*\"([^\"]+)\"", text, re.MULTILINE)
        deps = [d for d in deps if d and d != mod_id]
        return {
            "mod_id": mod_id or "",
            "name": _toml_attr(text, "displayName") or mod_id or "",
            "version": _toml_attr(text, "version"),
            "depends": deps,
            "provides": [],
        }
    return None


def _toml_attr(text: str, key: str) -> str:
    m = re.search(rf"^{key}\s*=\s*\"([^\"]+)\"", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def find_missing_dependencies(inst) -> list[str]:
    """Return dependency ids declared by installed mods but not present
    anywhere in the same mods folder (best-effort).

    round-201：按**项目规范 id**（``core.mod_repair.canonical_id``）比较，
    并把 jar 声明的 ``provides`` 计入已装。Cloth Config 的 mod id 是
    ``cloth-config2``、Modrinth slug 是 ``cloth-config``；旧逻辑按字符串
    直接比较，装了也会误报缺、补装又搜不到。
    """
    from .core.mod_repair import canonical_id

    mods = scan_mod_manifests(inst)
    present: set[str] = set()
    for m in mods:
        for mid in [m.get("mod_id", "")] + list(m.get("provides") or []):
            cid = canonical_id(mid)
            if cid:
                present.add(cid)
    missing: set[str] = set()
    for m in mods:
        for dep in m.get("depends", []):
            cid = canonical_id(dep)
            if not cid or cid in present or cid in missing:
                continue
            # skip known "always-present" ids that aren't mods
            if cid in ("minecraft", "java", "fabricloader", "forge",
                       "neoforge", "quilt-loader", "fabric-api-base"):
                continue
            missing.add(cid)
    # drop deps that ARE provided by another installed mod id
    return sorted(missing)


def search_and_download_missing(inst, missing_ids: list[str],
                                callback=None) -> tuple[list[str], list[str]]:
    """兼容旧入口：委托 ``core.mod_repair``（round-178 统一实现）。

    round-177 在这里加了「带 MC 版本 / 加载器」「不用 hits[0] 兜底」；
    round-178 把扫描、精确匹配、分阶段失败原因收敛到 ``mod_repair``，
    避免崩溃弹窗 / 实例右键 / 体检对话框各写一套。旧签名保持不变。
    """
    from .core.mod_repair import repair_missing

    result = repair_missing(inst, missing_ids, callback)
    return result["downloaded"], [f["id"] for f in result["failed"]]
