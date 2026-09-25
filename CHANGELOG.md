# AC Launcher 更新日志

> **版本策略（2026-09-02 起）**：正式发布前不再使用 `v1.x` 前缀，改为纯
> `round-NN` 内部迭代号。对外版本号只有在按《RELEASE\_1.0.0\_CHECKLIST.md》
> 全部完工、完成首个 release 时才一次性打上 `v1.0.0`。

> **补记说明（2026-09-16）**：下列 round-78 ~ round-91 为 09-03 ~ 09-12 期间
> TRAE 迭代完成、但当时未同步 CHANGELOG 的批次（代码随 `57825e6` 一并入库）。
> 内容依据代码中的 `round-NN` 标记与改动反推整理；**日期为按文件改动时间推断**，
> 非逐条精确记录。

## round-98（2026-09-25）— PCL 版本隔离导入启动失败修复 · 外来客户端宽容启动

> 依据 `docs/round98_memory.md`（TRAE 实测记录）整理。

* **PCL2 版本隔离实例导入后启动报「版本不存在」**（P0，玩家实测）：
  根因是三层错位——①PCL2 版本隔离下 `versions/<id>/` 里既有 `<id>.json` 又有
  `saves/ mods/`，扫描正确地把它判为版本目录；②**复制导入时把版本目录拍平**
  到 `<instance>/.minecraft/*`；③`_probe_format` 见到 `<mc>/<id>.json` 判为 `iso` →
  `versions_root` 返回**实例目录的上级** → mll 去
  `data/instances/versions/<id>/<id>.json` 找，**必然不存在**
  （修复前实测 `EXISTS = False`）

* 修复（`instances.py::import_external` copy 分支）：复制前判
  `isolated_src = version_id 且 mc_dir/<version_id>.json 存在` —— 是则目标目录取
  `<new>/.minecraft/versions/<version_id>/` 并标 `isolation="isolated"`，
  否保持原行为。修复后实测 `isolation=isolated`、`game_dir` 落在版本目录内

* **外来完整客户端宽容启动**：PCL2/HMCL 等导入客户端（version_id 非空）启动时若
  classpath 缺库——旧逻辑会触发 `install_minecraft_version` 下载官方原版库
  （「在补 PCL 特殊格式的 MC」）。现在按其原库布局直接启动，缺失条目由 JVM 静默
  忽略 + 进度提示，**绝不污染玩家客户端**（`launch.py`）

* **关闭行为默认改「直接退出」**：`tray_minimize` 默认 False——点关闭按钮即退出
  （主流直觉）；设置里勾选「最小化到系统托盘」可恢复藏盘常驻

## round-97（2026-09-23）— 扫描 / 首页三处 bug

* **PCL2 分组折叠完全失效**：组键是内部码（`"PCL-CE"`）而组头文字是显示名
  （`"PCL2"`），旧 `_toggle_group` 靠 `launcher in w.text()` 反查按钮 → **永远匹配不上**。
  修复：`_rebuild_instance_list` 用 `_group_headers[launcher]` 直接持有按钮引用；
  `_toggle_group` 直查，并只替换行首 ▾/▸（老实现 `text[2:]` 每次点击累积空格）

## round-96（2026-09-23）— 单实例守卫加固

* 用户报「新手教程背后露出启动器页面」：根因是清理数据删掉 `ac.lock` 后旧实例未退出，
  新实例 `tryLock` **误成功** → 双实例并存，教程叠在旧主窗口上
* 修复：`tryLock` 成功后仍用 `FindWindowW` 按 `APP_DISPLAY` 标题找窗口，找到则提拉旧实例
  并 `unlock` 退出；`splash_window.__init__` 设 `setWindowTitle(APP_DISPLAY)`，
  让 **splash 阶段**也可被识别。实测：删运行中锁再启动 → 进程数不增

## round-95（2026-09-22/23）— 实例页折叠 / 教程叠窗 / 版本图标扁平化

* **实例页折叠后再也展开不了**：`_toggle_panel` 收拢时对整个 `_left_panel`
  `setVisible(False)`，折叠按钮随之消失。修复：新增常驻 40px 展开条
  （`_strip` + `reopen_btn`），收起后留在最左侧提供反向箭头
* **新手教程背后露出主窗口**：根因 = `_force_foreground` 里的
  `user32.ShowWindow(hwnd, SW_RESTORE)` 把"未显示"的窗口直接拉成可见，
  而它原先在教程分支之前运行（round-30/46 只挪了 `win.show()`，没防住这条旁路）。
  修复：repaint / raise_ / `_force_foreground` 整体移入 `_show_main()`、紧跟 `win.show()`
* **扫描弹窗 NameError**：`scan_dialog.py::_rebuild_instance_list` 用 `launcher_label`
  但仅在他函数局部 import → 模块级补 import。这可能是之前「扫描实例扫不出来」的元凶
* **版本库图标扁平化**：`make_version_pixmap` 重写为 HMCL/PCL2 式纯色圆角方块 + 居中
  版本号；无渐变 / 3D 方块 / 装饰 chips；文本色按底色亮度自适应（亮底深字）
* **侧边栏「其他」分组**：新增 `nav.group.other`，音乐 / 成就从「娱乐」移入

## round-94（2026-09-22）— 字体查找共享化（移除写死本机路径）

