"""Minecraft panorama (cubemap) backdrop for the home page.

Minecraft's title screen is not a flat picture: it renders a six-face
cubemap (``minecraft/textures/gui/title/background/panorama_0..5.png``)
from *inside* a big cube, which is why it reads as a real cave instead of
a wallpaper.  This module renders the very same cubemap with QPainter so
the launcher home page shows the genuine artwork of the selected version
-- and, when a modpack replaced the panorama, the modpack's own file.

Pure Qt: no numpy, no OpenGL.

Rendering
---------
The camera sits in the middle of the cube, so a face is a *plane* seen
from a point: the map from the face's texture coordinates to the screen
is a single homography, which we build analytically.  Two regions have
to be excluded:

* everything behind the camera (its homography image is mirrored and
  would paint over the neighbouring walls) -- cut with the near plane;
* everything outside the viewport -- cut with the four screen bounds.

Both cuts are linear in the face's (u, v) coordinates, so the visible
part of a face is a convex polygon that can be clipped in texture space
and then used as the painter's clip region.

Layout of the six faces (verified against the real asset by comparing the
luminance profile of every face border):

    0,1,2,3  the four side walls, cyclic 0 -> 1 -> 2 -> 3 -> 0
    4         the ceiling
    5         the floor
"""
from __future__ import annotations

import atexit
import hashlib
import json
import math
import os
import re
import shutil
import zipfile
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, QThread, Signal
from PySide6.QtGui import (
    QImage, QPainter, QPainterPath, QPolygonF, QTransform, QColor,
)

# Resource names of the six faces, most recent layout first.
FACE_TEMPLATES = (
    "minecraft/textures/gui/title/background/panorama_{}.png",
    "minecraft/textures/gui/title/background/panorama/panorama_{}.png",
    "minecraft/textures/gui/panorama/panorama{}.png",
    "minecraft/textures/gui/panorama/panorama_{}.png",
)

# Same paths inside a resource-pack zip ("assets/" + resource name).
ZIP_TEMPLATES = tuple("assets/" + t for t in FACE_TEMPLATES)


# ─────────────────────────────────────────────────────────────── geometry
def face_point(face: int, u: float, v: float) -> tuple[float, float, float]:
    """Texture coords (0..1, origin top-left) -> a point on the unit cube."""
    if face == 0:
        return (2.0 * u - 1.0, 1.0 - 2.0 * v, -1.0)
    if face == 1:
        return (1.0, 1.0 - 2.0 * v, 2.0 * u - 1.0)
    if face == 2:
        return (1.0 - 2.0 * u, 1.0 - 2.0 * v, 1.0)
    if face == 3:
        return (-1.0, 1.0 - 2.0 * v, 1.0 - 2.0 * u)
    if face == 4:
        return (2.0 * u - 1.0, 1.0, 1.0 - 2.0 * v)
    return (2.0 * u - 1.0, -1.0, 2.0 * v - 1.0)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


class _Camera:
    """Camera at the centre of the cube, looking at the walls."""

    def __init__(self, yaw: float, pitch: float) -> None:
        y = math.radians(yaw)
        p = math.radians(pitch)
        cy, sy = math.cos(y), math.sin(y)
        cp, sp = math.cos(p), math.sin(p)
        self.fwd = (sy * cp, sp, -cy * cp)
        self.right = (cy, 0.0, sy)
        self.up = (-sy * sp, cp, cy * sp)


