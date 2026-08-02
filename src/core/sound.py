"""Audio for AC Launcher: one-shot chimes, UI sound effects and looping BGM.

Everything is user-replaceable. Players can point any of these at their own
audio file (mp3 / wav / ogg / flac / m4a — whatever the platform's media
backend supports):

  · launch chime  — played when the launcher opens and/or the game starts
  · background music — loops the whole time the launcher is open
  · UI sound effects — click / hover / success / error

A bundled default chime ships in assets/sounds/launch_default.wav; every other
channel is silent until the user supplies a file.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl, QObject
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from ..paths import get_resource_path

DEFAULT_SOUND = get_resource_path("assets/sounds/launch_default.wav")

# trigger values understood by callers
TRIGGER_APP = "app"
TRIGGER_GAME = "game"
TRIGGER_BOTH = "both"
TRIGGER_OFF = "off"

# UI effect keys → config field holding the user's custom file
SFX_KEYS = ("click", "hover", "success", "error")

# File types we advertise in the settings file picker.
AUDIO_FILTER = (
    "音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma);;所有文件 (*.*)"
)


class SoundPlayer(QObject):
    """Thin wrapper around QMediaPlayer that plays a one-shot chime."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(0.8)
        # keep a ref so the player is not GC'd mid-play
        self._last_source: str | None = None

    def play(self, custom_path: str | None = None, volume: float = 0.8) -> bool:
        """Play the custom file if given & exists, else the bundled default.
        Returns True if something was actually played.
        """
        self._audio.setVolume(max(0.0, min(1.0, volume)))
        path = custom_path or DEFAULT_SOUND
        if not path or not os.path.exists(path):
            return False
        self._last_source = path
        self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self._player.play()
        return True

    def stop(self) -> None:
        self._player.stop()


