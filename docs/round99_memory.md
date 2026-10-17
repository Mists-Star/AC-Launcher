# round-99 记忆（2026-09-27）— 极简美学重构第一波

用户上传「资源详情」截图反馈：配色不清晰、颜色丑、**色块压住文字**，要求把
AGENTS.md 里第一优先的「极简美学重构」提前上。拍板：分两波；默认观感 =
中性底 + 点缀强调色（花哨保留但走主题包/设置自选）；本地配置只关花哨项。
施工依据：`.trae/documents/ac-minimal-ui-wave1.md`（已获批准）。

## 1. 「半绿半紫」的真根因：Qt 8 位 hex 是 #AARRGGBB

### 现象
同一页里横幅/推荐条/chip 是荧光绿/怪黄，而 QSS 画的按钮是正常紫——
「一页两个色系」。

### 根因（运行时验证）
旧代码把 alpha 拼在**末尾**：`f"{accent}22"` = `#RRGGBBAA`。Qt 按
`#AARRGGBB` 解析 → `QColor('#7C3AED14')` = `(58, 237, 20, 124)` **亮绿色**
（实测）。凡是 `accent_soft` / `accent14/18/22/26/40/66`、加载器徽章
`colr1F` 的地方全部渲染成无关颜色。内联样式还挂着一个次要问题：不随
`apply_qss()` 刷新，但主因是颜色序。

### 修复
* `theme.py` 新增公开助手 `with_alpha(hex, alpha)`（内部走已有的
  `_to_translucent`，alpha 在前）；`_apply_accent` 的 `accent_soft` 改用它。
* 页面里禁止再手工拼末尾 alpha。

## 2. 全局基座（theme.py）

* 新增中性 QSS 类：`hero`（panel 底实色卡）/ `latest`（玻璃底 + 左侧 3px
  accent 竖条，唯一强调）/ `vrow`（行卡片）/ `badge`（中性小徽章：
  bg_hover 底 + text_sub 字 + 边框）/ `bare`（裸容器，见 §4）。
* `chip:checked` 从整块实色 accent 改「accent 描边 + accent_soft 淡底」。
* **强调色使用规约（写进 QSS 注释）**：accent 只允许出现在主按钮、选中态、
  focus 描边、进度条、≤16px 小图标点缀；禁止作文字背景/大面积底色。
* 只改「怎么用 token」，不改 token 名与 `apply_theme_pack` 合并逻辑。

## 3. 资源详情页 / 资源中心清扫

* `store_detail.py`：横幅 `qlineargradient(accent_soft→accent18)` → `hero`；
  推荐条 `accent14 底 + accent40 边 + accent22 标签` → `latest` + 中性
  `badge`；加载器 13 色品牌徽章默认关，**主题包声明 `"loader_vivid": true`
  才恢复**（新增 `_loader_vivid()` 读 `get_active_theme_pack_id()`）；
  loader 筛选 chip 删整段内联 → 全局 `chip`；版本号不再按最新态染 accent
  （星标保留 accent 点缀）；`_fill_latest` 加载器名默认 PlainText 中性；
  在线页面/加载更多/获取中文翻译统一 `cls="secondary"`（旧 `surface` 是卡片
  容器类：按钮上 `text-align:left; padding:0`，显示成裸文字「链接」）。
* `pages_browse.py`：`_letter_fallback` 从 `hash(title)%360` 随机饱和色块 →
  中性灰（bg_hover 底 + text_sub 字）；`TYPE_COLOR` 模块级快照（导入时把
  token 值写死，切主题不刷新）+ `#DB2777` 硬编码 → `_type_color()` 按需读
  COLORS，april 并入 text_sub。

## 4. 暗色「深色补丁压字」（像素级定位）

离屏暗色截图里发现：行卡片上版本号区域有 `#1E1E1E` 深色块（卡片是
`#2A2A2E`）。逐点采样 + 隔离实验确认：**plain `QWidget` 包装层
（`_VersionRow` 的 `v_wrap`）被全局 `QWidget { background: $bg_app_frost }`
规则画上了 bg_app 底色**——亮色主题下贴卡片色不可见，暗色主题下成为深色补丁。
修复：新增 `[cls="bare"] { background: transparent; }`，`v_wrap` 挂上；
`v_wrap.grab()` 像素验证 `alpha=0`。
（第二波注意：其他页面的 plain QWidget 包装层同样可能有此问题。）

## 5. 漏键 + 花哨默认

* `store.detail_shown / detail_load_more / detail_more_n / detail_all_loaded`
  中英各补（界面原本直接显示 key 原文）。
* `frosted_theme / transparent_window / effect_light_trail` 默认全翻 False：
  `settings_dialog.DEFAULTS` + 5 处 `cfg.get(..., True)` 读点、`main.py` 2 处、
  `main_window.py` 2 处；`page_transition` 保持 True。
  本地 `launcher_config.json` 仅关这 3 项（Java/内存/实例全保留）。

## 6. 验证（全离屏实测）

* `_audit_i18n.py`：MISSING 仅剩 3 个已知误报（`scan.note_` 动态拼接、
  `key`/`some.key` 文档串）。
* `_diag_store_detail_tmp.py`（round-66 冒烟已重写为 round-99 版，23 项）：
  全局类挂载 / 行内零 8 位 hex / 分页文案本地化 / 切 accent 后
  `accent_soft` = `#2214B8A6` 解析 `(20,184,166)` / `bare` 像素透明。
* `py_compile` 全绿；`_shots/store_detail_minimal_{light,dark}.png` 目检通过。
* 真机：`venv\Scripts\pythonw.exe main.py` 启动正常（AC Launcher 窗口），
  待用户点进资源中心 + 切 accent 复核。

## 7. 第二波路线（未做）

1. 其余页面：`pages_instances`（徽章色 27 处 inline）、`main_window` 首页 hero
   渐变 + 成就 toast、`login_dialog`、`modules_page`、`achievements_page`、
   `splash_window` 径向渐变；plain QWidget 包装层统一排查（见 §4）。
2. 欢迎页重构 + AC 标志简洁化；成就弹窗默认关 + 入口；动画三件套打磨
   （页面滑入/按压反馈/列表淡入）；OptiFine 资源中心入口移除（用户已拍板砍）。