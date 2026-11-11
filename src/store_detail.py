"""Store detail panel — per-mod info, version picker, translate, download.

round-66+85 资源中心详情页（round-85 重构为行卡片流，对齐主流启动器：
PCL2/HMCL 风格 = 头部信息 + 最新版本条 + 版本卡片列表，每行右侧直接下载：
* 展示项目信息（图标 / 标题 / 分类 / 下载量 / 作者 / 简介）
* 顶部「最新版本」条——最新版本一眼可见，点「下载」即装
* 其余版本以行卡片流展示（版本号 + MC + 加载器彩章 + 大小 + 日期 + 下载），
  按 MC 版本 + 加载器双重筛选；分页加载（每页 50），大项目不再一次拉全部
  （round-85：Fabric API 上千版本，分页后秒开）
* 中文说明："在 MC百科查看中文说明"外链（主流启动器做法，round-128）+
  机器翻译兜底；正文本身已是中文时直接显示、不消耗翻译额度
* 一键打开项目官网详情页

round-132：改为**页内面板**（QWidget），由资源中心用页内栈切换展示，
不再是独立 QDialog 弹窗；顶部「返回」回到资源列表，形状与实例页内嵌
向导一致。所有网络请求仍挂在后台 Worker(QThread)，绝不阻塞 UI。
"""
from __future__ import annotations

import os
import re
import time as _time
from collections import OrderedDict

# round-181：点开同一个项目不该重复拉版本列表 / 重复机翻。按
# (source, project_id) 做进程内 TTL 缓存 —— 主流启动器的详情页也是
# 「列表数据先立刻渲染，详情异步补一次，返回再点就是本地命中」。
_DETAIL_TTL = 600.0
_VERSION_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
_TRANSLATION_CACHE: "OrderedDict[str, tuple]" = OrderedDict()


def _cache_read(store, key):
    rec = store.get(key)
    if rec is None:
        return None
    ts, val = rec
    if _time.monotonic() - ts > _DETAIL_TTL:
        store.pop(key, None)
        return None
    store.move_to_end(key)
    return val


def _cache_write(store, key, val, cap=48):
    store[key] = (_time.monotonic(), val)
    store.move_to_end(key)
    while len(store) > cap:
        store.popitem(last=False)



from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QMessageBox, QFrame, QWidget, QButtonGroup,
    QScrollArea, QFileDialog, QProgressBar, QCheckBox, QSizePolicy,
)
from PySide6.QtCore import Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QDesktopServices, QPixmap

from .theme import COLORS, with_alpha, loader_vivid
from . import ui_kit
from .i18n import t
from .worker import ProgressWorker, Worker
from .async_image import get_image_loader

PAGE_SIZE = 50


# 加载器 → 徽章配色（对齐各加载器自身的品牌色，让加载器一眼可辨）。
# round-99 极简重构：**默认不使用**——13 个品牌色同屏时页面花而杂，加载器
# 徽章默认走全局中性 ``badge`` 类。只有主题包显式声明 ``"loader_vivid": true``
# （见 ``theme.loader_vivid()``）时才恢复品牌色（vivid 模式）。
LOADER_BADGE_COLORS = {
    "fabric":     "#B0633A",   # Fabric 沙金棕
    "forge":      "#E04E14",   # Forge 橙红
    "neoforge":   "#8B5CF6",   # NeoForge 紫
    "quilt":      "#2C9E8F",   # Quilt 青
    "liteloader": "#3B82F6",
    "legacyfabric": "#7C6BD6",
    "optifine":   "#F59E0B",
    "bukkit":     "#E2723B",
    "spigot":     "#E2723B",
    "paper":      "#C9B45B",
    "purpur":     "#C57B9A",
    "vanilla":    "#6B7280",
    "datapack":   "#0D9488",
}
LOADER_DEFAULT = "#6B7280"


def _human_size(n) -> str:
    """文件字节数 → 可读大小；空值给占位符。"""
    if not n:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _cjk_ratio(text: str) -> float:
    """汉字占非空白字符的比例（判断正文是否本身就是中文）。"""
    body = [c for c in (text or "") if not c.isspace()]
    if not body:
        return 0.0
    return sum(1 for c in body if "\u4e00" <= c <= "\u9fff") / len(body)


def _fetch_and_translate(card: dict) -> tuple[str, str | None]:
    """后台线程任务：取项目简介/README（body 优先）并机翻成中文。

    返回 (原文, 译文)。原文本身已经是中文时译文为 None（作者已提供中文
    说明，round-128：这种情况不再消耗翻译额度）。
    """
    from .net_api import get_project_info, translate_text, NetError
    desc = (card.get("description") or "").strip()
    body = ""
    try:
        p = get_project_info(card.get("slug") or card.get("project_id") or "")
        if p:
            body = (p.get("body") or "").strip()
    except NetError:
        pass  # 拿不到 README 就只翻译简介
    src = body if len(body) > len(desc) else desc
    if not src:
        raise NetError("该资源没有可翻译的简介/说明")
    # round-127: README 头部常是徽章图片 / 链接 / 裸 URL，既不展示、又白耗
    # 翻译额度（MyMemory 匿名额度约 1 万字符/天）。先剔噪声再截断——详情页
    # 原文区本来也只显示 1200 字符，翻 1600 足够读。
    src = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", src[:6000])
    src = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", src)
    src = re.sub(r"https?://\S+", " ", src)
    src = re.sub(r"<[^>]+>", " ", src)   # HTML 标签（<center>/<img> 等）不留残迹
    src = re.sub(r"[#>*`\[\]()~|_]+", " ", src)
    src = re.sub(r"\s{2,}", " ", src).strip()[:1600]
    # round-128：正文本来就是中文 -> 不机翻（准确、零额度消耗）。
    if _cjk_ratio(src) >= 0.2:
        return src, None
    return src, translate_text(src)


