# round-139 — PCL 式组件化下载（扩展运行时按需安装）spec

> 决策来源（2026-10-28，用户拍板）：
> 1. **立项做组件化下载** —— 学 PCL「需要的组件再下载」，默认包不再背 Chromium；
> 2. **不开老系统特殊版** —— 现代 MC（1.17+ 要 Java 16、1.20.5+ 要 Java 21）
>    本体就不支持 Win7，官方启动器也是 Win10+；release notes 写明
>    「系统要求 Windows 10 1809+」，不维护 Qt5/Python3.8 老支线。

## 1. 背景与动机

round-137 后体积拆解：默认 349.0 MB 里 **Chromium 栈 210.8 MB（61%）** 只为
扩展宿主（HTML/JS 插件）服务；同类完整启动器 CurseForge ~120 / XMCL ~136 /
PCL2 15.2，我们 349MB 是独一档的胖。框架本体（Qt 49.6 + 绑定 14.2 +
Python 15.8 ≈ 80–90MB）是 Python 栈地板，**唯一的大杠杆就是把 Chromium 变成
「按需组件」**：

| 形态 | 体积 | 扩展宿主 |
| --- | --- | --- |
| 现默认（完整版） | 349.0 MB | ✅ 内置 |
| 现 lite | 135.4 MB | ❌ 永久降级 |
| **本 round 主包（B1 实测）** | **117.9 MB** | ⏳ 首次使用时下载组件（zip **96.9MB**）后 ✅ |

> B1 补充发现：全量 PE 扫描揪出「幽灵链」——虚拟键盘输入法插件拖
> Qt6VirtualKeyboard→Qt6Quick→Qt6Qml*、qpdf 图片插件拖 Qt6Pdf（封闭集合
> ≈17MB，与 Chromium 无关但只被完整包真正需要）。已定点清出主包，diff 法
> 自动把它们收进组件包（31 文件），装回组件即恢复完整能力。

## 2. 架构设计

### 2.1 构建侧：产出组件包

- 新增 `build.py --components`（或 `build_components.py`）：
  - **文件清单用实测 diff 法生成**——对「完整构建」与「lite 构建」的
    `dist_beta/AC_Launcher` 做文件级 diff，差集即 Chromium 栈全集
    （含被 Qt6WebEngineCore 静态导入拖进来的 Qt6Quick/Qt6Qml/Qt6Pdf/
    QtPrintSupport/QtWebChannel/Qt6Positioning 的 DLL+pyd，PE 动态加载
    靠静态分析容易漏，diff 法最稳）；再补 runtime 必需的
    `QtWebEngineProcess.exe`、`resources/`、`qtwebengine_locales/`、
    必要时 `qml/`（以「装上后示例插件能跑」为最终判据，不猜）。
  - 打 zip：`ac_webengine_runtime_<版本>.zip` + 同名 `.sha256` +
    `manifest.json`（启动器版本、组件版本、文件清单、解压总大小）。
  - 组件包进 release 资产，不进主包。

### 2.2 运行侧：下载 / 安装 / 卸载

新增 `src/feature_pack.py`（暂名，接入 `src/core` 体系）：

- `state()` → `absent | downloading | installed`（落盘
  `<data>/component_state.json`：组件版本 + sha256 + 安装时间）
- `ensure_downloaded()`：复用 `core/mirror` 的多源 + 断点续传下载器，
  进度信号（复用现有下载进度 UI 模式）
- `install()`：解压到 `<data>/_tmp_pack/` → 逐文件校验 sha256 →
  **原子移动**到 `_internal/PySide6/`（同盘 rename，失败回滚删临时目录）→
  写 state → 提示重启生效
- `uninstall()`：按 manifest 清单删除（只删组件文件，绝不碰插件目录）→ 清 state
- 版本绑定：state 里的组件版本 ≠ 当前启动器版本 → 视为未安装（强制重下），
  防止启动器升级后组件错位
- `plugin_host.webengine_available()` 仍只管 import；组件缺失时由
  `modules_page` 扩展区把「扩展宿主不可用」升级为
  **「安装扩展组件（~110MB）」按钮 + 进度条 + 重启提示**
- 设置页扩展区加组件状态行：未安装 / 下载中 x% / 已安装 v1.0 / 卸载

### 2.3 发布形态

release 挂三资产（notes 写清）：
1. **主包 `AC_Launcher_<版本>.zip`**（≈135MB，默认推荐）——开扩展区时按需下组件；
2. **组件包 `ac_webengine_runtime_<版本>.zip`**（~110MB）——也给手动党直接丢进去用；
3. ~~完整包~~ **不再单独出**（diff 组合即得，避免三份产物漂移）——需要离线全家桶的
   用户 = 主包 + 组件包手动合并，等价完整版。

opengl32sw（19.7MB）是否顺带砍掉：**待定**（单独开关讨论，不与本 round 绑定）。

## 3. 验收

- B1 主包体积 ≈ 135MB（不含任何 `Qt6WebEngine*`/Quick/Qml/Pdf 跟班件）
- B2 全新主包 → 扩展区点安装 → 下载→校验→落位→重启 → **示例插件真实跑起来**
  （目视截图，不接受「装完了」但插件黑屏）
- B3 中途断网/杀进程重试可续传；sha256 不过 → 报错重下，不留半套文件
- B4 卸载组件 → 回到「安装组件」入口状态，插件数据（`<data>/extensions/`）不被删
- B5 版本绑定：换启动器版本后组件判为需更新
- B6 `regress.py` 12/12；断网冷启动主包不报错（缺组件不影响任何其他功能）

## 4. 风险

- R1 清单漏件（PE 动态加载）→ diff 法 + B2「示例插件实跑」作最终裁决，漏件
  补进清单即可，不返工架构
- R2 解压落位被杀软盯上 → 全程 Python zipfile，不 drop exe；临时目录同卷原子 move
- R3 用户下载失败误判「功能坏了」→ 扩展区文案必须是「组件未安装」而非「不可用」，
  断网时给出离线提示