class MusicPlayer(QObject):
    """Launcher background music — multi-file playlist with play modes.

    Supports three modes (mirrors settings.bgm_mode):
      · "loop"        — repeat the current track forever
      · "sequential"  — play through the list, stop at the end
      · "shuffle"     — pick a random next track each time
    Tracks auto-advance when the current one finishes (mediaStatusChanged).
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._path: str = ""
        self.files: list[str] = []
        self.mode: str = "loop"
        self._idx: int = -1
        self._shuffle_history: list[int] = []
        self._player.mediaStatusChanged.connect(self._on_status)

    def set_playlist(self, files: list[str]) -> None:
        """Replace the playlist. Keeps playback position if current file
        still exists in the new list."""
        cur = self._path
        self.files = [f for f in files if f and os.path.exists(f)]
        self._idx = -1
        if cur:
            for i, f in enumerate(self.files):
                if os.path.normpath(f) == os.path.normpath(cur):
                    self._idx = i
                    break

    def play(self, path: str, volume: float = 0.4) -> bool:
        if not path or not os.path.exists(path):
            self.stop()
            return False
        self._audio.setVolume(max(0.0, min(1.0, volume)))
        if path != self._path:
            self._path = path
            self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        self._player.play()
        return True

    def play_index(self, index: int, volume: float = 0.4) -> bool:
        if 0 <= index < len(self.files):
            self._idx = index
            return self.play(self.files[index], volume)
        return False

    def _on_status(self, status):
        # Auto-advance when a track ends (EndOfMedia fires for single-shot;
        # with Infinite loops it never fires, so sequential/shuffle use a
        # plain loop and we advance manually).
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.mode == "loop" and self._path:
                self._player.play()  # restart the same file
            else:
                self._next()

    def _next(self) -> bool:
        if not self.files:
            return False
        if self.mode == "shuffle":
            import random as _r
            candidates = [i for i in range(len(self.files)) if i != self._idx]
            if candidates:
                self._idx = _r.choice(candidates)
            return self.play(self.files[self._idx])
        # sequential: advance or wrap at end
        if len(self.files) == 1:
            return self.play(self.files[0])
        self._idx = (self._idx + 1) % len(self.files)
        return self.play(self.files[self._idx])

    def next(self) -> bool:
        """User-triggered skip (always moves, wraps around)."""
        if not self.files:
            return False
        self._idx = (self._idx + 1) % len(self.files)
        return self.play(self.files[self._idx])

    def prev(self) -> bool:
        if not self.files:
            return False
        self._idx = (self._idx - 1) % len(self.files)
        return self.play(self.files[self._idx])

    def set_volume(self, volume: float) -> None:
        self._audio.setVolume(max(0.0, min(1.0, volume)))

    def pause(self) -> None:
        self._player.pause()

    def resume(self) -> None:
        self._player.play()

    def stop(self) -> None:
        self._player.stop()
        self._path = ""

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def current_index(self) -> int:
        return self._idx


_player: SoundPlayer | None = None
_music: MusicPlayer | None = None
_sfx_pool: dict[str, SoundPlayer] = {}


def _instance() -> SoundPlayer:
    global _player
    if _player is None:
        _player = SoundPlayer()
    return _player


def music() -> MusicPlayer:
    global _music
    if _music is None:
        _music = MusicPlayer()
    return _music


def play_launch_sound(trigger: str, cfg: dict) -> None:
    """Entry point called from the UI.

    ``trigger`` is what just happened ("app" | "game"). ``cfg`` is the settings
    dict. Honors:
      - cfg["launch_sound"]          bool  master switch
      - cfg["launch_sound_trigger"]  "app"|"game"|"both"|"off"
      - cfg["launch_sound_file"]     custom audio path or ""
      - cfg["launch_sound_vol"]      float 0..1
    """
    if not cfg.get("launch_sound", True):
        return
    want = cfg.get("launch_sound_trigger", TRIGGER_GAME)
    if want == TRIGGER_OFF:
        return
    if want == TRIGGER_APP and trigger != TRIGGER_APP:
        return
    if want == TRIGGER_GAME and trigger != TRIGGER_GAME:
        return
    custom = cfg.get("launch_sound_file", "") or None
    vol = float(cfg.get("launch_sound_vol", 0.8))
    _instance().play(custom, vol)


# ---------------------------------------------------------------- background
def start_bgm(cfg: dict) -> bool:
    """Start (or restart) background music from settings.

    cfg keys:
      - cfg["bgm_enabled"]  bool
      - cfg["bgm_files"]    list of music paths (multi-file)
      - cfg["bgm_file"]     single-file fallback (legacy)
      - cfg["bgm_mode"]     "loop" | "sequential" | "shuffle"
      - cfg["bgm_vol"]      float 0..1
    """
    if not cfg.get("bgm_enabled", False):
        music().stop()
        return False
    files = cfg.get("bgm_files") or []
    if not files and cfg.get("bgm_file"):
        files = [cfg["bgm_file"]]
    files = [f for f in files if f]
    if not files:
        music().stop()
        return False
    mode = cfg.get("bgm_mode", "loop")
    m = music()
    m.mode = mode if mode in ("loop", "sequential", "shuffle") else "loop"
    m.set_playlist(files)
    cur = m.current_index()
    return m.play_index(cur if cur >= 0 else 0, float(cfg.get("bgm_vol", 0.4)))


def stop_bgm() -> None:
    music().stop()


def apply_bgm(cfg: dict) -> None:
    """Re-sync BGM with settings (called after the settings dialog saves)."""
    if not cfg.get("bgm_enabled", False):
        music().stop()
        return
    start_bgm(cfg)


# --------------------------------------------------------------------- sfx
def play_sfx(key: str, cfg: dict) -> None:
    """Play a UI sound effect (click / hover / success / error).

    Silent unless the user assigned a file to that key, so the launcher stays
    quiet by default.
    """
    if not cfg.get("sfx_enabled", False):
        return
    path = cfg.get(f"sfx_{key}", "")
    if not path or not os.path.exists(path):
        return
    p = _sfx_pool.get(key)
    if p is None:
        p = _sfx_pool[key] = SoundPlayer()
    p.play(path, float(cfg.get("sfx_vol", 0.6)))


def preview(path: str, volume: float = 0.8) -> bool:
    """Play an arbitrary file once (settings 'try it' buttons)."""
    return _instance().play(path or None, volume)


def stop_preview() -> None:
    _instance().stop()


def ensure_default_exists() -> str:
    """Return the default sound path (for settings preview / copy)."""
    return DEFAULT_SOUND