class _VersionRow(QFrame):
    """一行版本卡片：版本号 | MC 版本 | 加载器彩章 | 大小 | 日期 | 下载按钮。

    点击整行或右侧「下载」即下载该版本（对齐主流启动器的行内下载）。
    """

    def __init__(self, parent, ver: dict, is_latest: bool, on_download,
                 compatible: bool = True, reason: str = ""):
        super().__init__(parent)
        self._ver = ver
        self._compatible = compatible
        # round-99 极简：容器走全局 ``vrow`` 类（中性卡底 + 中性描边 +
        # hover 描边变亮），删除内联样式——内联样式不随主题切换刷新，且旧
        # hover 的 ``{accent}66`` 是错误 alpha（#RRGGBBAA 会被 Qt 当
        # #AARRGGBB 解析成荧光绿）。
        self.setProperty("cls", "vrow")
        self.setCursor(Qt.PointingHandCursor)
        accent = COLORS.get("accent", "#7C3AED")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(12)

        # 版本号（推荐加星：自绘星标，不用文本 ★）
        v_wrap = QWidget()
        # round-99：纯排布包装层挂 bare 类 —— 否则全局 QWidget 规则会给它
        # 画上 bg_app 底色，暗色主题下在行卡片上是一块深色补丁压住文字。
        v_wrap.setProperty("cls", "bare")
        vh = QHBoxLayout(v_wrap)
        vh.setContentsMargins(0, 0, 0, 0)
        vh.setSpacing(6)
        if is_latest:
            from .ui_kit import state_pix
            si = QLabel()
            si.setPixmap(state_pix("star", accent, 14))
            si.setFixedSize(15, 15)
            vh.addWidget(si)
        v_lbl = QLabel(ver.get("version_number", "—"))
        # round-99：颜色继承全局 text_main（不再按最新态染 accent——accent
        # 只留给左侧星标点缀）；字号/字重内联保留。
        # round-193：不兼容的版本整体压暗，并在行尾给一条原因（玩家一眼知道
        # 为什么这个版本不能装，而不是以为列表乱了）。
        _dim = "" if compatible else "color:%s;" % COLORS["text_disabled"]
        v_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: {'800' if is_latest else '600'};"
            f"{_dim}")
        v_lbl.setToolTip(t("store.detail_latest_tip") if is_latest else reason)
        vh.addWidget(v_lbl)
        if not compatible and reason:
            bad = QLabel(reason)
            bad.setProperty("cls", "sub")
            bad.setStyleSheet("font-size:11px;color:%s;"
                              % COLORS["danger"])
            vh.addWidget(bad)
        lay.addWidget(v_wrap)

        # MC 版本
        gvs = ver.get("game_versions", [])
        mc_lbl = QLabel("MC " + ", ".join(gvs[:2]) + (f" +{len(gvs)-2}" if len(gvs) > 2 else "") if gvs else "—")
        mc_lbl.setProperty("cls", "sub")
        lay.addWidget(mc_lbl)

        # 加载器徽章：默认中性（badge 类）；主题包 loader_vivid 时走品牌色
        loaders = ver.get("loaders", [])
        if loaders:
            ld_lbl = QLabel(loaders[0])
            if loader_vivid():
                colr = LOADER_BADGE_COLORS.get(loaders[0].lower(), LOADER_DEFAULT)
                ld_lbl.setStyleSheet(
                    f"color: {colr}; background: {with_alpha(colr, 0x1F)};"
                    f" border-radius: 8px; padding: 1px 8px;"
                    f" font-size: 11px; font-weight: 600;")
            else:
                ld_lbl.setProperty("cls", "badge")
            if len(loaders) > 1:
                ld_lbl.setText(f"{loaders[0]} +{len(loaders)-1}")
                ld_lbl.setToolTip(", ".join(loaders))
            lay.addWidget(ld_lbl)
        else:
            lay.addSpacing(1)

        lay.addStretch(1)

        # 大小 / 日期
        files = ver.get("files", [])
        size = files[0].get("size") if files else None
        s_lbl = QLabel(_human_size(size))
        s_lbl.setProperty("cls", "sub")
        s_lbl.setMinimumWidth(48)
        lay.addWidget(s_lbl)

        d_lbl = QLabel((ver.get("date_published", "") or "")[:10])
        d_lbl.setProperty("cls", "sub")
        d_lbl.setMinimumWidth(70)
        lay.addWidget(d_lbl)

        dl = QPushButton(t("store.download"))
        dl.setProperty("cls", "accent")
        dl.setCursor(Qt.PointingHandCursor)
        dl.setMinimumHeight(30)
        dl.setMinimumWidth(76)
        dl.clicked.connect(lambda: on_download(self._ver))
        lay.addWidget(dl)

        self._on_dl = on_download

    def mouseReleaseEvent(self, e):  # 整行点击 = 下载（与主流交互一致）
        if e.button() == Qt.LeftButton and self._on_dl:
            self._on_dl(self._ver)
        super().mouseReleaseEvent(e)


