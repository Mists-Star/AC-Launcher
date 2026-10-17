# round-103 记忆（2026-10-16）— 手绘矢量 logo · 死代码清扫 · 设置裁字修复

玩家四点要求：启动 logo 换掉 MC 字体；清掉无用/多余/100% 走 fallback 的代码；
排查「设置项生效与否」隐患；（顺延）修设置→外观底部文字裁切。

## 1. 启动 logo：手绘矢量 monogram（去字体依赖）

- **起因**：MC 像素字体属「字体不随包」（玩家 2026-09-25 决定）。发布环境
  三级查找（`data/fonts` → `assets/fonts` → 系统含 "minecraft" 的 family）
  **每一级都失败** → 两个启动页实际永远渲染系统 fallback 字体，是死路径。
- **拍板**：用 `AskUserQuestion` 让玩家在「手绘矢量 monogram / 几何极简字 /
  唯美衬线」三选一 → **手绘矢量 monogram**。
- **实现**：几何放 `brand.py`（品牌单一来源，两个启动页复用）：
  - `_sample_cubic` / `_sample_quad` / `_sample_arc` 采样中轴线；
  - `brush_path(points, w0, w1, wmid)`：沿中轴线生成**填充式锥形笔锋多边形**
    （宽度两端细、中部 wmid 鼓，`WindingFill`，**不加椭圆端帽**——加了会像串珠）；
  - `letter_a_strokes`：A 的**一条连续中轴**（左腿→圆角 apex→右腿）+ 横杠两笔；
    单条中轴可避免两腿分开导致 apex 出现缺口；
  - `letter_c_strokes`：`_sample_arc(308→52)` 单笔开月牙，开口向右，
    **从上方起笔**（角度递减：308°→270°→180°→90°→52°）符合手写顺序；
  - `letter_path` / `letter_bounds` / `draw_letter(painter, letter, reveal)`
    （reveal 0..1 按手绘顺序逐段画）/ `monogram_layout(gap)`（两字居中布局）。
- **两个启动页**：`welcome_window.py` 与 `splash_window.py` 均删去 MC 字体分支，
  改用 `brand` 手绘路径；出现动画改为**手写显现**；splash 保留逐字交错
  （A 先、C 后 ~0.23s）+ 缩放 + 光晕 + 底部进度条。
- **踩坑记录**：iso 字体端点的椭圆端帽读起来像串珠 → 去掉；apex 用单条连续
  中轴；C 的采样方向要反向才是「从顶部写下来」。
- **验证手段**：手绘路径**不受离屏 tofu 影响**（只有文字会变方框），故用
  `_render_monogram_preview.py` 离屏出 PNG 直接目检形态，有效。

## 2. 死代码清扫

- 删 `src/fonts.py`（整模块在发布环境 100% fallback）。
- 删 `welcome_window.mark_ready`（空 `pass`，全仓无调用）。
- 删 `welcome_window._on_stroke_done`（仅进度动画里 `update()`，随重写一并去掉）。
- 删 `brand.APP_TAGLINE`（原仅 splash 的 `_TAGLINE` 用，现无引用）。

## 3. 功能隐患：页面切换动画被装饰开关牵连

- `effects.fade_page_transition` 在 `EFFECTS_ENABLED`（= `effect_light_trail`，
  **默认关**）为假时直接瞬时跳转。但调用方 `main_window._switch_stack` 按
  `page_transition`（**默认开**）决定是否调用 → 「页面切换动画」开关形同虚设，
  默认配置下动画从不播放。
- 修法：`fade_page_transition` 不再看 `EFFECTS_ENABLED`，只由调用方按
  `page_transition` 决定；动画失败仍回退瞬时切换。
- 教训延续 round-101：**功能/感官流程不得被无关的装饰开关短路**。

## 4. 设置→外观 / 分辨率预设 文字被横向裁断（round-102 顺延）

- **量测方法**：`settings_dialog` 的 `SettingsPage` 可直接实例化；离屏建页后
  逐控件比较 `sizeHint().width()` 与 `width()`，`need>got` 即裁字。
- **根因**：`QScrollArea` 对页强制 `sizePolicy=Ignored`（贴合视口、不出横向
  滚动条），而外观组 8 复选框 / 分辨率组 8 单选各挤在一行 → 每项被压到
  83–188px，长标签（最长需 228px）被截断。
- **修法**：两处改 `QGridLayout` **两列**（`setColumnStretch(2,1)` 保持左对齐）。
  760/820/900/1024 四档宽度复测：**裁切 0 项**。
- **附带**：`lay.addWidget(app_grp)` 在源码里出现两次（L816 与 L932），Qt 会把
  「外观」组移动到末尾、打乱编号注释的预期顺序 → 删掉重复的一次。

## 5. 误报澄清（探索代理）

代理曾报 `page_transition` / `achievement_toasts` / `close_after_launch` 三项
「设置写了不生效」——**实为误报**：三者均在 `settings_dialog._collect` 采集，
且在运行期被读取（`main_window` L2912 / L1794 / L3366）。已核实排除。

## 6. 死代码全量清扫（脚本化）