* **字体不随包**（用户 09-25 决定）：后续 AC 走「暴力极简」美学重写，MC 像素字体
  只是排障期可选外观，不再作为发布产物（另：随包字体 16MB 且属 Mojang 字形版权灰色地带）。
  已移除 `assets/fonts/minecraft_pixel.ttf`；`fonts.py` 三级查找保留——
  玩家想要像素字效果，把 .ttf 放进 `data/fonts/` 即可（优先级最高），不放则回退系统矢量字体
* **启动页回退链防 tofu**：无 MC 字体时 `_font_family` 可能为空串
  （极端环境下 `QFont().defaultFamily()` 返回 ""），`QFont("")` 渲染成缺字形方框；
  两处字体构造加防线——空串改用 `QFont()` 默认构造

* 新增 `src/fonts.py`：MC 像素字体三级查找——
  ①`data/fonts/`（用户放置即覆盖默认）②`assets/fonts/`（随包只读）
  ③系统已安装字体中 family 含 `minecraft` 的。全部缺失返回 None，调用方回退，启动动画永不崩
* 移除原先写死的 `<本地字体目录>\[苦力怕论坛]Minecraft(...).ttf`
  （换机 / 目录移动后静默失效），改为随包 `assets/fonts/minecraft_pixel.ttf`

## round-92（2026-09-21）— 模块化内容市场 · JS 扩展宿主（选装桥接）

* **模块化内容市场**（`src/modules.py` + `settings_dialog.py`「模块与扩展」分区）：
  主题包 / JVM 预设 / 音效包 / 崩溃策略统一为「可安装模块」
  （`data/modules/<id>/manifest.json` + 按类型载荷），支持本地 zip / 目录 /
  旧主题 .json 导入、应用副作用（写主题桥接 / jvm_preset / sfx 卷 / crash_policy）、
  导出、卸载回滚；内置精选目录 `assets/modules/catalog.json`（Aikar G1GC 预设、
  午夜主题、崩溃后自动重启）

* **JS 扩展宿主**（`src/plugin_host.py`，QWebEngine 选装）：扩展 =
  `data/extensions/<id>/manifest.json` + HTML 入口，manifest 声明权限
  （read_only_instance / change_args / exec_command / network），默认全拒 +
  逐项授权弹窗；无 QWebChannel 下用「注入客户端脚本 + 页面队列 + QTimer 轮询
  runJavaScript 回投」的沙箱桥接，越权调用一律返回 `__error`；随包示例 `sample-clock`
  演示 `window.AC.listInstances()`

* **崩溃策略接线**：`crash_pol` 模块接入崩溃流程——`active_crash_policy()` 读
  action=restart 时崩溃弹窗追加「重启游戏」按钮并设为默认（复用完整启动流程，
  含内存/磁盘预检）；auto_analyze=true 时弹窗关闭后非模态打开日志分析器
  （`main_window.py:_show_crash_dialog`）

* **扩展启动参数接线**：host `changeArgs` 写入的 `ext_launch_arg_jobs` 在
  `build_options` 消费——追加到 JVM 参数末尾并按 token 与预设/玩家参数去重
  （`launch.py`）

### 🔍 验证

1. `venv\Scripts\python.exe -m py_compile src/modules.py src/plugin_host.py src/modules_page.py src/settings_dialog.py src/i18n.py src/launch.py src/main_window.py`
2. `pythonw main.py` 冒烟：设置 → 模块与扩展三分区正常；无 QWebEngine 时扩展区给出选装提示
3. 市场流程：安装「Aikar G1GC 预设」应用、安装「午夜」主题应用、安装「崩溃后自动重启」应用
4. 扩展流程：安装示例时钟 → 授权弹窗逐项选择 → 打开扩展窗口显示实例数 + 走秒
5. 崩溃接线：应用 crash-policy-restart 后，人为制造非零退出（如启动不存在的版本），
   崩溃弹窗应出现「重启游戏」默认按钮，关闭后自动打开日志分析器

### 🐛 仓库侧审查修复（2026-09-21 入库前）

1. **zip 安装的「manifest 位于包根」形式实际装不上**（P1，功能失效）：
   `_install_from_folder()` 固定拿解压容器目录名去和 `manifest.id` 比对，
   而 zip 安装时容器是随机临时目录（`ac_mod_xxxx`），**必然不一致**并抛错——
   导致文档声称支持的包根布局全部安装失败。新增 `check_dir_name` 开关，
   仅 zip 包根场景跳过该校验；本地目录安装与「包内唯一顶层目录」仍照常校验

2. **扩展卸载后 `changeArgs` 注入的 JVM 参数永久残留**（P1，静默副作用）：
   `uninstall_extension()` 原先只删目录与授权，没清理全局配置里的
   `ext_launch_arg_jobs`——扩展卸载后它注入的启动参数**持续影响每次启动**，
   而玩家在 UI 里已找不到来源、无法撤销。新增 `clear_ext_arg_jobs()` 并在卸载时调用

3. **`changeArgs` 反复调用导致配置无限膨胀**（P2）：原实现每次追加一条 job，
   同一扩展重复调用会不停堆叠；改为按 `ext` 归属先剔除同名再写入（替换语义）

