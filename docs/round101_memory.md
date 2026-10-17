# round-101 记忆（2026-10-13）— 验收修复 3 连 + 发布前清理

玩家真机验收 round-100，连中 3 个阻断性问题；全部修复并验证，玩家结论「这次验收完美」。

## 修复

1. **导航全失效（最致命）**：`effects.fade_page_transition` 开头
   `if not EFFECTS_ENABLED: return`，而该开关由装饰配置 `effect_light_trail`
   （默认关）驱动；`MainWindow._switch_stack` 把它当作唯一切页口。
   → 默认配置下任何左侧菜单点击都不切页，且无异常。
   教训：**功能性流程不得被装饰性开关短路**。修法：关特效时函数内直接
   `setCurrentIndex`（瞬时切换），开特效才走淡入+上浮。
2. **清数据/全新首启静默闪退**：splash 关闭 → 延迟 1.2s 弹教程 → 教程结束
   才 show 主窗口；Qt 默认 `quitOnLastWindowClosed=True` 在 splash 关闭瞬间
   退出。修法：`app.setQuitOnLastWindowClosed(False)` + MainWindow.closeEvent
   实关闭分支显式 `QApplication.quit()`。改这条必须检查所有退出路径
   （托盘最小化 hide 不能误退）。
3. **教程无任务栏图标**：对话框 owner 是未 show 的主窗口 → Windows 不发
   任务栏按钮。修法：showEvent 首次显示时给 HWND 加 `WS_EX_APPWINDOW`
   （0x40000）。已验证 exstyle=0x40000 且截图见任务栏 AC 图标。

## 发布前清理（全部物理删除）

坏测试实例（扁平化布局，版本 json 散落 `.minecraft` 根 → notfound）、
data/ 全量（缓存/成就/索引/flag）、launcher_config.json、ac.lock、
38 个 `_*.py` 诊断脚本、_shots（103 图）、dist/（749MB）、__pycache__、
试验性 *.spec；.gitignore 补 `*.spec`。保留 venv/（gitignore 已排除）。
Git 仓库早已 init，remote=`git@github.com:Mists-Star/AC-Launcher.git`，
分支 main；git 不在 PATH，用 GitHub Desktop 自带 git：
`C:\Users\<user>\AppData\Local\GitHubDesktop\app-3.6.6\resources\app\git\cmd\git.exe`。

## 环境/工具

- 清 data 后首启是回归首启流程的唯一可靠方法；教程重弹需删
  `data/onboarding_done.flag`。
- pythonw 启动后窗口被其他应用遮挡时，用 user32 EnumWindows 找 HWND +
  SetForegroundWindow 提到前台；截图用 PowerShell CopyFromScreen。

---

## 下次待办（玩家 2026-10-13 验收时提出，明确「下次来做」）

1. **设置 → 外观页底部文字少量显示不全**（玩家截图确认）。
   排查方向：该页滚动区/对话框固定高度 + 底部控件高度不足（QCheckBox/QLabel
   行高、DPI 缩放、底部 margin）；优先检查 effects/外观分组最后几行是否被
   裁切，考虑增大对话框默认高度或让末行不贴边。
2. **内存占用进一步下探**（当前真机仅 ~80MB，玩家满意但想更小）。
   现状：QtWebEngine 已懒加载（plugin_host.webengine_available 函数内 import，
   启动零负担）；页面已 lazy load。可选手段（按性价比）：
   - 任务管理器/psutil 实测基线构成（Qt widgets 基座占大头，80MB 对 PySide6
     已属极瘦，不要为几 MB 牺牲功能）
   - 检查启动时图标/资源图片预缓存的驻留量（项目约定资源图启动即缓存，
     这是内存↔秒开的权衡，改动需与玩家确认）
   - 打包期可裁剪 PySide6 未用模块（qml/quick/webengine/3d 等）减小**磁盘**
     体积（注意：磁盘体积 ≠ 运行内存）
   - 真要压运行内存可评估延迟 import 非首屏重模块，但收益有限。
