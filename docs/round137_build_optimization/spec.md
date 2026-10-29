# round-137 — 启动器打包体积优化（spec）

日期：2026-10-28
状态：已批准（用户授权「遗留你可以自行决定怎么搞」）

---

## 1. 需求

用户提问：

> 遗留你可以自行决定怎么搞。现在启动器打包后多大？需不需要搞优化？

拆成两件事：

1. **报体积** —— 回答「现在启动器打包后多大」。
2. **做优化** —— 判断需不需要，并动手做。

---

## 2. 现状事实（实测）

### 2.1 体积基线

| 路径 | 大小 | 文件数 |
|---|---|---|
| `dist_beta/`（含 `_work` 临时目录） | 602.2 MB | 7,008 |
| **`dist_beta/AC_Launcher/`（唯一交付目录）** | **580.4 MB** | **6,991** |
| `_internal/PySide6/` | 551.5 MB | — |
| `_internal/assets/` | 2.8 MB | — |
| `_internal/shiboken6/` | 1.1 MB | — |
| `_internal/minecraft_launcher_lib/` | 0.4 MB | — |

**结论：交付目录 580.4 MB，其中 PySide6 占 551.5 MB（95%）。**

### 2.2 PySide6 内部大头

| 项 | 大小 | 性质 |
|---|---|---|
| `Qt6WebEngineCore.dll` | 195.3 MB | Chromium 内核 —— **JS 扩展宿主必需** |
| `resources/` | 101.4 MB | 其中 **77.2 MB 是 `*.debug.pak` / `*.debug.bin`**（调试构建才加载） |
| `translations/` | 52.9 MB / 238 文件 | Qt 自带 .qm —— 本项目 **零 `QTranslator` 使用**（全库 grep 无命中） |
| `qml/` | 23.7 MB / 2,510 文件 | QML 运行时 —— 无 QtQuick/QtQml 使用，但被 WebEngine 的 hook 连带收集 |
| `opengl32sw.dll` | 19.7 MB | Mesa 软件 OpenGL 回退 —— 全库无任何 OpenGL API 使用 |
| `avcodec/avformat/avutil` | 17.9 MB | ffmpeg —— `plugins/multimedia/ffmpegmediaplugin.dll` 依赖（ogg/flac 解码要留） |
| `Qt6Quick / Qt6Qml / Qt6Quick3D* / Qt6Pdf / Qt6Charts / Qt6Graphs / Qt6DataVisualization / Qt6ShaderTools / Qt63DRender / Qt6Location …` | 49.0 MB | 全部**不在**静态导入图里（PE 导入扫描判定 unreachable） |

### 2.3 死重是怎么进来的（机制）

`PyInstaller/hooks/hook-PySide6.py` 只做两件事（加 `hiddenimports` + `collect_extra_binaries()`）；
真正的膨胀在 **60 个 per-module hook** 里，每个都跑 `add_qt6_dependencies()` →
`QtLibraryInfo.collect_module()` → 递归走 PE 导入图 → 命中一个 Qt 模块就
`hiddenimports.add("PySide6.<Mod>")` → 触发下一个 hook。

链路（实测自 `Analysis-00.toc`）：

```
PySide6.QtWebEngineWidgets
  └─ hook-PySide6.QtWebEngineCore
       ├─ collect_qtwebengine_files()  → resources/ (101.4 MB) + qtwebengine_*.qm
       └─ collect_module() 走 PE 导入：
            Qt6WebEngineCore.dll → Qt6Qml.dll → Qt6Quick.dll
                                 → Qt6WebChannel.dll → Qt6Positioning.dll
              每个都命中 shared_libraries 表 → 加 hiddenimport → 再触发 hook
            → hook-PySide6.QtQml → collect_qtqml_files() → qml/ (23.7 MB)
            → hook-PySide6.QtQuick3D / QtPdf / QtCharts / QtGraphs … → 各自 DLL
```

`spec` 里 `excludes=[]`（空）→ 一个都没挡。

### 2.4 实际用到哪些 Qt 模块（全库 import 扫描）

| 模块 | import 次数 |
|---|---|
| QtCore | 65 |
| QtWidgets | 64 |
| QtGui | 43 |
| QtMultimedia | 3 |
| QtSvg | 2 |
| QtNetwork | 2 |
| QtMultimediaWidgets | 1 |
| QtWebEngineWidgets | 1（`plugin_host.py`，try/except 包裹） |
| QtWebEngineCore | 1（同上） |