4. **zip 解压改为 fail-closed**（安全加固）：原先直接用 `zf.extractall()`。
   实测确认 Python 3.13 标准库**已内置路径净化**（`../../a.txt` 折叠为
   `<dest>/a.txt`，绝对路径去根），**并非可利用的 Zip Slip**；但净化是静默的，
   恶意成员会被悄悄塞进模块目录。改为逐成员 `realpath` 校验后显式拒绝，
   以便在安装阶段就报错中止，同时防御将来解释器行为变化

### 🔭 扩大范围审查（2026-09-21 第二轮：视觉 / 体感 / 文案）

offscreen 渲染 8 个页面逐一截图审查（`_shots_audit.py`，诊断脚本不入库）：

### 🐛 启动页 logo 字母粘连修复（用户报障「logo 加载偏移」）

1. **根因**：Minecraft AE 是位图字体，`setPixelSize(96)` 后 QFontMetrics 与
   实际渲染**严重脱节**——实测 metrics 报 `horizontalAdvance("AC") == 18`，
   实际墨迹约 134px（**失真 7 倍**）。`drawText` 按 advance 逐字符排布 →
   A、C 完全重叠粘连成一团歪字形；按 metrics 宽度居中 → 整体错位。
   round-78 加的 -14 负字距在失真度量上雪上加霜，纯调数字无解
2. **修法**：`_render_ac_pixmap()` 预渲染——A、C 各自画到离屏图 →
   逐像素测**实际墨迹**包围盒 → 按墨迹宽 + 14px 间距手动排布拼接；
   `paintEvent` 改为按墨迹图实际尺寸居中绘制（透明度/缩放动画不变，
   主题色经 `CompositionMode_SourceIn` 染色）。彻底绕开失真的字体度量
3. 回退链保留：预渲染异常时兜底纯文本 `AlignCenter` 绘制

offscreen 渲染 8 个页面逐一截图审查（`_shots_audit.py`，诊断脚本不入库）：

1. **联机大厅卡片不居中**（布局 bug）：卡片 `setMaximumWidth(560)` 后
   `QVBoxLayout.addWidget` 默认**靠左**，右侧空出约 600px，整个页面重心歪向左边。
   加 `AlignHCenter` 水平居中（垂直方向上下 stretch 本来就对）
2. **空状态文案敷衍**（AI 味）：`"市场为空。"`（4 字，与相邻 `"还没有安装内容模块。`
   `去下方市场挑一个…"` 的详细引导形成鲜明反差）、`"还没有安装扩展。"`（无动作引导）。
   中英 4 条全部重写为「现状 + 下一步动作」结构
3. 审查中确认**健康**的部分：文案整体克制（感叹号全库 14 处、空话词仅 2 处且为
   合理技术描述）、弹窗收敛已落实（`QMessageBox` 构造仅 6 处）、主题令牌体系完整
   （radii 4/6/10/12/16）、`setStyleSheet` 硬编码颜色仅 14 处且均为中性灰
4. **遗留观察项**（待真机确认，未动）：设置页「外观」分组 4 列 radio 文字疑似
   横向挤压（offscreen 字体下溢出截断，真实字体待验证）；versions 页列表空时
   滚动区为整块灰底（status 小字存在但视觉存在感弱，建议加居中空态图标）

> 补记：本次为 09-21 完成、随日期批次补记；启动主线施工图见
> `docs/LAUNCH_MODE_DESIGN.md`（⚠️ 编号冲突：round-92 已被本次占用）。

## round-91（2026-09-12）— 自绘符号收尾 · 自定义强调色贯通

* **全局消灭文本 emoji / 符号**：Windows 下 `✓` `●` `▶` 会被 Segoe UI Emoji 渲染成
  彩色字形、风格突兀——对勾、圆点、折叠箭头全部改为自绘
  （`pages_instances.py:380/1214`、`java_manager_dialog.py:93`、`crash_dialog.py:64`），
  并删除已迁移到 `state_pix` 的残留文本符号表 `_GLYPH`（`launch_dialog.py:46`）

* **强调色贯通自定义 accent**：主窗口光晕、按钮起色、强调边框均跟随玩家自定义强调色
  （`main_window.py:265/520/656`），内置紫主题下仍与品牌 `#7C3AED` 一致

* **字体下拉改为自动检测**：不再枚举候选列表，扫描系统全部已安装字体，
  列表项各用自身字形预览，按钮文字跟随当前选中项（`settings_dialog.py:304`）

## round-90（2026-09-12）— 横溢出治理：不出现底部横条

* 确立 UI 原则：**页面不允许出现底部横向滚动条**。横向溢出一律改由内容自身收缩解决，
  而非放任出现滚动条

## round-89（2026-09-12）— 折叠箭头自绘

* 版本卡折叠箭头改为自绘（不再用文本 `▶`/`◀`），继续 round-91 前的 emoji/符号清理

## round-88（2026-09-12）— 加载器官方风格图标

* 版本卡片左侧显示加载器官方风格图标，新增 10 个 `assets/icons/loader_*.svg`：
  forge / fabric / quilt / neoforge / cleanroom / liteloader / legacyfabric /
  labymod / optifine / vanilla（`pages_instances.py:342`）

* 隐藏不兼容卡片后，剩余可见卡重新按 3 列排布，不留空位（`pages_instances.py:907`）