def _clip_halfplane(poly, a: float, b: float, c: float):
    """Sutherland-Hodgman: keep the part where ``a*u + b*v + c >= 0``."""
    if not poly:
        return []
    out = []
    n = len(poly)
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        fp = a * p[0] + b * p[1] + c
        fq = a * q[0] + b * q[1] + c
        if fp >= 0.0:
            out.append(p)
        if (fp >= 0.0) != (fq >= 0.0):
            t = fp / (fp - fq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


# ──────────────────────────────────────────────────────── asset discovery
def _asset_dirs(mc_dir: str) -> list[str]:
    """Directories that may hold the shared asset store of an instance.

    A standard instance keeps it in ``<mc_dir>/assets``; a version
    isolated instance keeps it one or two levels up, next to ``versions``.
    """
    out: list[str] = []
    d = os.path.abspath(mc_dir) if mc_dir else ""
    for _ in range(3):
        if not d:
            break
        cand = os.path.join(d, "assets")
        if cand not in out:
            out.append(cand)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return out


def _faces_from_index_text(text: str, objects_dir: str) -> list[str] | None:
    """Resolve the six panorama faces out of one asset index.

    The index of a modern version lists thousands of objects; a full
    ``json.load`` costs tens of milliseconds, while a single regex pass per
    template costs well under one.
    """
    for tmpl in FACE_TEMPLATES:
        prefix, suffix = tmpl.split("{}")
        pattern = re.compile(
            r'"' + re.escape(prefix) + r'(\d)' + re.escape(suffix)
            + r'"\s*:\s*\{([^{}]*)\}'
        )
        hashes: dict[int, str] = {}
        for m in pattern.finditer(text):
            h = re.search(r'"hash"\s*:\s*"([0-9a-fA-F]+)"', m.group(2))
            if h:
                hashes[int(m.group(1))] = h.group(1)
        if len(hashes) < 6:
            continue
        paths: list[str] = []
        for i in range(6):
            h = hashes[i]
            obj = os.path.join(objects_dir, h[:2], h)
            if not os.path.isfile(obj):
                paths = []
                break
            paths.append(obj)
        if paths:
            return paths
    return None


def _panorama_from_index(index_path: str, objects_dir: str) -> list[str] | None:
    """Resolve the six panorama faces through one asset index."""
    try:
        with open(index_path, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except OSError:
        return None
    return _faces_from_index_text(text, objects_dir)


def _version_json_paths(mc_dir: str, version: str) -> list[str]:
    """Every place a version's metadata json may live.

    * ``<mc>/versions/<v>/<v>.json`` -- standard layout
    * ``<mc>/versions/<v>.json``        -- some launchers flatten it
    * ``<mc>/<v>.json``                 -- version-isolated instance whose
      game directory *is* the version folder
    """
    out: list[str] = []
    roots = [os.path.abspath(mc_dir)] if mc_dir else []
    d = roots[0] if roots else ""
    for _ in range(2):  # the shared versions/ folder may sit one level up
        if not d:
            break
        for cand in (
            os.path.join(d, "versions", version, f"{version}.json"),
            os.path.join(d, "versions", f"{version}.json"),
            os.path.join(d, f"{version}.json"),
        ):
            if cand not in out:
                out.append(cand)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return out


def _asset_index_id(mc_dir: str, version: str) -> str:
    """The ``assetIndex.id`` a version points at ("32", "5", ...).

    Every version ships its own asset index, and the panorama art changed
    between versions -- picking the index of the *running* version is what
    makes the backdrop match the game.
    """
    if not version:
        return ""
    for path in _version_json_paths(mc_dir, version):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        idx = data.get("assetIndex")
        if isinstance(idx, dict):
            index_id = str(idx.get("id") or "")
            if index_id:
                return index_id
    return ""


def find_vanilla_faces(mc_dir: str, version: str = "") -> list[str] | None:
    """Locate the vanilla panorama faces of an instance.

    The instance's own version index wins; only when that index is missing
    (old launchers, half-copied instances) do we fall back to scanning
    every index on disk, newest first.
    """
    index_id = _asset_index_id(mc_dir, version)
    for assets in _asset_dirs(mc_dir):
        idx_dir = os.path.join(assets, "indexes")
        objects_dir = os.path.join(assets, "objects")
        if not os.path.isdir(idx_dir):
            continue
        if index_id:
            paths = _panorama_from_index(os.path.join(idx_dir, f"{index_id}.json"),
                                         objects_dir)
            if paths:
                return paths
        try:
            names = sorted(n for n in os.listdir(idx_dir) if n.endswith(".json"))
        except OSError:
            continue
        # Newest index first: a version may have been upgraded in place.
        for name in reversed(names):
            paths = _panorama_from_index(os.path.join(idx_dir, name), objects_dir)
            if paths:
                return paths
    return None


def _enabled_resource_packs(*dirs: str) -> list[str]:
    """Pack ids the player actually enabled, in options.txt order.

    Minecraft applies the packs listed in ``resourcePacks`` in order, so
    the *last* entry wins -- that is the one whose panorama is on screen.
    """
    names: list[str] = []
    for d in dirs:
        if not d:
            continue
        opts = os.path.join(d, "options.txt")
        if not os.path.isfile(opts):
            continue
        try:
            with open(opts, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        m = re.search(r"^resourcePacks:\[(.*?)\]", text, re.M)
        if not m:
            continue
        for nm in re.findall(r'"([^"]*)"', m.group(1)):
            if nm and nm not in names:
                names.append(nm)
    return names


def _pack_dirs(*dirs: str) -> list[str]:
    out: list[str] = []
    for d in dirs:
        if not d:
            continue
        for sub in ("resourcepacks", "packs"):
            p = os.path.join(d, sub)
            if p not in out:
                out.append(p)
    return out


def _extract_pack_faces(zip_path: str, cache_root: str) -> list[str] | None:
    """Extract the panorama of one resource pack zip into the cache."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            entries = set(zf.namelist())
            chosen: list[str] | None = None
            for tmpl in ZIP_TEMPLATES:
                cand = [tmpl.format(i) for i in range(6)]
                if all(e in entries for e in cand):
                    chosen = cand
                    break
            if not chosen:
                return None
            try:
                stamp = os.path.getmtime(zip_path)
            except OSError:
                stamp = 0.0
            key = hashlib.sha1(f"{zip_path}|{stamp}".encode()).hexdigest()[:16]
            out_dir = os.path.join(cache_root, key)
            paths: list[str] = []
            for i, entry in enumerate(chosen):
                dst = os.path.join(out_dir, f"panorama_{i}.png")
                if not os.path.isfile(dst):
                    os.makedirs(out_dir, exist_ok=True)
                    tmp = dst + ".part"
                    with zf.open(entry) as src, open(tmp, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.replace(tmp, dst)
                paths.append(dst)
            return paths
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return None


def _override_faces(mc_dir: str) -> list[str] | None:
    """Panorama shipped as loose files by a modpack (``overrides/``).

    A modpack's ``overrides/`` folder mirrors the *game* directory, and
    resource-pack content lives under ``assets/`` in it -- so the file is
    ``overrides/assets/minecraft/textures/gui/title/background/panorama_N.png``.
    Both that form and the bare ``overrides/minecraft/...`` form are
    accepted, since modpacks differ in how they were built.
    """
    for base in _asset_dirs(mc_dir):
        root = os.path.dirname(base)  # .../<mc_root>
        for ov in (os.path.join(root, "overrides"),
                   os.path.join(root, "overrides", "assets")):
            for tmpl in FACE_TEMPLATES:
                cand = [os.path.join(ov, *tmpl.format(i).split("/")) for i in range(6)]
                if all(os.path.isfile(p) for p in cand):
                    return cand
    return None


def locate_faces(mc_dir: str, game_dir: str = "",
                 version: str = "") -> tuple[list[str], str]:
    """Find the panorama that the game would actually show.

    Priority: an enabled resource pack that ships its own panorama, then
    the modpack ``overrides`` folder, then the vanilla asset store.
    ``version`` is the instance's game version, used to pick the right
    asset index (every version has its own panorama art).
    Returns ``([], "")`` when nothing is found so the caller can fall back
    to the procedural wallpaper.
    """
    game_dir = game_dir or mc_dir

    enabled = _enabled_resource_packs(game_dir, mc_dir)
    dirs = _pack_dirs(game_dir, mc_dir)
    # Highest priority first: Minecraft lets the last listed pack win.
    for name in reversed(enabled):
        for d in dirs:
            faces = _extract_pack_faces(os.path.join(d, name + ".zip"),
                                         _cache_root())
            if faces:
                return faces, f"resourcepack:{name}"
    # A pack on disk that the player did not enable is not on screen.
    faces = _override_faces(mc_dir)
    if faces:
        return faces, "overrides"
    faces = find_vanilla_faces(mc_dir, version)
    if faces:
        return faces, "vanilla"
    return [], ""


def _cache_root() -> str:
    try:
        from .paths import get_data_dir
        root = os.path.join(get_data_dir(), "cache", "panorama")
    except Exception:  # noqa: BLE001 - paths module unavailable
        root = os.path.join(os.path.expanduser("~"), ".ac_launcher", "panorama")
    os.makedirs(root, exist_ok=True)
    return root


# ──────────────────────────────────────────────────────────────── renderer
class PanoramaRenderer:
    """Draws a six-face panorama cubemap as a rotating 3D view.

    One ``drawImage`` per face: the texture-to-screen map of a planar
    face is a homography, so the whole face is drawn in a single call.
    """

    def __init__(self, faces: list[QImage], fov: float = 90.0) -> None:
        if len(faces) != 6:
            raise ValueError("panorama needs exactly six faces")
        self._faces = list(faces)
        self.fov = fov
        self.yaw = 0.0
        self.pitch = -6.0
        # round-146：面与面之间按浮点裁剪后偶有 1px 缝，缓冲填黑时这些缝就是
        # 表现为「黑色噪点/黑线」（且随每帧 yaw 抖动闪烁）。缓冲底色改为
        # 六面平均色——缝隙即使露出来也和画面同色，肉眼不可见。
        self.avg_color = self._mean_color(faces)

    @staticmethod
    def _mean_color(faces: list[QImage]) -> QColor:
        """Sparse mean color of the six faces (16×16 samples each — cheap)."""
        r = g = b = n = 0
        for img in faces:
            w, h = img.width(), img.height()
            if w < 2 or h < 2:
                continue
            for i in range(16):
                for j in range(16):
                    c = img.pixelColor(int(w * (i + 0.5) / 16), int(h * (j + 0.5) / 16))
                    r += c.red()
                    g += c.green()
                    b += c.blue()
                    n += 1
        if not n:
            return QColor(32, 34, 38)
        return QColor(r // n, g // n, b // n)

    # ---------------------------------------------------------------- draw
    def render(self, painter: QPainter, rect: QRectF, yaw: float | None = None,
               pitch: float | None = None) -> None:
        """Paint the cube into ``painter``, covering ``rect``."""
        w = rect.width()
        h = rect.height()
        if w < 2 or h < 2:
            return
        cam = _Camera(self.yaw if yaw is None else yaw,
                      self.pitch if pitch is None else pitch)
        tany = math.tan(math.radians(self.fov) * 0.5)
        tanx = tany * (w / h)
        cx = rect.x() + w * 0.5
        cy = rect.y() + h * 0.5
        kx = (w * 0.5) / tanx
        ky = (h * 0.5) / tany
        for face in range(6):
            self._draw_face(painter, face, cam, rect, cx, cy, kx, ky)

    def _draw_face(self, painter, face, cam, rect, cx, cy, kx, ky) -> None:
        # Face plane: P(u, v) = p00 + u * e1 + v * e2.
        p00 = face_point(face, 0.0, 0.0)
        e1 = _sub(face_point(face, 1.0, 0.0), p00)
        e2 = _sub(face_point(face, 0.0, 1.0), p00)

        # Camera space components are affine in (u, v).
        nx = (_dot(e1, cam.right), _dot(e2, cam.right), _dot(p00, cam.right))
        ny = (_dot(e1, cam.up), _dot(e2, cam.up), _dot(p00, cam.up))
        dz = (_dot(e1, cam.fwd), _dot(e2, cam.fwd), _dot(p00, cam.fwd))

        # Everything behind the camera must go: the homography mirrors it
        # onto the opposite half of the screen.
        poly = _clip_halfplane([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
                                dz[0], dz[1], dz[2] - 1e-3)
        if len(poly) < 3:
            return

        # Cut away everything that falls outside the viewport.
        left, right = rect.left(), rect.right()
        top, bottom = rect.top(), rect.bottom()
        poly = _clip_halfplane(poly, kx * nx[0] - (left - cx) * dz[0],
                               kx * nx[1] - (left - cx) * dz[1],
                               kx * nx[2] - (left - cx) * dz[2])
        poly = _clip_halfplane(poly, (right - cx) * dz[0] - kx * nx[0],
                               (right - cx) * dz[1] - kx * nx[1],
                               (right - cx) * dz[2] - kx * nx[2])
        poly = _clip_halfplane(poly, (cy - top) * dz[0] - ky * ny[0],
                               (cy - top) * dz[1] - ky * ny[1],
                               (cy - top) * dz[2] - ky * ny[2])
        poly = _clip_halfplane(poly, ky * ny[0] - (cy - bottom) * dz[0],
                               ky * ny[1] - (cy - bottom) * dz[1],
                               ky * ny[2] - (cy - bottom) * dz[2])
        if len(poly) < 3:
            return

        img = self._faces[face]
        iw = float(img.width())
        ih = float(img.height())

        # Homography: (u, v) -> screen.  x = (cx * den + kx * num_x) / den,
        # y = (cy * den - ky * num_y) / den.
        mx = (cx * dz[0] + kx * nx[0], cx * dz[1] + kx * nx[1], cx * dz[2] + kx * nx[2])
        my = (cy * dz[0] - ky * ny[0], cy * dz[1] - ky * ny[1], cy * dz[2] - ky * ny[2])
        t = QTransform(
            mx[0] / iw, my[0] / iw, dz[0] / iw,
            mx[1] / ih, my[1] / ih, dz[1] / ih,
            mx[2], my[2], dz[2],
        )

        # Clip region = the visible part of the face, in device space.
        dev = []
        for (u, v) in poly:
            den = dz[0] * u + dz[1] * v + dz[2]
            if abs(den) < 1e-9:
                den = 1e-9
            sx = (mx[0] * u + mx[1] * v + mx[2]) / den
            sy = (my[0] * u + my[1] * v + my[2]) / den
            dev.append(QPointF(sx, sy))
        path = QPainterPath()
        # round-146：相邻面共用一条边，浮点裁剪后常留 1px 缝；缓冲填黑时这些
        # 缝就是闪烁的「黑色噪点」。把可见多边形沿质心方向外扩 0.75px，让相邻
        # 面互相压住（重叠部分画的是同一处墙面，肉眼不可见）。
        if len(dev) >= 3:
            gx = sum(pt.x() for pt in dev) / len(dev)
            gy = sum(pt.y() for pt in dev) / len(dev)
            grown = []
            for pt in dev:
                dx, dy = pt.x() - gx, pt.y() - gy
                d = math.hypot(dx, dy) or 1.0
                grown.append(QPointF(pt.x() + dx / d * 0.75,
                                     pt.y() + dy / d * 0.75))
            dev = grown
        path.addPolygon(QPolygonF(dev))
        path.closeSubpath()

        painter.save()
        painter.resetTransform()
        painter.setClipPath(path)
        painter.setTransform(t)
        # round-146：1024px 贴图被重投影放大到屏幕，最近邻采样会给出块状/点状
        # 杂色（用户感知为「噪点」）；显式打开平滑采样。
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(QPointF(0, 0), img)
        painter.restore()


# ──────────────────────────────────────────────────────────── background job
# Every loader is kept in a module-level registry.  A QThread that is still
# running when its QObject is destroyed aborts the whole process
# (0xC0000409), so the loader must outlive the widget that started it and
# the app must be able to wait for it before it tears anything down.
_ACTIVE_LOADERS: list = []


def wait_for_loaders(timeout_ms: int = 5000) -> None:
    """Wait for every panorama loader that is still running.

    Called on ``QApplication.aboutToQuit`` and again from ``atexit`` so
    that neither a normal shutdown nor a bare interpreter teardown can
    destroy a running loader.
    """
    for loader in list(_ACTIVE_LOADERS):
        try:
            if loader.isRunning():
                loader.wait(timeout_ms)
        except Exception:  # noqa: BLE001 - already deleted C++ object
            pass


def _prune_loaders() -> None:
    """Drop loaders that have finished (their result was consumed)."""
    for loader in list(_ACTIVE_LOADERS):
        try:
            if not loader.isRunning():
                _ACTIVE_LOADERS.remove(loader)
        except Exception:  # noqa: BLE001
            _ACTIVE_LOADERS.remove(loader)


atexit.register(wait_for_loaders)


class PanoramaLoader(QThread):
    """Resolves the panorama of an instance off the UI thread.

    Scanning the asset store and decoding six 1024x1024 textures takes
    long enough to stall the first paint, so it runs here and the result
    is delivered through a queued signal.
    """

    ready = Signal(object, object, object)  # key, images, source

    def __init__(self, key: tuple, mc_dir: str, game_dir: str,
                 version: str = "", parent=None) -> None:
        super().__init__(parent)
        self._key = key
        self._mc = mc_dir
        self._game = game_dir
        self._version = version
        # The canonical Qt pattern: the thread object deletes itself once the
        # thread has stopped.  Until then the registry keeps it alive.
        self.finished.connect(self.deleteLater)
        _prune_loaders()
        _ACTIVE_LOADERS.append(self)

    def run(self) -> None:  # pragma: no cover - thread body
        # round-243：命中缓存直接返回，不再重新扫描 + 解码（切回看过的
        # 版本时这一步把 ~130ms 降到 ~0）。
        cached = cached_faces(self._key)
        if cached is not None:
            self.ready.emit(self._key, list(cached), "cache")
            return
        images: list[QImage] = []
        source = ""
        try:
            paths, source = locate_faces(self._mc, self._game, self._version)
            for p in paths:
                img = QImage(p)
                if img.isNull():
                    images = []
                    source = ""
                    break
                images.append(img)
        except Exception:  # noqa: BLE001 - a missing panorama is not fatal
            images = []
            source = ""
        if images:
            store_faces(self._key, images)
        self.ready.emit(self._key, images, source)


# ────────────────────────────────────────────── decoded-face LRU (round-243)
# 为什么缓存「解码后的 QImage」而不是文件路径：定位索引只要 1ms（实测），
# 真正贵的是解码 6 张 1024² PNG（实测 ~120ms）。切回刚看过的版本时重走一遍
# 完全是浪费，玩家感知到的就是"每次切版本都卡一下"。
# 代价是内存：每个版本 6×1024²×4B ≈ 24MB。所以只留最近 2 个版本
# （来回切两个实例的场景已覆盖），并设总字节上限兜住超大贴图的极端情况。
_FACE_CACHE: "OrderedDict[tuple, list[QImage]]" = OrderedDict()
_FACE_CACHE_ENTRIES = 2
_FACE_CACHE_BYTES = 56 * 1024 * 1024


def _face_bytes(images: list[QImage]) -> int:
    total = 0
    for img in images:
        try:
            total += img.sizeInBytes()
        except Exception:  # noqa: BLE001 - 老版本 Qt 没有 sizeInBytes
            total += img.width() * img.height() * 4
    return total


def cached_faces(key: tuple) -> list[QImage] | None:
    """取某实例已解码的全景六面（命中即移到队尾）。"""
    hit = _FACE_CACHE.get(key)
    if hit is None:
        return None
    _FACE_CACHE.move_to_end(key)
    return hit


def store_faces(key: tuple, images: list[QImage]) -> None:
    """缓存某实例的全景六面，超出条目/字节上限时淘汰最久未用的。"""
    if not images or len(images) != 6:
        return
    if _face_bytes(images) > _FACE_CACHE_BYTES // 2:
        return  # 单个版本就吃掉一半预算 → 不值得缓存
    _FACE_CACHE[key] = list(images)
    _FACE_CACHE.move_to_end(key)
    while len(_FACE_CACHE) > _FACE_CACHE_ENTRIES:
        _FACE_CACHE.popitem(last=False)
    while sum(_face_bytes(v) for v in _FACE_CACHE.values()) > _FACE_CACHE_BYTES:
        if len(_FACE_CACHE) <= 1:
            break
        _FACE_CACHE.popitem(last=False)


def clear_face_cache() -> None:
    """释放缓存的全景贴图（游戏启动降载时调用）。"""
    _FACE_CACHE.clear()
