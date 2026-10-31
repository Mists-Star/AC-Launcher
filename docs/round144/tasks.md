<!-- [骨架复原版 · 2026-10-30]
     原文在 2026-10-30 目录整理事故中被 ASCII 往返压成 '?'（汉字全失）。
     本文件的行结构、标识符、代码位置 100% 取自原始损坏件的完好部分；
     被压掉的汉字按该骨架 + `docs/round144/spec.md` + `checklist.md` +
     `CHANGELOG.md` round-144 节复原。措辞非逐字原文。
     原始损坏副本：_scratch/_damaged_backup/mr144tasks.damaged
-->
# Tasks — round-144「仅留文字与背景，白色文字底不要」

> 配套 spec：`docs/round144/spec.md`
> 验收清单：`docs/round144/checklist.md`

## 任务分解（按 spec 的 4 个文件 + 144b 追加）

- [x] **T1 `src/theme.py` — `build_qss()` token 分支**
  `_wallpaper_surface` 判断置顶（先于 `_app_bg_translucent`）：
  `bg_app_frost` / `glassy` / `band` / `band_card` → `transparent`；
  `win_bg` → `bg_app` 实色垫底；非壁纸模式三个分支补 `band=bg_panel` /
  `band_card=bg_card` / `win_bg=bg_app_frost`（外观零变化）。
- [x] **T2 `src/theme.py` — QSS 模板 4 处 token 替换**
  `QMainWindow`→`$win_bg`；标题栏 / 页头 / `QStatusBar`→`$band`；页脚→`$band_card`；
  （144b）左导航 `#ac-nav`→`$band`。
- [x] **T3 `src/theme.py` — 卡片默认填充按窗归属**
  新增 `_on_wallpaper_window(widget)` / `default_card_fill(widget)`；
  `RoundedCard.paintEvent` 的 `fill is None` 分支改用它，`self._fill` 保持 None，
  边框/圆角逻辑不动。
- [x] **T4 `src/effects.py` — LightTrailCard 同步**
  `_card_fill()` → `_card_fill(widget=None)` 转调 `theme.default_card_fill(widget)`；
  paintEvent 调用点改 `_card_fill(self)`；流光/反射动画照旧。
- [x] **T5 `src/main_window.py` — 主窗标记**
  `__init__` 加 `self.setProperty("wallpaper_backdrop", "1")`。
- [x] **T6（144b）backdrop 改挂 MainWindow 并 `lower()`**
  修状态栏区露 `$win_bg` 白条。
- [x] **T7（144b）`resizeEvent` / `showEvent` 同步几何**
  `backdrop.setGeometry(self.rect())`，修首显四边白条。
- [x] **T8 收尾 / 文档 / 清理**
  写 `CHANGELOG.md` round-143/144 条目；同步把残留的绝对路径改成相对路径；
  写任务记忆 `notes/ac-launcher/任务记忆_AC启动器round144壁纸去白底_2026-10-28.md`；
  清掉或禁用测试用 schtasks `AC_R144_LAUNCH`；
  清理 Environmental Box 误提交；
  确认 round-143 的 `1.12.2-cleanroom` 启动 `'dict' object is not callable` 回退未被带回。

## 验收

- [x] `python -m compileall -q src` 通过
- [x] `python regress.py` 12/12
- [x] offscreen QSS 探针：壁纸模式 27 处透明无残留 token、对话框卡 alpha=255、
      主窗卡 alpha=0、关壁纸复原实色
- [x] 真机目视：首页 hero 无白卡、实例页白面板与页头灰条消失、左导航/标题栏/状态栏/四边铺满、
      「选择游戏版本」对话框白卡保留、无透桌面穿帮
- [x] 非壁纸模式外观零变化（`$band` 非壁纸时 == `$bg_panel`）
- [ ] 用户真机目视最终确认（待用户）