## round-87（2026-09-12）— 全局自定义字体 · 徽章文字色跟主题

* **玩家可改全局字体**：先于 `apply_qss` 生效，让 `build_qss` 用新字体重建；
  设置页放弃修改时字体同步还原

* **来源徽章文字色跟主题 `text_main`**：避免主题色为浅色（如琥珀黄）时徽章文字看不清
  （`main_window.py:213`）

## round-86（2026-09-12）— 来源徽章显示真实来源名 · 关于/守则置底

* **导入实例允许显示来源启动器名**（PCL2 / HMCL / Prism 等），此前一律不显示
  （`instances.py:227`、`main_window.py:212/1146`）

* 设置页「关于 / 守则」独立成组并**置于最底部**——无论快速/高级分组怎么折叠都在最后

## round-85（2026-09-12）— 资源中心详情页重构 · 版本列表分页

* `store_detail` 重构为**行卡片流**，对齐主流启动器信息密度

* `net_api` 新增 `limit` / `offset` 分页（`net_api.py:558`）——
  Fabric API 上千版本，分页后秒开

## round-84（2026-09-12）— 主题切换按钮修复 · 实例卡操作行简洁化

* 修复「**主题切换按钮只有空框**」：图标/文字只在 `on_theme_change` 时更新导致丢失；
  改为不再依赖 SVG 文件

* 实例卡操作行简洁化：一行只放高频操作（打开文件夹 / 实例设置 / 设为当前 / 删除）

## round-83（2026-09-12）— 服务器收藏一键直连 · 系统托盘常驻

* **服务器收藏一键直连**：新增 `server_favorites.py` + `server_fav_dialog.py`。
  收藏服务器 → 用当前实例直接启动并连入，覆盖 `game_args` / 全局里的
  `--server`/`--port`（收藏直连优先于附加参数）

* **系统托盘**：关闭窗口后藏到托盘常驻，游戏与下载不中断

## round-82（2026-09-11）— 启动格式（磁盘布局）自适应识别

* 新增 `detect_format()`（`instances.py:297`）：`auto` 自动识别磁盘布局
  （`vanilla` / `iso` / `multimc` / `curseforge` / `modrinth` / `custom`），
  实例设置可手动强制覆盖；`auto` 时下方灰字实时显示「检测到：xxx」，
  强制时显示「已强制：xxx」

* 识别结果驱动版本 json 定位与游戏目录解析
  （**后续「启动方式自适应」UI 直接复用本 round 的交互模式**）

## round-81（2026-09-11）— 多实例并行

* 同一实例已在运行 → 提示而非重复启动

* 多实例进程跟踪：`poll()` 非 None 即已退出，逐条清理

* 崩溃诊断弹窗支持多实例：`log_path` / `base_dir` 取退出实例自己的值

## round-80（2026-09-11）— 崩溃诊断弹窗 · 磁盘预检 · JVM 智能推荐

* **崩溃诊断弹窗**：内容 = `latest.log` 尾部 + `crash-reports` 最新文件摘要；
  三个动作——打开日志目录（优先 crash-reports）/ 复制诊断信息（方便贴给整合包作者）/ 好。
  数据不足时按 reason 兜底，绝不阻塞 UI

* **磁盘空间预检**：游戏盘剩余 < （堆内存 + 2GB 余量）时弹警告

* **JVM 预设新增 `auto`**：按分配内存自动选组——≥8G 给完整 Aikar，
  否则给轻量 G1GC 组（避免 `AlwaysPreTouch` 预占内存挤压堆）

## round-79（2026-09-10）— 英文支持（实验性）· 大厅 · 工具箱

* **英文支持**：尚未全覆盖（主页等仍有中文残留），先标注「实验性」

* **79b**：大厅从「敬请期待」占位升级为真实页面；工具箱升级为真实快捷工具
  （打开目录 / 清理缓存）；新增窗口置顶开关

* **79e**：低内存警告——实例覆盖内存优先，超过可用物理内存时警告

## round-78（2026-09-10）— 实例存储拆分升级 · 跨启动器版本隔离导入

* **存储升级**：单文件 `data/instances.json` 拆分为
  `data/instances/<id>.json`（每实例全量、真理源、原子写）+
  `data/instances.index.json`（摘要索引，启动秒开、懒加载全量）。
  旧版单文件首次启动一次性迁移后改名 `.legacy.bak`

* **其他启动器版本隔离实例导入**：这类实例 `mc_dir` 本身就是 `versions/<id>` 目录，
  按此布局正确解析

## round-77（2026-09-03）— 日志终端：搜索高亮 · 导出到文件

> 落地《RELEASE\_1.0.0\_CHECKLIST》B 段第 1 项（对齐 Zaphyrous 日志面板——9-02 对标报告点名的真实差距：无关键词搜索高亮与导出文件）。

* **搜索并高亮全部匹配**：console 页新增搜索行（header 下方）。输入即高亮所有匹配片段
  （`accent_soft` 主题底色、大小写不敏感），右侧实时显示「n 处匹配」；**Enter 跳下一个
  匹配**（到底自动从头再来一轮），搜索框带清除按钮

* **过滤 / 搜索职责分离**：过滤行 = 只展示匹配行（保持原有语义）；搜索行 = 全量保留 +
  高亮 + 跳转。两行独立，互不影响