**完全未用**：QtQuick / QtQml / Qt3D* / QtPdf / QtCharts / QtDataVisualization /
QtGraphs / QtDesigner / QtQuickControls2 / QtLocation / QtPositioning /
QtWebChannel / QtWebSockets / QtHttpServer / QtSerialPort / QtSensors /
QtBluetooth / QtNfc / QtHelp / QtUiTools / QtTest / QtQuickTest / QtOpenGLWidgets /
QtQuickWidgets / QtSpatialAudio / QtStateMachine / QtScxml / QtRemoteObjects /
QtVirtualKeyboard。

### 2.5 降级路径已经存在

`src/plugin_host.py:38-49` 用 try/except 包住 QtWebEngine import，失败 →
`webengine_available()` 返回 False → `src/modules_page.py:374` 显示
「扩展宿主不可用」并给出具体原因。**去掉 WebEngine 不会让启动器崩。**

### 2.6 音频依赖

`src/core/sound.py` 用 `QMediaPlayer`，支持 mp3/wav/ogg/flac/m4a/aac/wma；
`assets/sounds/launch_default.wav` 是默认音效。
`plugins/multimedia/ffmpegmediaplugin.dll` → `avformat/avcodec/avutil`（17.9 MB）
**必须保留**（ogg/flac 靠它；Windows Media Foundation 插件解不了）。

---

## 3. 设计决策

分两条腿，**互不牺牲功能**：

### 3.1 腿 A —— 默认构建瘦身（零功能损失）

| 手段 | 省 |
|---|---|
| `spec.excludes` 挡掉未使用的 PySide6 模块（连带其 hook 与 DLL 一起不收） | ~49 MB + qml/ 23.7 MB |
| 构建后裁剪 `*.debug.pak` / `*.debug.bin`（调试构建才用） | 77.2 MB |
| 构建后 `translations/` 只留 zh_CN / en_US | 37.1 MB |

→ 目标 **580.4 MB → 约 330 MB**（实测以构建结果为准）。

### 3.2 腿 B —— `--lite` 构建（去掉 Chromium，扩展开宿主不可用）

额外排除 `PySide6.QtWebEngineCore` / `PySide6.QtWebEngineWidgets`，
再连带裁掉 `resources/`、`qml/`、Qt6Quick/Qt6Qml/Quick3D/QuickControls2 等链。

→ 目标 **约 100–130 MB**。

**默认构建保持功能完整**（不悄悄削功能）；`--lite` 作为显式可选产物。

### 3.3 明确不做

- ❌ 不用 `upx=True` —— 已经被 `AC_PiTest_noupx.spec` 名字排除，且 UPX 压缩
  Chromium 会拖慢启动、有 AV 误报风险。
- ❌ 不删 `plugins/` 整个目录 —— 里面的插件是**运行时按名加载**的，PE 静态
  导入图看不见（`qwindows.dll` / `qjpeg.dll` / `ffmpegmediaplugin.dll` 都在
  unreachable 名单里但必须留）。
- ❌ 不删 `avcodec/avformat/avutil` —— ogg/flac 解码要。
- ❌ 不删 `icudtl.dat` / `qtwebengine_resources.pak` —— Chromium 运行时加载。
- ❌ 不动 `libssl/libcrypto` —— `_ssl.pyd` 延迟加载找不到就崩。
- ❌ 不动 `minecraft_launcher_lib` 数据文件。

---

## 4. 验收标准

| # | 标准 |
|---|---|
| A1 | 默认构建产物 ≤ 360 MB |
| A2 | `AC_Launcher.exe` 能正常启动，主界面渲染出来 |
| A3 | 设置页能打开，标题栏品牌自定义仍在（round-136 功能不回退） |
| A4 | `src/modules_page.py` 的扩展区正常显示（可用或「不可用」提示都算过） |
| A5 | 音效能播（`launch_default.wav`） |
| A6 | `--lite` 产物 ≤ 140 MB 且能启动，扩展区显示「扩展宿主不可用」 |
| A7 | `python regress.py` 12/12 通过（本次改动不碰业务逻辑） |

---

## 5. 改动文件清单

| 文件 | 动作 |
|---|---|
| `AC_PiTest_noupx.spec` | 加 `excludes`（未用 Qt 模块）+ 读环境变量切 lite |
| `build.py` | 加 `--lite` 参数、构建后裁剪（debug 资源 / 翻译）、打印体积对比 |
| `src/splash_window.py` | round-136 遗留：启动页蒙版按背景图平均亮度自适应 |
| `CHANGELOG.md` | round-137 条目 |
| `<本地工作区>\2026-10-28_AC启动器_round137_打包体积优化.md` | 任务记忆 |

---

## 6. 批准

用户原话：「遗留你可以自行决定怎么搞。现在启动器打包后多大？需不需要搞优化？」
→ 授权自行决定实现方式。直接进入实施。