- **判据**：符号名在**整个项目**（排除 venv/dist/build/__pycache__/.git）里出现
  次数 `== 1`（仅定义行）。这同时排除了 `getattr(self, "name")` 这类字符串动态
  引用（那样字符串本身会出现）。Qt 事件重写（`paintEvent`/`contextMenuEvent`…）
  与生成文件（`icons_rc.py` `qCleanupResources`）不在判据内——它们由 Qt C++ 侧调用。
- **删除**：33 个函数 + 2 个常量。大头是 round-100 极简重构的遗留模板构造器
  （`main_window` `nav_items`/`_yield`/`_make_scan_btn`/`_make_settings_btn`/
  `_action_card`/`_quick_btn`/`_open_mods`）、dev_mode 桩、`async_image` 扁平化前
  的装饰绘制，以及各模块无用访问器。
- **注意**：删除一个函数可能让其私有 helper 变成新的孤儿（级联），删完要**再跑一次**
  扫描（本轮 `_circle`/`_hex`/`_MOTIF`/`get_launch_count`/`is_frosted` 就是第二轮
  才暴露的）。
- **疑似未接线（保留上报，别当死代码删）**：`main_window.apply_home_style`
  （`onboarding.style_changed` 无人 connect）、`onboarding.reset_onboarding`
  （docstring 说设置页要用）、`net_api.fetch_liteloader_builds` /
  `fetch_legacy_fabric_games`、`plugin_host.webengine_unavailable_reason`。
  这类「本该被调用却没接上」是**功能隐患**，删掉等于把 bug 埋了。
- **配置键**：判「已写入但从不被读取」时，必须排除**动态键**——典型如
  `sound.py` 的 `cfg.get(f"sfx_{key}")`，会把 `sfx_click/hover/success/error`
  误判为死。真正可疑的：`launcher_ram_mb`、`jvm_aikars`、`collapsed_groups`、
  `enabled_modules`、`dev_mode_key`。

## 环境/工具

- venv 解释器：`<repo>\venv\Scripts\python.exe`（系统 python 无 PySide6）。
- 离屏诊断脚本须 `os._exit(code)` 收尾（PySide6 6.11 × Py3.13 shutdown
  fail-fast 0xC0000409），并在末尾 flush 或直接不依赖 print 缓冲。
- 诊断脚本 `_` 前缀；本轮产物 `_render_monogram_preview.py`、
  `_render_settings_probe.py` 在收尾时一并删除。

---

## 7. 收尾复核新增发现（2026-10-16 追记）

- **真 bug：`settings_dialog._reset_tutorial` 是空操作**。教程开关自 round-45
  起改为 flag 文件 `onboarding_done.flag`（`onboarding.should_show_onboarding`），
  而旧实现仍在 `os.remove("launch_count.txt")`——该文件已不参与任何判定；且
  文件不存在时 `if os.path.exists` 直接跳过、连 toast 都不弹。**「重置新手教程」
  按钮点了没反应**。修法：改成 `from .onboarding import reset_onboarding`
  再 `reset_onboarding()`（函数内导入，因 onboarding 顶层 import 了 settings_dialog，
  顶层互导会成环）。教训：**改了状态来源（count→flag）却没同步改所有消费者**。
- **配置键结论收窄**：上轮「5 个从未读取」不准确。二次核对——
  `jvm_aikars`（L1072 旧配置迁移读取）、`collapsed_groups`（折叠组读/写）在用；
  `launcher_ram_mb` 只在设置页回填滑块、**无运行期消费者**（hint 承诺的
  「AC 自身加速」不兑现，疑死设置）；真正从未读取的只有 `enabled_modules`
  与 `dev_mode_key`（后者已移除功能、注释标「保留」）。
- **「未接线」再定性**：`main_window.apply_home_style` + `onboarding` 的 style
  步骤分支/`style_changed` 属「主页模板切换」**刻意保留的恢复入口**（注释写了
  re-add 方式），**不是误留死代码**，别删。真正待决策的功能缺口是
  `fetch_liteloader_builds`/`fetch_legacy_fabric_games`（加载器不全）与
  `webengine_unavailable_reason`（未展示失败原因）。
- 收尾状态：`compileall` 通过；改动未提交 git（交给玩家 GitHub Desktop）。

## 待办（转入 round-104）— 2026-10-16 夜间记录

> 玩家当晚明确「这些明天来，太晚了」——**今晚不动代码**，仅登记。

1. **设置页折叠分栏改平铺**：玩家质疑「设置里放那么多折叠的分栏干啥，直接开在
   那一列列多好」。动手前须先查清当前折叠组（FoldGroup / `collapsed_groups`）
   有几个、各装了什么，评估平铺后单页是否会过长（过长则改左菜单分区或 tab）。
2. **全页面排版审计 → 简化/修改**：逐页梳理当前布局，标出「重复、多余、繁杂」
   项，**先产出审计文档**（页面清单 + 问题清单）供玩家确认，再改代码。
3. **对标其他启动器**：参考 PCL2 / HMCL / Prism Launcher 的排版与功能分布，
   纳入本轮优化。
4. **已确认的三项**（与排版审计合并为一轮，避免反复改同一批文件）：
   - 移除「启动器内存」设置（`launcher_ram_mb` 无运行期消费者）；
   - 把 `fetch_liteloader_builds` / `fetch_legacy_fabric_games` 接入版本选择；
   - 展示 `webengine_unavailable_reason`（WebEngine 不可用时给出具体原因）。