* **渲染防抖**：`_render` 内容未变化时不再重建 QPlainTextEdit 文本——避免 1s poll 每次
  重置选区、打断搜索选中（此前每次 tail 都会 `setPlainText` 全量重建）

* **导出到文件**：「导出…」按钮把当前视图（过滤后的展示结果）存为 `.txt`，默认文件名
  `<实例名>_<yyyyMMdd-HHmmss>.txt`；日志为空时 toast 拦截不落盘；成功 toast（复用
  round-76 弹窗收敛）、磁盘/编码失败保留模态 warn

* **i18n**：新增 `console.search_placeholder / search_count / export / export_title /
  export_done_title / export_done / export_fail / export_empty` 8 键（中英对称）

### 🔍 验证

* compileall 0 错误；`_diag_console_search_tmp.py` 11 项断言全过（计数/高亮片段数/
  清空复位/Enter 跳转选中/过滤联动/导出落盘内容一致/toast 触发/空日志拦截）

* `_diag_all.py` 全量回归绿（新脚本自动纳入 glob 集）；`_audit_i18n.py` ZH\_NOT\_EN /
  EN\_NOT\_ZH 均为空

## round-76（2026-09-03）— 弹窗收敛：通用 toast 浮窗 · 模态 info 大批收敛

* **通用轻提示浮窗** **`show_toast`**（main\_window）：右下角滑入 → 停留 → 淡出，
  中性主题色（accent 左侧竖条 + 玻璃底 + 随主题 text\_main/text\_sub，无硬编码色），
  与成就 toast（MC 棕金风）并存互不干扰；复用 `_active_toasts` 防 GC

* **`win_rounded.toast`** **辅助**：主窗口上下文 → 浮窗；窗口外/对话框内自动回退模态 info

* **收敛 10 处模态 info → toast**：

  * 实例备份完成 / 无快照提示 / 恢复完成 / 克隆提示

  * 实例应用整合包完成

  * 整合包导入完成（modpack.done）

  * 模组：未选实例提示 / 已是最新 / 批量更新完成 / 添加模组提示

  * 资源中心：创建实例成功 / 未选实例下载提示（×2）

* **保留模态的 info**（决策/错误/引导性质，3 处 + 对话框上下文）：
  新实例向导提示、选错包格式错误、坏包提示

* **顺带修 bug**：`_copy_mod_name` 里 `from .toast import toast` 引用不存在的模块
  （round-74 并行编辑覆盖时残留——右键"复制文件名"触发即崩溃），改为 `win_rounded.toast`

### 🔍 验证

* compileall 0 错误；offscreen 冒烟通过（show\_toast 存在、QSS 无遗留 token、模块导入全通）；
  残留检索确认无 `from .toast import`、剩余 info 仅 3 处合理保留

## round-75（2026-09-03）— 交互反馈：整合包导入进度 · 按压反馈补齐

* **整合包导入进度感**：`_import_pack_path`（按钮/拖拽共用入口）导入期间在主窗口状态条
  挂上转圈进度条 + 「正在导入，请稍候…」文案，成功或报错都恢复就绪——解决大包导入
  几十秒内"点了没反应"的错觉；复用已有 `modpack.importing` i18n 键（无重复新增）

* **按压反馈补齐**：`icon-btn` / `chip` / `pcl2-pill` 补 `:pressed` 状态
  （icon-btn → `$border_light`；chip/pcl2-pill → `$accent_soft` + accent 字），
  与基础/accent/danger/secondary/seg 的既有按压体系对齐

### 🔍 验证

* compileall 0 错误；offscreen 冒烟通过；build\_qss 无遗留 `$token`；i18n 键中英对称

## round-74（2026-09-02）— 主题一致性 QSS 层 · 模组右键菜单

* **模组右键菜单**：模组管理页 `ModCard` 新增右键（对齐 Prism/CurseForge 鼠标流）——「打开所在文件夹」（explorer `/select` 直接定位文件，排查冲突更快）/「复制文件名」（写进剪贴板 + 状态条轻提示，查 Modrinth 时即贴即搜）；新增 `mods.open_folder` / `mods.copy_name` / `mods.copy_name_done` 中英键

* **字号层级扩展**：`FONTS` 新增 `xs`(11) 档，`F_XS/F_XL` 五个档位常量；QSS 模板内散落的 `11px`（pill/导航分组）/`13px`（chip/pcl2-pill）全部改走 `$f_xs/$f_md` token——改字号档位或主题包覆盖 `fonts` 时全 UI 联动

* **圆角 token 化**：`RADII` 新增 `icon`(8) 档；`[cls=surface/row/tile/pill/loader-card/icon-btn]` 的硬编码 `8/9/10/12px` 圆角统一走 `$r_card/$r_btn/$r_small/$r_icon`

* **颜色 token 化**：seg/chip checked、secondary pressed 的 `#FFFFFF` 改 `$text_on_accent`（accent 亮度自适应文字色，不再固定白字）；radio 未选圆心 `#FFFFFF` 改 `$bg_frost`（dark 下随主题深色）；slider 白心新增 `slider_knob` token（浅/深主题同为白，主题包可覆盖，QSS 与 `AcSliderStyle` 自绘共用）；danger 按钮 hover 底的 `rgba(239,68,68,0.08)` 改为 `$danger_hover`（由 danger token 派生，自定义主题包改 danger 时联动）