class StoreDetailPanel(QWidget):
    """资源详情页内嵌面板：信息头 + 最新版本条 + 版本卡片流（分页）+ 翻译 + 下载。"""

    back_requested = Signal()

    def __init__(self, parent, card: dict, category: str, inst, subdir: str,
                 instances=None):
        super().__init__(parent)
        self._card = card
        self._ck = "%s:%s" % (card.get("source") or "modrinth",
                              card.get("project_id") or card.get("slug") or "")
        self._category = category
        self._inst = inst
        self._instances = list(instances) if instances is not None else []
        self._subdir = subdir
        self._versions: list[dict] = []      # 已分页累积的全量版本
        self._deps: list[dict] = []          # round-193：推荐版本的前置清单
        self._workers: list = []
        self._img = get_image_loader()
        self._offset = 0                     # 服务端分页游标
        self._has_more = False
        # round-203：本详情页占用中的下载闸门 key（连点不再开第二个下载）
        self._dl_gate_keys: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ── 顶部返回条（round-132：详情是页内面板，返回列表不再关窗口）──
        top = QHBoxLayout()
        top.setSpacing(10)
        self.back_btn = QPushButton(t("common.back"))
        self.back_btn.setProperty("cls", "secondary")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setMinimumHeight(32)
        self.back_btn.clicked.connect(self._go_back)
        top.addWidget(self.back_btn)
        self.page_title = QLabel(t("store.detail_title"))
        self.page_title.setProperty("cls", "title")
        top.addWidget(self.page_title)
        top.addStretch(1)
        root.addLayout(top)

        # ── 正文：整页滚动（版本行不自己套滚动区，窄窗口下也能看全）──
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self._body = QWidget()
        bl = QVBoxLayout(self._body)
        bl.setContentsMargins(0, 0, 4, 0)
        bl.setSpacing(8)

        # ── ① 信息头：图标 + 标题 + 徽章 + 简介 + 在线页面 ──
        bl.addWidget(self._build_header())

        # ── ①b 下载目标（round-119）：实例列表 + 「不指定版本 · 另存为…」──
        bl.addLayout(self._build_target_bar())
        # 目标实例换了 → 「已安装」徽章跟着换（round-199）
        self.target_combo.currentIndexChanged.connect(
            lambda _i=0: self._refresh_installed_tag())
        self._refresh_installed_tag()

        # ── ② 最新版本条 ──
        bl.addWidget(self._build_latest())

        # round-193：前置模组区（装之前就摆出来，别等进游戏报缺前置）
        self.deps_box = QFrame()
        self.deps_box.setProperty("cls", "latest")
        dl = QHBoxLayout(self.deps_box)
        dl.setContentsMargins(13, 9, 11, 9)
        dl.setSpacing(10)
        self.deps_title = QLabel(t("store.deps_title"))
        self.deps_title.setProperty("cls", "sub")
        self.deps_title.setStyleSheet("font-weight: 700;")
        dl.addWidget(self.deps_title)
        self.deps_lbl = QLabel("")
        self.deps_lbl.setProperty("cls", "sub")
        self.deps_lbl.setWordWrap(True)
        dl.addWidget(self.deps_lbl, 1)
        self.deps_box.setVisible(False)
        bl.addWidget(self.deps_box)

        # round-193：下载进度（详情页内可见，不用回列表页看）
        self.dl_bar = QProgressBar()
        self.dl_bar.setProperty("cls", "slim")
        self.dl_bar.setTextVisible(False)
        self.dl_bar.setFixedHeight(8)
        self.dl_bar.setVisible(False)
        bl.addWidget(self.dl_bar)
        self.dl_speed = QLabel("")
        self.dl_speed.setProperty("cls", "sub")
        self.dl_speed.setVisible(False)
        bl.addWidget(self.dl_speed)

        # ── ③ 筛选栏 ──
        bl.addLayout(self._build_filter_bar())

        # ── ④ 版本行容器（行直接铺在页面流里） ──
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(6)
        self._rows.addStretch(1)
        bl.addWidget(self._rows_host)
        # round-205：版本行缓存 + 分批构建。旧实现每次筛选/翻页都把 N 行
        # 同步重建（每行 ~10 个控件），一页 50 行直接把 UI 线程顶住 ——
        # 这就是「出 mod 版本选择卡顿灾难」。现在：
        #   * 行按「版本+推荐态+兼容态」缓存，筛选只换可见性，不重建；
        #   * 新建行每批 8 个（QTimer 0ms 接力），首屏立刻可用；
        #   * 翻页追加不再把滚动条拉回顶部。
        self._row_cache: dict[str, _VersionRow] = {}
        self._rebuild_gen = 0
        self._pending_rows: list[dict] = []
        self._pending_i = 0
        self._latest_id: str | None = None

        # 加载更多
        more_row = QHBoxLayout()
        self.more_btn = QPushButton(t("store.detail_load_more"))
        # round-99：小动作按钮统一 cls="secondary"（中性描边），不再用
        # surface（surface 是卡片容器类，按钮上会 text-align:left/padding:0）
        self.more_btn.setProperty("cls", "secondary")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setMinimumHeight(32)
        self.more_btn.clicked.connect(self._load_more)
        more_row.addStretch(1)
        more_row.addWidget(self.more_btn)
        more_row.addStretch(1)
        bl.addLayout(more_row)

        # ── ⑤ 中文说明区 ──
        # round-143（用户拍板）：打开详情即自动机翻（gtx→MyMemory 兜底、带缓存），
        # 不再要求玩家点按钮或跳官网；MC百科按钮保留为社区中文条目入口。
        tl_row = QHBoxLayout()
        self.mcmod_btn = QPushButton(t("store.detail_mcmod"))
        self.mcmod_btn.setProperty("cls", "secondary")
        self.mcmod_btn.setCursor(Qt.PointingHandCursor)
        self.mcmod_btn.clicked.connect(self._open_mcmod)
        tl_row.addWidget(self.mcmod_btn)
        self.translate_btn = QPushButton(t("store.detail_translate"))
        # round-99：改 cls="secondary"（中性描边小按钮）——旧 surface 类在
        # 按钮上是左对齐/零内边距，显示成裸文字"链接"，与页面按钮体系不一致
        self.translate_btn.setProperty("cls", "secondary")
        self.translate_btn.setCursor(Qt.PointingHandCursor)
        self.translate_btn.clicked.connect(self._translate)
        tl_row.addWidget(self.translate_btn)
        self.tr_status = QLabel("")
        self.tr_status.setProperty("cls", "sub")
        tl_row.addWidget(self.tr_status, stretch=1)
        bl.addLayout(tl_row)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(t("store.detail_text_hint"))
        self.text.setMaximumHeight(96)
        bl.addWidget(self.text)

        # ── ⑥ 底部状态（下载进度/结果） ──
        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setProperty("cls", "sub")
        foot.addWidget(self.status, stretch=1)
        bl.addLayout(foot)

        bl.addStretch(1)
        self.body_scroll.setWidget(self._body)
        root.addWidget(self.body_scroll, stretch=1)

        self._load_first_page()
        # round-143（用户拍板）：描述默认直接机翻成中文——打开详情就自动翻，
        # 不再要求玩家先点按钮或跳官网；原文本身是中文时上层零成本直返。
        if (card.get("description") or "").strip():
            self._translate(auto=True)

    # ---------------- UI 构建 ----------------
    def _build_target_bar(self) -> QHBoxLayout:
        """Pick where the file lands: an existing instance, or just a folder.

        Round-119: the dialog used to be unreachable without an instance and
        every download required one. Launchers like PCL2/HMCL let you grab a
        file for *any* version — or simply save it without picking one — so
        the combo offers every instance plus a "save as…" entry that needs no
        instance at all.
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(t("store.detail_target"))
        lbl.setProperty("cls", "sub")
        row.addWidget(lbl)
        self.target_combo = QComboBox()
        self.target_combo.setMinimumHeight(32)
        self.target_combo.setMinimumWidth(240)
        for i in self._instances:
            self.target_combo.addItem(i.name, i.id)
        self.target_combo.addItem(t("store.detail_target_save"), "__save__")
        want = getattr(self._inst, "id", "") if self._inst is not None else ""
        idx = self.target_combo.findData(want) if want else -1
        self.target_combo.setCurrentIndex(idx if idx >= 0
                                          else self.target_combo.count() - 1)
        row.addWidget(self.target_combo)
        row.addStretch(1)
        return row

    def _current_inst(self):
        """Instance picked in the target combo, or ``None`` for "save as…"."""
        data = (self.target_combo.currentData()
                if hasattr(self, "target_combo") else "")
        if not data or data == "__save__":
            return None
        for i in self._instances:
            if i.id == data:
                return i
        return None

    def _installed(self) -> bool:
        """这个资源是否已装在当前目标实例的 mods/ 里（round-199）。

        与资源中心列表卡片同一判据（``mod_sources.is_installed``），避免
        「列表说装了、详情说不装」两套逻辑。
        """
        inst = self._current_inst()
        if inst is None:
            return False
        try:
            from .core import mod_sources
            return mod_sources.is_installed(
                inst,
                project_id=str(self._card.get("project_id", "") or ""),
                slug=str(self._card.get("slug", "") or ""),
                title=str(self._card.get("title", "") or ""),
            )
        except Exception:  # noqa: BLE001 - 判定失败按未装处理
            return False

    def _refresh_installed_tag(self) -> None:
        tag = getattr(self, "installed_tag", None)
        if tag is None:
            return
        tag.setVisible(self._installed() and self._category == "mod")

    def _build_header(self) -> QFrame:
        card = self._card

        head = QFrame()
        # round-99 极简：删除紫渐变（旧写法 stop:1 的 ``{accent}18`` 是错误
        # alpha → 实渲染成怪绿/荧光），改全局 ``hero`` 中性卡（panel 底 +
        # 中性描边）；强调色交给内容自身（下载按钮/星标）点缀。
        head.setProperty("cls", "hero")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 14, 14, 14)
        hl.setSpacing(14)

        self.thumb = QLabel()
        # round-180：详情页封面比列表大一号，建立清晰的层级差
        self.thumb.setFixedSize(88, 88)
        hl.addWidget(self.thumb, 0, Qt.AlignTop)
        if self._img and card.get("icon_url"):
            fb = QPixmap(88, 88)
            fb.fill(Qt.transparent)
            self._img.load(card.get("icon_url", ""), 88, self.thumb, fb)

        ti = QVBoxLayout()
        ti.setSpacing(5)
        self.title = QLabel(card.get("title", ""))
        # 详情页主标题用全站 big 类，不再和列表卡片同权重
        self.title.setProperty("cls", "big")
        self.title.setWordWrap(True)
        # round-218：wordWrap 只会在**空格**处折行，一整串没有空格的英文 mod
        # 名（或 120 字标题）仍会把详情页顶到窗口外。这里让水平方向忽略
        # sizeHint，超长无空格串直接裁切，不再参与最小宽度计算。
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title.setMinimumWidth(0)
        self.title.setToolTip(card.get("title", "") or "")
        ti.addWidget(self.title)

        meta = QHBoxLayout()
        meta.setSpacing(10)
        cat_b = QLabel(t(_cat_key(self._category)))
        # round-99：分类徽章走中性 badge 类（旧写法 accent 字+soft 底在
        # accent 变绿时不可读）
        cat_b.setProperty("cls", "badge")
        meta.addWidget(cat_b)
        _src = ("CurseForge" if card.get("source") == "curseforge"
                else "Modrinth")
        meta.addWidget(ui_kit.tag(
            _src, COLORS["bg_hover"], COLORS["text_sub"],
            font_size=10, radius=6, pad="2px 8px"))
        # round-199：详情页也标「已安装」——列表卡片早就有，进详情反而看不到
        # 是最容易重复下载的地方。切换「下载到」实例时同步刷新。
        self.installed_tag = ui_kit.tag(
            t("store.installed_tag"), COLORS["bg_hover"], COLORS["success"],
            font_size=10, radius=6, pad="2px 8px")
        self.installed_tag.setVisible(False)
        meta.addWidget(self.installed_tag)
        self.meta = QLabel(t("store.meta",
                             downloads=ui_kit.format_count(card.get("downloads", 0)),
                             author=card.get("author", "")))
        self.meta.setProperty("cls", "sub")
        meta.addWidget(self.meta)
        meta.addStretch(1)
        # 在线页面（子行右侧）：round-99 小动作按钮统一 cls="secondary"
        self.open_btn = QPushButton(t("store.detail_open"))
        self.open_btn.setProperty("cls", "secondary")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setMinimumHeight(28)
        # round-143 修：CF 卡片此前也拼 Modrinth 链接（点开必 404）。
        if card.get("source") == "curseforge":
            _cf_path = {"mod": "mc-mods", "modpack": "modpacks",
                        "shader": "shaders", "resourcepack": "resource-packs",
                        "datapack": "data-packs"}.get(self._category, "mc-mods")
            link = (f"https://www.curseforge.com/minecraft/{_cf_path}/"
                    f"{card.get('slug') or ''}")
        else:
            link = (f"https://modrinth.com/{_type_slug(self._category)}/"
                    f"{card.get('slug') or card.get('project_id')}")
        self.open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(link)))
        meta.addWidget(self.open_btn)
        ti.addLayout(meta)

        # round-199：简介不再按 240 字符硬切（半句话 + 无全文）。改为按当前
        # 宽度像素省略两行，完整内容进 tooltip；宽度变化时重折（_rewrap_desc）。
        self._desc_full = " ".join((card.get("description", "") or "").split())
        self.desc = QLabel("")
        self.desc.setProperty("cls", "sub")
        self.desc.setWordWrap(True)
        self.desc.setMaximumHeight(44)
        if self._desc_full:
            self.desc.setToolTip(self._desc_full)
        ti.addWidget(self.desc)
        hl.addLayout(ti, stretch=1)
        return head

    def _build_latest(self) -> QFrame:
        accent = COLORS.get("accent", "#7C3AED")
        box = QFrame()
        # round-99 极简：删除整块 accent 底纹（旧 ``{accent}14`` 底 +
        # ``{accent}40`` 描边均为错误 alpha → 渲染成怪绿，且色块压文字），
        # 改全局 ``latest`` 类：中性玻璃底 + 仅左侧 3px accent 竖条点缀。
        box.setProperty("cls", "latest")
        bi = QHBoxLayout(box)
        bi.setContentsMargins(13, 9, 11, 9)
        bi.setSpacing(10)

        tag = QWidget()
        tag.setAttribute(Qt.WA_StyledBackground, True)
        # round-99：tag 走中性 badge（旧 ``{accent}22`` 错误 alpha）
        tag.setProperty("cls", "badge")
        tag_lay = QHBoxLayout(tag)
        tag_lay.setContentsMargins(8, 1, 10, 1)
        tag_lay.setSpacing(6)
        from .ui_kit import state_pix
        si = QLabel()
        si.setPixmap(state_pix("star", accent, 14))
        si.setFixedSize(15, 15)
        tag_lay.addWidget(si)
        st = QLabel(t("store.detail_latest"))
        # 星标是唯一 accent 点缀（≤16px 图标，符合强调色规约）；文字中性
        st.setProperty("cls", "sub")
        st.setStyleSheet("font-weight: 700;")
        tag_lay.addWidget(st)
        bi.addWidget(tag)

        self.latest_ver = QLabel("—")
        self.latest_ver.setStyleSheet("font-size: 14px; font-weight: 700;")
        self.latest_ver.setToolTip(t("store.detail_latest_tip"))
        bi.addWidget(self.latest_ver)

        self.latest_loader = QLabel("")
        self.latest_loader.setProperty("cls", "sub")
        bi.addWidget(self.latest_loader)
        self.latest_mc = QLabel("")
        self.latest_mc.setProperty("cls", "sub")
        bi.addWidget(self.latest_mc)
        self.latest_size = QLabel("")
        self.latest_size.setProperty("cls", "sub")
        bi.addWidget(self.latest_size)
        self.latest_date = QLabel("")
        self.latest_date.setProperty("cls", "sub")
        bi.addWidget(self.latest_date)
        bi.addStretch(1)

        self.latest_btn = QPushButton(t("store.download"))
        self.latest_btn.setProperty("cls", "accent")
        self.latest_btn.setCursor(Qt.PointingHandCursor)
        self.latest_btn.setMinimumHeight(32)
        self.latest_btn.setEnabled(False)
        self.latest_btn.clicked.connect(self._download_latest)
        bi.addWidget(self.latest_btn)
        box.setVisible(False)
        self._latest_box = box
        return box

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)

        self.loader_lbl = QLabel(t("store.detail_filter_loader"))
        self.loader_lbl.setProperty("cls", "sub")
        bar.addWidget(self.loader_lbl)
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chips_box = QHBoxLayout()
        self._chips_box.setSpacing(6)
        self._loader_options: list[str] = []
        self._add_loader_chip("", t("store.detail_all_loader"), True)
        bar.addLayout(self._chips_box)

        self.filter_lbl = QLabel(t("store.detail_filter"))
        self.filter_lbl.setProperty("cls", "sub")
        bar.addWidget(self.filter_lbl)
        self.mc_filter = QComboBox()
        self.mc_filter.setProperty("cls", "surface")
        self.mc_filter.setMinimumWidth(128)
        self.mc_filter.currentIndexChanged.connect(self._rebuild_rows)
        bar.addWidget(self.mc_filter)

        # round-193：默认只看「兼容当前实例」的版本（可临时放开看全部）。
        # 用户原话：「模组最高版本推荐不是随着我版本加载器来选的有何作用？」
        self.compat_chk = QCheckBox(t("store.detail_compat_only"))
        self.compat_chk.setChecked(True)
        self.compat_chk.setToolTip(t("store.detail_compat_only_hint"))
        self.compat_chk.toggled.connect(self._on_compat_toggle)
        bar.addWidget(self.compat_chk)

        bar.addStretch(1)
        self.versions_lbl = QLabel(t("store.detail_loading"))
        self.versions_lbl.setProperty("cls", "sub")
        bar.addWidget(self.versions_lbl, alignment=Qt.AlignRight)
        return bar

    def _add_loader_chip(self, value: str, text: str, checked: bool = False):
        from PySide6.QtWidgets import QPushButton
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(checked)
        b.setCursor(Qt.PointingHandCursor)
        # round-99 极简：走全局 ``chip`` 类（中性卡底；选中 = accent 描边 +
        # 淡底点缀，由 QSS :checked 驱动）。删除内联样式——旧写法
        # ``$ACCENT15`` 用 accent + "26"（错误 alpha），且内联不随主题刷新。
        b.setProperty("cls", "chip")
        b.clicked.connect(self._rebuild_rows)
        self._chip_group.addButton(b, len(self._loader_options))
        self._loader_options.append(value)
        self._chips_box.addWidget(b)

    # ---------- helpers ----------
    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._rewrap_desc()

    def _rewrap_desc(self) -> None:
        """按当前宽度把头部简介折成最多两行（像素省略，tooltip 给全文）。"""
        if not hasattr(self, "desc") or not hasattr(self, "_desc_full"):
            return
        w = max(120, self.desc.width() - 2)
        if w == getattr(self, "_desc_width", 0):
            return
        self._desc_width = w
        from .mod_list import _wrap_by_width
        self.desc.setText(
            _wrap_by_width(self._desc_full, self.desc.fontMetrics(), w, 2))

    def _short(self, s: str, n: int) -> str:
        s = (s or "").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    def _loader(self) -> str:
        """当前选中的加载器筛选值（"" = 全部）。"""
        if not hasattr(self, "_chip_group"):
            return ""
        bid = self._chip_group.checkedId()
        if bid < 0 or bid >= len(self._loader_options):
            return ""
        return self._loader_options[bid]

    def _compat_of(self, ver: dict) -> tuple[bool, str]:
        """这个版本对**当前实例**（MC 版本 + 加载器）兼不兼容。

        用户原话：「模组最高版本推荐不是随着我版本加载器来选的有何作用？」
        —— 推荐必须跟着实例走：给一个装不上的"最新"毫无意义。
        """
        inst = self._current_inst() or self._inst
        if inst is None:
            return True, ""
        mc = str(getattr(inst, "game_version", "") or "")
        ld = str(getattr(inst, "loader", "") or "vanilla").lower()
        gvs = [str(g) for g in (ver.get("game_versions") or [])]
        lds = [str(x).lower() for x in (ver.get("loaders") or [])]
        if mc and gvs and mc not in gvs:
            return False, t("store.incompat_mc", mc=mc)
        if ld and ld != "vanilla" and lds and ld not in lds:
            return False, t("store.incompat_loader", loader=ld)
        return True, ""

    def _recommended(self) -> dict | None:
        """推荐版本：优先「兼容当前实例的正式版」，其次兼容版，最后最新。

        round-205：旧实现直接取「第一个兼容」——Modrinth 列表按发布时间倒序，
        第一个兼容常常是 beta/alpha；而下面的大按钮显示的正是这个推荐版本。
        推荐给普通玩家一个测试版，就是用户说的「版本建议很奇怪」。
        """
        ok_versions = [v for v in self._versions if self._compat_of(v)[0]]
        if ok_versions:
            stable = [v for v in ok_versions
                      if str(v.get("version_type") or "").lower()
                      in ("release", "")]
            return (stable or ok_versions)[0]
        return self._versions[0] if self._versions else None

    def _filtered(self) -> list[dict]:
        mc = self.mc_filter.currentData() or ""
        ld = self._loader()
        return [v for v in self._versions
                if (not mc or mc in v.get("game_versions", []))
                and (not ld or ld in v.get("loaders", []))]

    # ---------- 数据加载（分页） ----------
    def _load_first_page(self):
        self.versions_lbl.setText(t("store.detail_loading"))
        self.more_btn.setEnabled(False)
        self._fetch_page(offset=0, append=False)

    def _load_more(self):
        self.more_btn.setEnabled(False)
        self._fetch_page(offset=self._offset, append=True)

    def _fetch_page(self, offset: int, append: bool):
        if offset == 0 and not append:
            hit = _cache_read(_VERSION_CACHE, self._ck)
            if hit is not None:
                self.more_btn.setEnabled(True)
                self._versions = list(hit)
                self._has_more = len(self._versions) >= PAGE_SIZE
                self._offset = len(self._versions)
                self._on_versions_ready(appending=False)
                return
        from .net_api import (_curseforge_versions, _curseforge_versions_keyless,
                              _modrinth_versions, curseforge_available)
        if self._card.get("source") == "curseforge":
            if curseforge_available():
                w = Worker(_curseforge_versions,
                           self._card.get("project_id", ""), PAGE_SIZE, offset)
            else:
                # round-142：传 project_id（数字 id 走镜像文件列表；cfwidget
                # 对整合包 slug 404，slug 只作最后兜底）
                w = Worker(_curseforge_versions_keyless,
                           self._card.get("project_id", "")
                           or self._card.get("slug", ""), PAGE_SIZE, offset)
        else:
            # round-193：服务端按实例的 MC 版本 + 加载器过滤。
            # 原来拉的是「全量最新 50 条」—— Mod Menu 这种上千版本的模组，
            # 前 50 条全是 26.x 的新版本，**兼容 1.20.1 的版本在第 50+ 位**，
            # 于是「推荐版本」永远推荐一个装不上的。
            mc_f, ld_f = self._server_filters()
            w = Worker(_modrinth_versions, self._card.get("project_id", ""),
                       mc_f, ld_f, PAGE_SIZE, offset)

        def _on_ok(page: list):
            self.more_btn.setEnabled(True)
            page = page if isinstance(page, list) else []
            self._has_more = len(page) >= PAGE_SIZE
            self._offset = offset + len(page)
            if append:
                # 追加前先剔除已存在 id，避免重复行
                exist = {v.get("id") for v in self._versions}
                self._versions.extend(v for v in page if v.get("id") not in exist)
            else:
                self._versions = page
                _cache_write(_VERSION_CACHE, self._ck, list(page))
            self._on_versions_ready(appending=append)

        def _on_err(e):
            self.more_btn.setEnabled(True)
            self.versions_lbl.setText(t("store.detail_ver_err", e=e))
            if not self._versions:
                self._latest_box.setVisible(False)

        w.finished.connect(_on_ok)
        w.error.connect(_on_err)
        self._track(w)
        w.start()

    def _on_versions_ready(self, appending: bool):
        self.versions_lbl.setText(t("store.detail_n_versions", n=len(self._versions)))

        # 最新版本条：round-193 改成「最新**兼容**当前实例的版本」
        if self._versions and not appending:
            rec = self._recommended()
            if rec is not None:
                self._fill_latest(rec)
                self._latest_box.setVisible(True)

        # round-193：前置模组（跟着推荐版本走）
        if not appending:
            self._refresh_deps(rec)

        # MC 版本下拉聚合
        if not appending:
            seen = []
            for v in self._versions:
                for gv in v.get("game_versions", []):
                    if gv not in seen:
                        seen.append(gv)
            self.mc_filter.blockSignals(True)
            self.mc_filter.clear()
            self.mc_filter.addItem(t("store.detail_all_mc"), "")
            for gv in seen:
                self.mc_filter.addItem(gv, gv)
            self.mc_filter.blockSignals(False)

            # 加载器 chips：全量 + 各加载器
            seen_loaders = []
            for v in self._versions:
                for ld in v.get("loaders", []):
                    if ld not in seen_loaders:
                        seen_loaders.append(ld)
            for ld in seen_loaders:
                self._add_loader_chip(ld, ld)

        self.more_btn.setVisible(self._has_more)
        self.more_btn.setText(
            t("store.detail_more_n", n=len(self._versions) + PAGE_SIZE)
            if self._has_more else t("store.detail_all_loaded"))
        self.more_btn.setEnabled(self._has_more)
        # round-205：翻页追加时不重置滚动条（见 _rebuild_rows）。
        self._rebuild_rows(appending)

    def _fill_latest(self, v: dict):
        self.latest_ver.setText(v.get("version_number", "—"))
        files = v.get("files", [])
        if files:
            self.latest_ver.setToolTip(files[0].get("filename", ""))
        loaders = v.get("loaders", [])
        if loaders:
            if loader_vivid():
                text = ""
                for ld in loaders[:2]:
                    colr = LOADER_BADGE_COLORS.get(ld.lower(), LOADER_DEFAULT)
                    # round-91 去掉文本 ● 圆点：Windows 下可能渲染成彩色 emoji，
                    # 加载器名本身已带品牌色，点多余。
                    text += (f"<span style='color:{colr}; font-weight:700;'>{ld}</span>  ")
                self.latest_loader.setTextFormat(Qt.RichText)
                self.latest_loader.setText(text.strip())
            else:
                # round-99 极简：默认纯文本中性色（cls=sub），加载器名不染品牌色
                self.latest_loader.setTextFormat(Qt.PlainText)
                self.latest_loader.setText("  ".join(loaders[:2]))
        else:
            self.latest_loader.setText("—")
        gvs = v.get("game_versions", [])
        self.latest_mc.setText("MC " + ", ".join(gvs[:3]) if gvs else "")
        self.latest_size.setText(_human_size(files[0].get("size") if files else None))
        self.latest_date.setText((v.get("date_published", "") or "")[:10])
        self.latest_btn.setEnabled(True)
        self._latest_box.setVisible(True)

    # ---------- 行卡片渲染 ----------
    def _row_key(self, v: dict, compatible: bool, reason: str,
                 is_latest: bool) -> str:
        """缓存键：版本 + 推荐态 + 兼容态。任一项变化才需要新行。"""
        return "%s|%s|%s|%s" % (
            v.get("id") or v.get("version_number", ""),
            "1" if is_latest else "0",
            "1" if compatible else "0",
            reason or "")

    def _rebuild_rows(self, appending=False):
        """按当前筛选重建版本行（缓存复用 + 分批插入）。

        ``appending`` 为 True（「加载更多」）时不重置滚动条 —— 旧实现每次
        追加都 ``setValue(0)``，玩家刚滚到底部又被弹回第一行。
        """
        self._rebuild_gen += 1
        gen = self._rebuild_gen
        # 旧行移出布局但不销毁：筛选切回来时直接复用（hide 后才能被
        # insertWidget 重新按顺序摆放）。
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
        # round-193：星标给「推荐（最新且兼容当前实例）」，不兼容的行整体压暗
        rec = self._recommended()
        self._latest_id = rec.get("id") if rec else None
        self._pending_rows = self._filtered()
        self._pending_i = 0
        self.versions_lbl.setText(
            t("store.detail_shown", shown=len(self._pending_rows),
              total=len(self._versions)))
        self._flush_rows(gen)
        if not (isinstance(appending, bool) and appending):
            self.body_scroll.verticalScrollBar().setValue(0)

    def _flush_rows(self, gen: int) -> None:
        """插入下一批版本行；被新的筛选代际打断则立即停手。"""
        if gen != self._rebuild_gen:
            return
        BATCH = 8
        while self._pending_i < len(self._pending_rows) and BATCH > 0:
            v = self._pending_rows[self._pending_i]
            self._pending_i += 1
            BATCH -= 1
            ok, reason = self._compat_of(v)
            latest = v.get("id") == self._latest_id
            key = self._row_key(v, ok, reason, latest)
            row = self._row_cache.get(key)
            if row is None:
                row = _VersionRow(self._rows_host, v, latest,
                                  self._download_version,
                                  compatible=ok, reason=reason)
                self._row_cache[key] = row
            self._rows.insertWidget(self._rows.count() - 1, row)
            row.show()
        if self._pending_i < len(self._pending_rows):
            QTimer.singleShot(0, lambda g=gen: self._flush_rows(g))
        else:
            self._trim_row_cache()

    def _trim_row_cache(self) -> None:
        """限制缓存上限：只删除当前不在布局里的旧行，避免内存无限增长。"""
        LIMIT = 300
        if len(self._row_cache) <= LIMIT:
            return
        for key, row in list(self._row_cache.items()):
            if len(self._row_cache) <= LIMIT:
                break
            if row.isVisible():
                continue
            self._row_cache.pop(key, None)
            try:
                row.deleteLater()
            except RuntimeError:  # noqa: BLE001 - 已随面板销毁
                pass

    # ---------- 下载 ----------
    def _download_latest(self):
        # round-205：下载按钮必须下「卡片上显示的那个推荐版本」。旧实现取
        # `self._versions[0]`（列表第一条 = 最新发布），与推荐条显示的
        # 版本不一致 —— 玩家看到推荐 1.20.1 版，点下去却装了 1.21 版。
        v = self._recommended()
        if v:
            self._download_version(v)

    def _server_filters(self) -> tuple[str, str]:
        """给服务端过滤用的 (mc, loader)：

        * 勾着「只看兼容」→ 用目标实例的 MC 版本 + 加载器；
        * 取消勾选 → 空（拉全量版本）。
        """
        if not (hasattr(self, "compat_chk") and self.compat_chk.isChecked()):
            return "", ""
        inst = self._current_inst() or self._inst
        mc = str(getattr(inst, "game_version", "") or "") if inst else ""
        ld = str(getattr(inst, "loader", "") or "") if inst else ""
        if ld.lower() == "vanilla":
            ld = ""
        return mc, ld

    def _on_compat_toggle(self, _on: bool) -> None:
        """切换「只看兼容」→ 重新拉版本（服务端过滤变了）。"""
        self._versions = []
        self._offset = 0
        self._load_first_page()

    def _on_dl_progress(self, value: int, maximum: int) -> None:
        """下载进度（字节级 → 百分比；拿不到最大值就保持忙指示）。"""
        try:
            if maximum and maximum > 0:
                self.dl_bar.setRange(0, 100)
                self.dl_bar.setValue(int(value * 100 / maximum))
        except Exception:  # noqa: BLE001 - 进度显示失败不影响下载
            pass

    def _refresh_deps(self, ver: dict | None) -> None:
        """拉「推荐版本」的前置模组并显示出来（MR + CF + 跨源覆盖）。"""
        self.deps_box.setVisible(False)
        self._deps = []
        if not ver:
            return
        src = self._card.get("source", "")
        pid = self._card.get("project_id", "")
        if not pid:
            return
        inst = self._current_inst()
        mc = str(getattr(inst, "game_version", "") or "") if inst else ""
        ld = str(getattr(inst, "loader", "") or "") if inst else ""
        if ld.lower() == "vanilla":
            ld = ""
        try:
            if src == "curseforge":
                from .net_api import cf_version_dependencies
                fid = (ver.get("files") or [{}])[0].get("id") or ver.get("id")
                deps = cf_version_dependencies(pid, fid, mc, ld)
            else:
                from .net_api import (mod_version_dependencies,
                                      _override_companions, cf_project_title)
                vid = str(ver.get("id", "") or "")
                deps = mod_version_dependencies(pid, vid)
                # round-220：跨源「必需伴随」（Ultimine Unchained → FTB Ultimine）
                for c in _override_companions(pid, mc, ld):
                    if not any(str(d.get("project_id")) == c["project_id"]
                               for d in deps):
                        deps.append({"project_id": c["project_id"],
                                     "title": cf_project_title(c["project_id"]),
                                     "slug": "", "optional": False})
        except Exception:  # noqa: BLE001 - 依赖查询失败不挡住页面
            return
        if not deps:
            return
        self._deps = deps
        names = []
        for d in deps:
            mark = t("store.deps_installed") if self._dep_installed(d) \
                else t("store.deps_missing")
            names.append("%s（%s）" % (d.get("title", ""), mark))
        self.deps_lbl.setText(" · ".join(names))
        self.deps_box.setVisible(True)

    def _dep_installed(self, dep: dict) -> bool:
        """这个前置是不是已经装在实例里了（round-199：与列表页同一判据）。

        旧实现用「标题前 8 字符包含匹配」，``Sodium`` 会命中
        ``sodium-extra.jar`` —— 和 round-196 修掉的商品误报是同一个坑。
        """
        inst = self._current_inst()
        if inst is None:
            return False
        try:
            from .core import mod_sources
            return mod_sources.is_installed(
                inst,
                project_id=str(dep.get("project_id", "") or ""),
                slug=str(dep.get("slug", "") or ""),
                title=str(dep.get("title", "") or ""),
            )
        except Exception:  # noqa: BLE001 - 判定失败按未装处理
            return False

    def _ask_deps(self, ver: dict) -> bool:
        """下载前问一句「是否一并安装前置」。返回 True = 连前置一起装。

        没有前置 → 直接 True（不问）；玩家选「不装」→ False（只下本体）。
        """
        deps = self._deps
        if not deps and ver:
            src = self._card.get("source", "")
            pid = self._card.get("project_id", "")
            try:
                if src == "curseforge":
                    from .net_api import cf_version_dependencies
                    fid = (ver.get("files") or [{}])[0].get("id") or ver.get("id")
                    deps = cf_version_dependencies(pid, fid)
                else:
                    from .net_api import mod_version_dependencies
                    deps = mod_version_dependencies(
                        pid, str(ver.get("id", "") or ""))
            except Exception:  # noqa: BLE001
                deps = []
        if not deps:
            return True
        names = "\n".join("· %s" % d.get("title", "") for d in deps)
        box = QMessageBox(self)
        box.setWindowTitle(t("store.deps_title"))
        box.setText(t("store.deps_ask", n=len(deps)))
        box.setInformativeText(names)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        reply = box.exec()
        return reply == QMessageBox.Yes

    def _download_version(self, v: dict):
        """Download one version into the picked instance — or into a folder.

        Round-119: with "不指定版本 · 另存为…" selected the file is saved to a
        folder the user picks, no instance (and therefore no MC version) needed.
        """
        inst = self._current_inst()
        # round-199：记下这次真正写入的实例 —— 下载中途用户可能改「下载到」，
        # 来源记录必须落到文件实际所在的那个实例，不能跟着下拉框漂。
        self._dl_inst = inst
        slug = self._card.get("slug", "")
        ver = v.get("version_number", "")
        if inst is None:
            from .paths import get_data_dir
            start = os.path.join(get_data_dir(), "downloads")
            os.makedirs(start, exist_ok=True)
            folder = QFileDialog.getExistingDirectory(
                self, t("store.detail_save_title"), start)
            if not folder:
                self.status.setText(t("store.detail_no_folder"))
                return
            reply = QMessageBox.question(
                self, t("store.download_confirm_title"),
                t("store.detail_save_confirm", slug=slug, ver=ver,
                  folder=folder))
            if reply != QMessageBox.StandardButton.Yes:
                return
            dest = folder
            mc_version, loader = "", ""
        else:
            reply = QMessageBox.question(
                self, t("store.download_confirm_title"),
                t("store.detail_ver_confirm",
                  slug=slug, ver=ver, name=inst.name))
            if reply != QMessageBox.StandardButton.Yes:
                return
            dest = os.path.join(inst.game_dir, self._subdir)
            mc_version = getattr(inst, "game_version", "") or ""
            loader = getattr(inst, "loader", "") or ""
        from .net_api import (curseforge_available, download_mod_version_to,
                              download_cf_with_deps)
        # round-193：下载前问一句「前置要不要一起装」——玩家不该在进游戏报
        # 缺前置之后才知道这事。
        with_deps = self._ask_deps(v)
        # round-203：详情页单飞 —— 同一项目/版本只允许一个下载在跑。旧实现连点
        # 会各开一个 worker（本体 + 依赖各下一遍），带宽被自己抢掉，看起来
        # 就是「好几个下载一起占用」。
        from .core.dl_gate import claim, release as _release_gate
        _gate_key = "store:%s:%s" % (
            self._card.get("project_id") or self._card.get("slug", ""),
            v.get("id") or v.get("version_number", ""))
        if not claim(_gate_key):
            self.status.setText(t("store.download_busy"))
            return
        self._dl_gate_keys.add(_gate_key)
        self.status.setText(t("store.downloading", slug=slug))
        # round-193：详情页内可见的进度条 + 速度（不用回列表页看进度）
        self.dl_bar.setVisible(True)
        self.dl_bar.setRange(0, 0)
        self.dl_speed.setVisible(True)
        self.dl_speed.setText("")
        # 每次下载都重置（CF 分支不填 manifest，别让它读到上一次的）
        self._dl_manifest = []
        # round-111：改用 ProgressWorker，速度行进已有 status 标签
        # （本对话框没有独立进度条，速度是用户明确要的可观测项）。
        if self._card.get("source") == "curseforge":
            # round-220：CF 通道终于自动拉前置（FTB Ultimine → FTB Library 等），
            # 并把同 mod 旧版本 jar 删掉，避免新旧 FTB Library 共存崩游戏。
            f0 = (v.get("files") or [{}])[0]
            # round-222：不能用 `or` 回退——文件 id 是数字，0 / 空串会掉到
            # v["id"]（版本显示串，不是 fileID），与 round-221 修的 id=0 同源坑。
            raw_fid = f0.get("id")
            fid = v.get("id") if raw_fid is None or raw_fid == "" else raw_fid
            # round-221：版本条目现在带 sha1（从 CF 文件元数据取），透传给
            # 本体下载做完整性校验；round-220 重构时这个值一度是死值。
            w = ProgressWorker(
                download_cf_with_deps,
                str(self._card.get("project_id", "")), fid, dest,
                mc_version, loader,
                manifest_out=self._dl_manifest,
                with_deps=with_deps, inst=self._current_inst(),
                primary_sha1=f0.get("sha1", ""))
        else:
            # round-191：详情页「选择版本下载」同样登记来源，模组列表才能标出来
            self._dl_manifest = []
            w = ProgressWorker(
                download_mod_version_to,
                self._card.get("project_id", ""), v.get("id", ""), dest,
                mc_version, loader,
                manifest_out=self._dl_manifest,
                with_deps=with_deps,
            )
        w.speed.connect(lambda s: self.dl_speed.setText(s))
        w.progress.connect(self._on_dl_progress)

        def _finish_gate():
            """round-203：下载本体结束（成功/失败）即放开单飞闸门。"""
            if _gate_key in self._dl_gate_keys:
                self._dl_gate_keys.discard(_gate_key)
                try:
                    _release_gate(_gate_key)
                except Exception:  # noqa: BLE001
                    pass

        def _ok(p: str):
            _finish_gate()
            # round-193：说清楚「装了哪些文件」（本体 + 前置），别只报一个文件名
            names = [os.path.basename(p)]
            for item in (self._dl_manifest or []):
                fn = item.get("filename", "")
                if fn and fn not in names:
                    names.append(fn)
            msg = t("store.downloaded", file=os.path.basename(p))
            if len(names) > 1:
                msg += ("\n" + t("store.installed_files", n=len(names),
                                  files="、".join(os.path.basename(x)
                                                  for x in names[:6])))
            # round-193：装完再体检一次 —— 很多老模组在 Modrinth 上**没声明**
            # 依赖（Mod Menu 7.x 就不写 Fabric API），下载前的清单是空的，
            # 只能靠装完扫描实例的 mods 目录才发现「少了 Fabric API」。
            try:
                inst = self._current_inst()
                if inst is not None:
                    from .core.mod_check import scan_conflicts
                    res = scan_conflicts(inst)
                    miss = [f for f in (res.get("findings") or [])
                            if getattr(f, "kind", "") == "missing_dep"]
                    if miss:
                        msg += "\n" + t("store.missing_deps", n=len(miss))
            except Exception:  # noqa: BLE001 - 体检失败不影响下载结果
                pass
            self.status.setText(msg)
            self.dl_bar.setVisible(False)
            self.dl_speed.setVisible(False)
            self._record_sources()

        def _err(e):
            _finish_gate()
            self.status.setText(t("store.download_fail", e=e))
            self.dl_bar.setVisible(False)
            self.dl_speed.setVisible(False)

        w.finished.connect(_ok)
        w.error.connect(_err)
        self._track(w)
        w.start()

    def _record_sources(self) -> None:
        """把这次下载的文件登记到实例的模组来源表（区分资源中心 / 本地）。"""
        manifest = getattr(self, "_dl_manifest", None) or []
        inst = getattr(self, "_dl_inst", None) or self._current_inst() \
            or getattr(self, "_inst", None)
        if not manifest or inst is None:
            return
        card = getattr(self, "_card", None) or {}
        pid = str(card.get("project_id", ""))
        try:
            from .core import mod_sources
            mod_sources.record(inst, [{
                "filename": item.get("filename", ""),
                "project_id": item.get("project_id", ""),
                "slug": card.get("slug", "") if item.get("project_id") == pid
                        else "",
                "title": card.get("title", "") if item.get("project_id") == pid
                         else "",
                "source": card.get("source", "modrinth"),
            } for item in manifest])
        except Exception:  # noqa: BLE001 - 记录失败不影响下载结果
            pass
        self._dl_manifest = []
        self._refresh_installed_tag()

    # ---------- 中文说明 ----------
    def _open_mcmod(self):
        """打开 MC百科条目（中文说明的正解；找不到就退搜索页）。

        round-205：候选词按「中文短名 → 中文全名 → 标题 → slug」排序。
        MC百科是中文站，拿英文 slug 去搜基本查不到 —— 必须先试中文。
        """
        from .mod_names import cn_short, cn_name
        from .net_api import mcmod_best_entry, mcmod_search_url
        slug = self._card.get("slug") or ""
        title = self._card.get("title") or ""
        cands: list[str] = []

        def _add(value):
            v = str(value or "").strip()
            if v and v not in cands:
                cands.append(v)

        _add(cn_short(slug))
        # cn_name 形如「Sodium（钠·渲染优化）」：取括号里的第一个中文短语。
        full = cn_name(slug, "")
        if full:
            for lp, rp in (("（", "）"), ("(", ")")):
                i, j = full.find(lp), full.find(rp)
                if i >= 0 and j > i:
                    _add(full[i + 1:j].split("·")[0])
                    break
        _add(title)
        _add(slug)
        key = cands[0] if cands else ""
        self.mcmod_btn.setEnabled(False)
        self.tr_status.setText(t("store.detail_mcmod_searching"))
        w = Worker(mcmod_best_entry, cands)

        def _ok(url):
            self.mcmod_btn.setEnabled(True)
            self.tr_status.setText("")
            QDesktopServices.openUrl(QUrl(url))

        def _err(_e):
            # 网络异常不拦用户：直接开搜索页让他自己在浏览器里找。
            self.mcmod_btn.setEnabled(True)
            self.tr_status.setText("")
            QDesktopServices.openUrl(QUrl(mcmod_search_url(key)))

        w.finished.connect(_ok)
        w.error.connect(_err)
        self._track(w)
        w.start()

    # ---------- 翻译（打开即自动，按钮可重试） ----------
    def _translate(self, auto: bool = False):
        hit = _cache_read(_TRANSLATION_CACHE, self._ck)
        if hit is not None:
            self._render_translation(hit)
            return
        self.tr_status.setText(t("store.detail_translating"))
        self.translate_btn.setEnabled(False)
        w = Worker(_fetch_and_translate, self._card)

        def _ok(pair):
            _cache_write(_TRANSLATION_CACHE, self._ck, pair)
            self._render_translation(pair)

        def _err(e):
            self.translate_btn.setEnabled(True)
            if auto:
                # 自动翻译失败不打扰：保留头部英文简介即可，按钮仍可手动重试。
                self.tr_status.setText("")
            else:
                self.tr_status.setText(t("store.detail_translate_fail", e=e))

        # round-205：修复缩进错位 —— 旧代码把 `_err` / connect / start 全塞进
        # `_render_translation` 的方法体，`_translate` 定义完 `_ok` 就结束了：
        # Worker 从未 start()（「翻译半天没动静」），缓存命中路径还会 NameError。
        w.finished.connect(_ok)
        w.error.connect(_err)
        self._track(w)
        w.start()

    def _render_translation(self, pair):
        self.translate_btn.setEnabled(True)
        src, tr = pair
        if tr is None:
            # round-128：原文已是中文，没走机翻。
            self.text.setPlainText(src)
            self.tr_status.setText(t("store.detail_native_cn"))
            return
        disp = tr or ""
        self.text.setPlainText(
            f"── {t('store.detail_original')} ──\n{src}"
            f"\n\n── {t('store.detail_translated')} ──\n{disp}"
        )
        # 头部短简介也换成中文（默认视图不再让玩家先看到英文）。
        # round-199：同样改成像素省略 + 全文 tooltip，不再按 240 字符硬切。
        self._desc_full = " ".join(disp.split())
        if self._desc_full:
            self.desc.setToolTip(self._desc_full)
        self._desc_width = 0
        self._rewrap_desc()
        self.tr_status.setText(t("store.detail_translated_ok"))

    # ---------- 生命周期 ----------
    def _track(self, w):
        self._workers.append(w)
        w.finished.connect(lambda _p: self._retire(w))
        w.error.connect(lambda _e: self._retire(w))

    def _retire(self, w):
        try:
            self._workers.remove(w)
        except ValueError:
            pass

    def _go_back(self):
        """返回资源列表：先停掉在跑的 Worker，再通知宿主切回列表。"""
        self.shutdown()
        self.back_requested.emit()

    def shutdown(self):
        """停止所有在跑的 Worker（面板被移出页内栈时由宿主调用）。"""
        for w in list(self._workers):
            try:
                if w.isRunning():
                    w.requestInterruption()
            except RuntimeError:
                pass
        self._workers.clear()
        # round-203：面板走了但下载线程可能还没退，闸门必须跟着放 —— 否则
        # 同一个项目的下一次下载会被误判为「已有下载在进行」。
        try:
            from .core.dl_gate import release
            for key in list(self._dl_gate_keys):
                release(key)
            self._dl_gate_keys.clear()
        except Exception:  # noqa: BLE001 - 闸门释放失败不影响关闭
            pass


def _cat_key(category: str) -> str:
    """store 内部 project_type → i18n key（分类徽章文案）。"""
    return {
        "mod": "store.cat_mod", "modpack": "store.cat_modpack",
        "shader": "store.cat_shader", "resourcepack": "store.cat_respack",
        "datapack": "store.cat_datapack",
    }.get(category, "store.cat_mod")


def _type_slug(category: str) -> str:
    # store 内部 project_type → Modrinth URL path
    return {
        "mod": "mod", "modpack": "modpack", "shader": "shader",
        "resourcepack": "resourcepack", "datapack": "datapack",
    }.get(category, "mod")