"""Music player page (direction B 彩蛋, FMCL-style).

A dedicated launcher music page: multi-file playlist, play modes
(loop / sequential / shuffle), volume, play/pause/skip controls.
Feeds the global MusicPlayer singleton in core.sound so the BGM keeps
playing while the user browses other pages.
"""
import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QComboBox, QSlider,
)

from .theme import COLORS, RoundedCard
from .icons import icon
from .i18n import t
from . import ui_kit
from .core.sound import music
from .win_rounded import pick_files, pick_folder, info
from .settings_dialog import load_config, save_config


def _current_cfg() -> dict:
    cfg = load_config()
    files = cfg.get("bgm_files") or []
    if not files and cfg.get("bgm_file"):
        files = [cfg["bgm_file"]]
    return {**cfg, "bgm_files": [f for f in files if f]}


class MusicPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg = _current_cfg()
        self._tracks: list[str] = list(self._cfg.get("bgm_files", []))
        self._player = music()

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        # ── header ──
        self.clear_btn = ui_kit.make_button(
            t("music.clear"), kind="secondary", on_click=self._clear, min_h=36)
        root.addWidget(ui_kit.page_header(
            t("music.title"), action=self.clear_btn, icon_key="music"))

        # ── controls row ──
        ctl = QHBoxLayout()
        ctl.setSpacing(10)
        self.add_btn = ui_kit.make_button(
            t("music.add_files"), icon_key="add", on_click=self._add_files, min_h=36)
        ctl.addWidget(self.add_btn)
        self.folder_btn = ui_kit.make_button(
            t("music.add_folder"), icon_key="folder", on_click=self._add_folder, min_h=36)
        ctl.addWidget(self.folder_btn)
        ctl.addStretch(1)
        ctl.addWidget(QLabel(t("music.mode")))
        self.mode_combo = QComboBox()
        self.mode_combo.setMinimumHeight(32)
        self.mode_combo.setMinimumWidth(110)
        for mode, key in [("loop", "music.mode_loop"), ("sequential", "music.mode_sequential"), ("shuffle", "music.mode_shuffle")]:
            self.mode_combo.addItem(t(key), mode)
        # round-34 加固：bgm_mode 非法值（脏配置）时 .index() 会 ValueError
        try:
            _mode_idx = ["loop", "sequential", "shuffle"].index(
                self._cfg.get("bgm_mode", "loop"))
        except ValueError:
            _mode_idx = 0
        self.mode_combo.setCurrentIndex(max(0, _mode_idx))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        ctl.addWidget(self.mode_combo)
        root.addLayout(ctl)

        # ── playlist ──
        self.list = QListWidget()
        self.list.setMinimumHeight(220)
        self.list.itemDoubleClicked.connect(lambda it: self._play_row(self.list.row(it)))
        root.addWidget(self.list, stretch=1)

        # ── now playing + transport ──
        now = RoundedCard(radius=12)
        nl = QHBoxLayout(now)
        nl.setContentsMargins(18, 12, 18, 12)
        nl.setSpacing(14)
        self.now_lbl = QLabel(t("music.none"))
        self.now_lbl.setProperty("cls", "sub")
        nl.addWidget(self.now_lbl, stretch=1)
        self.prev_btn = QPushButton(icon("skip_prev"), "")
        self.prev_btn.setFixedSize(40, 40)
        self.prev_btn.setProperty("cls", "accent")
        self.prev_btn.setCursor(Qt.PointingHandCursor)
        self.prev_btn.setToolTip(t("music.prev"))
        self.prev_btn.clicked.connect(lambda: (self._player.prev(), self._sync_ui()))
        nl.addWidget(self.prev_btn)
        self.play_btn = QPushButton(icon("play"), "")
        self.play_btn.setFixedSize(44, 44)
        self.play_btn.setProperty("cls", "accent")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip(t("music.play"))
        self.play_btn.clicked.connect(self._toggle_play)
        nl.addWidget(self.play_btn)
        self.next_btn = QPushButton(icon("skip_next"), "")
        self.next_btn.setFixedSize(40, 40)
        self.next_btn.setProperty("cls", "accent")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setToolTip(t("music.next"))
        self.next_btn.clicked.connect(lambda: (self._player.next(), self._sync_ui()))
        nl.addWidget(self.next_btn)
        nl.addSpacing(8)
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(float(self._cfg.get("bgm_vol", 0.4)) * 100))
        self.vol_slider.setMinimumWidth(120)
        self.vol_slider.setMaximumWidth(200)
        self.vol_slider.valueChanged.connect(self._on_vol)
        nl.addWidget(self.vol_slider, stretch=1)
        root.addWidget(now)

        self._rebuild_list()
        self._sync_ui()

    # ---------- playlist ----------
    def _rebuild_list(self):
        self.list.clear()
        for f in self._tracks:
            item = QListWidgetItem(os.path.basename(f))
            item.setToolTip(f)
            self.list.addItem(item)

    def _add_files(self):
        files = pick_files(self, t("music.add_title"), "", t("music.filter"), multi=True)
        if not files:
            return
        for f in files:
            if f not in self._tracks:
                self._tracks.append(f)
        self._rebuild_list()
        self._save_cfg()

    def _add_folder(self):
        d = pick_folder(self, t("music.add_folder_title"))
        if not d:
            return
        added = 0
        for root, _dirs, fnames in os.walk(d):
            for fn in fnames:
                if fn.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a")):
                    p = os.path.join(root, fn)
                    if p not in self._tracks:
                        self._tracks.append(p)
                        added += 1
        if added:
            info(self, t("music.added_title"), t("music.added_msg", n=added))
        self._rebuild_list()
        self._save_cfg()

    def _clear(self):
        self._tracks.clear()
        self._rebuild_list()
        self._player.stop()
        self._sync_ui()
        self._save_cfg()

    def _save_cfg(self):
        cfg = load_config()
        cfg["bgm_files"] = self._tracks
        cfg["bgm_file"] = self._tracks[0] if self._tracks else ""
        cfg["bgm_mode"] = self.mode_combo.currentData()
        cfg["bgm_vol"] = self.vol_slider.value() / 100.0
        save_config(cfg)
        if len(self._tracks) >= 5:
            from .achievements import achievements as _ach
            _ach.unlock("playlist_5")

    # ---------- transport ----------
    def _play_row(self, row: int):
        if 0 <= row < len(self._tracks):
            self._player.mode = self.mode_combo.currentData()
            # round-52 修复：MusicPlayer.files 是独立于页面 _tracks 的内部列表，
            # 必须先 set_playlist 同步，否则 play_index 因 files 为空而静默失败
            # （点击播放无效、index 恒为 -1、无任何声音）。
            self._player.set_playlist(self._tracks)
            self._player.play_index(row, self.vol_slider.value() / 100.0)
            self._sync_ui()

    def _toggle_play(self):
        if self._player.is_playing():
            self._player.pause()
        else:
            if self._player.current_index() < 0 and self._tracks:
                self._play_row(0)
            else:
                self._player.resume()
        self._sync_ui()

    def _on_mode_changed(self, _i):
        self._player.mode = self.mode_combo.currentData()
        self._save_cfg()

    def _on_vol(self, v):
        self._player.set_volume(v / 100.0)

    def _sync_ui(self):
        idx = self._player.current_index()
        if 0 <= idx < len(self._tracks):
            self.now_lbl.setText(f"{os.path.basename(self._tracks[idx])}  ·  {self._tracks[idx]}")
        else:
            self.now_lbl.setText(t("music.none"))
        self.list.setCurrentRow(idx if 0 <= idx < len(self._tracks) else -1)
        # round-66：播放/暂停按钮图标随状态切换（此前固定显示播放图标，
        # 点击后无任何视觉反馈）。
        self.play_btn.setIcon(icon("pause" if self._player.is_playing() else "play"))

    def retranslate_ui(self):
        self._rebuild_list()
        self._sync_ui()