* **build\_qss 兜底**：`text_on_accent` 冷启动缺失时默认白字，杜绝 QSS 出现字面 `$text_on_accent`

* **main\_window 主题切换按钮**：`_style_theme_toggle` 的 dark 三元色值改为读 `COLORS` token（`bg_btn/border/text_main/bg_hover`）、字号走 `F_MD`——"控制中枢"等任意主题包自适应，不再锁死 light/dark 两套灰

### 🔍 验证

* `build_qss()` 冒烟：QSS 生成无遗留 `$token`；`F_XS/R_ICON/F_MD` 常量正确；全量 `compileall` 0 错误

## round-73（2026-09-02）— README 重写 · 版本号回归 · 批量下载队列

* **README 重写**：以 round-72 现实为准（功能矩阵 / 技术栈 / DPAPI 隐私承诺 / 零遥测 / 自检命令 / 路线图），告别"轻量浅色主题"初版旧文案

* **版本号体系回归**：新增 `_diag_version_parse_tmp.py`——验证 26.1/26.2 新版本号、26w 快照、愚人节分流、classic legacy、缺日期条目全部正常；结论：type+日期排序天然免疫语义化版本号，不变式固化防回归

* **批量下载队列**：新增 `src/batch_download.py`（`BatchDownloader`）：4\~8 worker 线程池 + 任务队列 + **失败记录继续** + 线程安全进度/取消 + 存在即跳过 & sha1 复核；接入 CurseForge 整合包文件下载（原逐个顺序下载、失败中断整批 → 并发批下载、失败汇总）；新增 `modpack.curse_batch_fail` 中英键

* 修复 `_diag_all.py` 审计发现的 i18n 中英不对称（`modpack.curse_batch_fail` 英文表先落、中文表补回）

### 🔍 验证

* `_diag_batch_tmp.py` 6 用例 + `_diag_version_parse_tmp.py` 5 用例新增并通过；`_diag_all.py` **21 脚本 + i18n 审计全绿**；全量编译 0 错误

## round-72（2026-09-02）— 下载器加固：退避重试 · 毒 .part 清理 · 完整性校验

### ⬇ 下载引擎加固（借鉴 PCL-CE `LoaderDownload.cs` / `FileDownloader.cs`）

* `download_file` 重构为「单次尝试 + 有限退避重试」两层：网络类失败（连接/超时/5xx/内容不完整）最多重试 3 次，抖动退避 0.8s/1.6s ± 0.3s（对齐 PCL retry<4 + Sleep 300\~500+retry\*300），重试期间 `.part` 断点续传；**4xx 确定性失败立即抛错、不重试，并删除可能被污染的** **`.part`**（防毒化后续续传）

* 新增下载完整性校验：`Content-Length` 已知但实际写不满 → 判定内容不完整按瞬时错误重试（PCL `FileChecker` actualSize 的简化版）

* `.part` 临时后缀 + `os.replace` 原子收尾此前已有（round-37/48），本轮补上缺失的「重试 + 失败清理」两环；所有下载入口（mod/modpack/cf/optifine/java）统一收益

### 🔍 验证

* 新增 `_diag_retry_tmp.py` 5 用例（假传输 monkeypatch）：瞬时失败重试至成功（恰 3 次请求）/ 404 立即失败 + 毒 .part 清理 / 内容不完整重试 / 416 直接原子收尾 / 架构常数约定——全过

* 真实网络下载（version\_manifest 274KB）端到端通过；`_diag_all.py` 19 脚本 + i18n 审计全部 exit=0；全量编译 0 错误

## round-70/71（2026-08-30）— 日志打码 · 非 ASCII 路径警告

### 🛡 round-71 日志打码（借鉴 PCL-CE `McLogFilter.cs`）

* 新增 `src/log_mask.py`：`mask_launch_text()` 在**展示层**统一打码——启动参数段 `accessToken xxx`、当前登录 token、Windows 用户名，均保留**首尾各 5 位**中间 `*` 替换；磁盘日志原样保留，崩溃分析不受影响

* 控制台页 `set_game()` 接收登录 token，tail 日志时逐块打码后显示；崩溃分析证据 `detail` 构建时同样过打码，防分享截图/日志时泄漏凭证

* 修复 `_mask_access_token` 单段 token 尾部日志被重复拼接的缺陷（冒烟测试捕获）

### ⚠ round-71 非 ASCII 路径警告（借鉴 PCL-CE McLaunchPrecheck）

* 启动预检新增「游戏目录含非 ASCII 字符（如中文）→ 启动前给一次提示」：只警告不拦截，启动失败时把原因指向路径；设置 → 加载器 → 「非 ASCII 路径警告」开关可关闭（对齐 PCL-CE「不再提示」语义），配置 `warn_non_ascii_path`（默认开）

* 补齐 `settings.warn_non_ascii_path(_hint)` 中英键值，i18n 审计中英对称

### 📚 round-70 ModDownload.cs 下载引擎 · 崩溃分析模块深挖（PCL-CE 源码）

* 抓取 PCL-CE 关键源码至 `<workspace>\_PCLCE\`（`ModDownload.cs`、`FileDownloader.cs`、`LoaderDownload.cs`、`ModBase.cs`、`CrashAnalysis/` 29 文件）

* 下载引擎要点：多阶段 Loader 权重流水线 + 官方 URL `.Replace` 生成镜像源按序切换 + 临时文件后缀下载原子移动 + `FileChecker` 哈希按长度自动判型（MD5/SHA1/SHA256）+ 精确/最小 size + JSON 结构校验

* 崩溃分析要点：Collect→Prepare→Analyze→Output 四步管道、按文件名前缀分类日志、Fatal→Primary→Secondary 三阶段规则短路、46 种稳定 `CrashCause` 枚举映射本地化建议

* 详细对照见 `2026-08-30_PCL-CE下载引擎与崩溃分析深挖.md`

### 🔍 验证

* 冒烟测试：log\_mask 单/多段 token、用户名、无敏感文本全通过

* `_diag_all.py` 18 脚本 + i18n 审计（ZH\_NOT\_EN/EN\_NOT\_ZH 为空）全部 exit=0；全量编译 0 错误

## round-68/69（2026-08-30）— Quilt 加载器 · 设置简化 · 进程优先级

### ✨ round-68 Quilt 加载器

* 新建实例页新增 **Quilt** 加载器卡片与版本获取（`minecraft_launcher_lib` 的 Quilt 分支，`stable_only=True` 只列稳定版）

* 设置 → 加载器 → **「显示 Quilt 加载器」开关**（对齐 PCL-CE 的隐藏加载器思路）：关闭后 `_compatible_loaders` 与新建实例卡片同时过滤，不残留入口

### 🎛 设置简化（round-68）

* 设置页由三分区（快速设置/Java/高级设置）合并为**两分区：设置 / Java 管理**；原「快速设置」+「高级设置」纵向合并进「设置」滚动页，Java 单独成区（对齐 PCL-CE「Java 归游戏分区」的分类）

### ⚡ round-69 进程优先级

* 新增「进程优先级」下拉：标准 / 高 / 实时，写入 `process_priority` 配置

* `launch._priority_bits()` 用 Windows 原生 `CREATE_HIGH_PRIORITY_CLASS`(0x80) / `CREATE_REALTIME_PRIORITY_CLASS`(0x100) 与 `CREATE_NO_WINDOW` 按位或，随 creationflags 一次性生效，**零新增依赖**（不引入 psutil）

### ✨ round-62\~67 汇总补录

* 资源中心详情页（全部版本列表 + 按 MC 版本过滤 + 谷歌翻译中文说明，24h 缓存）

* 设置页滚轮误调预防；版本列表 24h 缓存 + 主窗口构建时后台预取提速

* Logo 页精简（去背景/文字，保留 AC 字母动画）；音乐播放/暂停按钮图标随状态切换

* 联机大厅工具选择器（无联机插件时引导 Terracotta/EasyTier/MCTier）；MC 像素字体 Logo 与 Splash 动画

* 修复：崩溃分析对话框缺 QWidget 导入、设置页未改动误弹保存、导航布局被硬编码篡改、启动窗口闪现与首次启动假死、authlib 配置原子写、退出后命令未执行、版本页加载缓慢等

### 🔍 验证

* `_diag_priority.py`（位映射/下拉/脏检测/creationflags 4 项）+ `_diag_quilt_tmp.py`（两分区/开关/过滤/兼容列表/版本分支 5 项）新增并通过

* `_diag_all.py` 16 脚本 + i18n 审计（ZH\_NOT\_EN/EN\_NOT\_ZH 为空）全部 exit=0；全量编译 0 错误

## round-61（2026-08-30）— 性能优化

### ⚡ 性能

* **流光卡视口裁剪**：`QScrollArea` 里滚出屏幕的卡片此前虽 `isVisible()=True`，仍每帧触发一次被裁剪掉的光栅化。现在按 `visibleRegion()` 判定，只有真正可见的卡片才推进动画（浏览页/实例列表滚动时 CPU 显著下降），滚回来自动续播

* **动态壁纸随可见性暂停**：GIF/视频壁纸在页面被切走、窗口最小化时暂停解码（`QMovie.setPaused` / `QMediaPlayer.pause`），回到页面/还原窗口自动恢复，避免后台白跑 CPU

* 修复进程退出时流光卡析构触发 `hideEvent → _stop_master()` 访问已销毁 QTimer 的 RuntimeError

### 🔍 验证

* 全量编译 0 错误；离屏功能验证（壁纸无媒体静默通过、滚动视口掩码正确）；`_diag_all.py` 全量回归 11 脚本 + i18n 审计全部 exit=0

## 2026-08-30 — 启动高级设置（对齐 PCL2）+ 玻璃拟态 + 拖拽修复

### ✨ 新增：启动高级设置（round-55，对齐 PCL2「启动游戏 / 版本设置」）

* **游戏附加参数**：全局默认 + 实例级覆盖，追加到游戏启动参数末尾；支持 `--server <ip>` / `--port` 服务器直连（自动解析并交给 minecraft-launcher-lib 注入）

* **JVM 参数预设**：三档下拉（默认不注入 / Aikar GC 优化 / 自定义），替换原 Aikars 单勾选框；旧配置 `jvm_aikars=true` 自动映射到 `aikar`，不丢用户选择

* **版本隔离**：默认共享 / 版本隔离（`versions/<版本>/`）/ 自定义目录三选项，经 `gameDirectory` 下发，实例级可覆盖全局

* **启动后 / 退出后命令**：`run_hook_cmd` 异步 `Popen` 执行（失败静默），游戏退出时自动补跑退出钩子

### ✨ 体验

* **窗口拖拽修复**：无边框 + Acrylic 透底下 `startSystemMove` 失效，改为「原生优先 + 手动移动兜底」双机制（标题栏 + 主窗口统一）

* **玻璃拟态（毛玻璃）**：Acrylic 透底 + 半透明卡片 `bg_frost`，全局/实例设置界面统一升级

* **版本页图标**：MC 风格 3D 等距方块（按区块纹理合成）

* **authlib 自动更新**：后台线程检查 GitHub 最新版，原子替换 jar，失败静默回退

* **渲染器选择 + 实验性 GC 性能选项**：实例级 `auto/software/legacy` 渲染器 + G1GC 优化组/禁显式 GC

### 🔍 验证

* 编译 0 错误；i18n 审计中英对称、模板变量全匹配；`_diag_launch/_diag_settings/_diag_exit/_diag_backup/_diag_shared` 等回归脚本全部通过

* 功能单测：`--server` 解析（含 `=` 写法）、版本隔离三种目录解析、Aikar 参数注入均 PASS

## 2026-08-03 — 导入体验修复

### 🛠️ 修复

* **复制导入进度条**：扫描导入选"复制到本启动器"时显示实时进度（文件级 + 当前文件名），可随时取消；取消则停止导入，不再静默回退为接管

* **导入后立即刷新**：主页 / 实例页扫描导入完成后，主页实例卡、实例列表、模组页实例选择器一次性全部刷新——之前只有当前页刷新，导入的实例要等切页才出现

* **主页"刷新列表"按钮修复**：之前点击必抛异常（HomePage 缺 inst\_mgr 引用），现在正常重读磁盘列表

* **主页"扫描接管"修复**：对话框关闭后的成就检查之前会抛 AttributeError 导致主页不刷新

* **新建实例顺序调整**：先选游戏版本 → 再选加载器 → Java（与主流启动器一致；加载器兼容性依赖版本）

* **一键导入全部**：支持中途取消（复制到一半点取消即中断，不再继续导后面的实例）

### 🔍 自检（不变）

* 10 项检查：依赖 / 数据目录 / 配置 / 账户 / 外置登录 / 资源文件 / Java / 游戏文件 / 网络连通性 / 界面状态（双页预警）

### ⚠️ 已知问题（Beta 1.1）

* 偶发"双页"视觉问题仍在排查（自检"界面状态"可检测是否实例重复）

* PCL2 实例目录结构与标准 MC 不同，启动可能触发多余下载（独立跟进中）

* 启动崩溃（窗口消失）个案在排查，可能与 PCL2 实例或新建实例连点有关

## 2026-08-03 — 首个公开测试版

### ✨ 核心功能

* **跨启动器实例接管**：扫描并导入 MultiMC / Prism / HMCL / PCL2 / 官方启动器的游戏实例（复制或接管）

* **实例管理**：新建 / 导入 / 删除 / 设置当前实例，游戏版本 + 加载器（Fabric / Forge / Quilt / NeoForge 等 9 种）选择

* **版本安装**：浏览并安装 Minecraft 版本（官方 / BMCLAPI 镜像源）

* **模组管理**：按实例管理 .jar 模组（启用 / 禁用 / 删除 / 添加）

* **启动游戏**：微软账户登录（Azure OAuth）/ 离线模式，自动选 Java、注入 Authlib-Injector（外置登录）

* **统御面板**：已接管实例数 / 来源启动器数 / 待修复实例一目了然

### 🛠️ 修复（本轮 20+ 项）

* **单实例锁**：双击 exe 或进程残留不再开第二个实例（消灭"双页/双进程"）

* **切页动画移除**：不再出现页面半透明叠加的"重影双页"

* **实例页空状态**：重写为 toggle 可见性方案，不再堆叠双卡片

* **"新建实例"按钮**：修复 LOADERS 元组解包崩溃（之前点击无反应）

* **"新建实例"按钮文字**：去掉文案中多余的"+"（避免"++"）

* **首页重建优化**：语言未变时跳过全量重建，欢迎页加载提速

* **模组页快速交互**：同步删除 + 重入保护，不再崩溃

* **SSL 修复**：exe 旁加载 libssl/libcrypto，资源中心 HTTPS 正常

* **欢迎页（Onboarding）**：样式应用延迟，不阻塞响应

### 🔍 新增：内置自检（诊断）

* 10 项检查：依赖 / 数据目录 / 配置 / 账户 / 外置登录 / 资源文件 / Java / 游戏文件 / **网络连通性** / **界面状态（双页预警）**

* 入口：左侧"工具"区 → 诊断，或 设置 → 诊断

### ⚠️ 已知问题（Beta 1）

* 偶发"双页"视觉问题仍在排查（自检"界面状态"可检测是否实例重复）

* 欢迎页初次加载仍偏慢（已部分优化）

* 微软登录需在 Azure 配置回环重定向地址

### 🖥️ 环境

* Windows 10/11 x64

* 需要 Java 8+（自动检测，可用自带 Java 或系统 Java）

