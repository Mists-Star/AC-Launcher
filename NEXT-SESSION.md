# 明日计划（2026-11-23）— AC Launcher

> 今天（11-22）连做 round-243~247，修了 10+ 个 P0，但**全部未提交**、
> 用户端只验证了部分。明天的顺序按「先保住成果 → 再确认用户实测 → 再清债」。

## P0 开工第一件事：提交（5 分钟，别拖）

现状：`git status` 有 **33 个 M + 8 个 untracked**，`git diff --stat` 约
**+3741/-990 行**。这是 round-243~247 五轮的全部成果，一旦误操作全丢。

- [ ] 用 GitHub Desktop 或 `git add -A && git commit`，按 conventional：
  `fix(launcher): 整合包导入/补全/版本页卡顿/换肤过渡等 P0 修复（round-243~247）`
  分组描述：P0 修复 / 性能 / 功能包恢复 / 测试接缝。
- [ ] 提交后 `git status` 必须干净（_probe_*.py 与 _probe_out/ 是否入库先决定，
      建议探针入库、`_probe_out/` 加 .gitignore）。
- [ ] 确认 `AC_PiTest_noupx.spec` 的 `("assets","assets")` 会把
      `assets/features/{achievements,console,music}` 打进包（已实测在，提交前再瞄一眼）。

## P0 用户实测确认（昨天改了但用户没验的）

用户 22:31 收工时最后部署的包是 **22:30**（round-246 整合包 UI 接线）。
昨天用户反复报"还是不行"，两次是接线漏改导致的假通过——明天**先问用户实测结果**，
别再自顾自改代码。

- [ ] 问用户：22:30 的包里，导入整合包对话框是否显示了真实**版本/加载器/模组数**、
      安装时**进度条是否动**、`Dreamy World` 启动是否还报 `Version not found`。
- [ ] 让用户把对话框/报错截图发来，按图定位，不要再靠日志猜（日志停在 19:04，
      用户操作后没产生新条目，说明可能已经关掉程序）。
- [ ] 若仍失败：**先复制用户实际导入的 .mrpack/.zip 到项目内做 fixture**，
      用真实文件跑 `_probe_mrpack_ui.py`，而不是继续用合成的假包。

## P1 清债（昨天标记为"非我引入但红"的）

- [ ] `tests/test_build_trim.py`：静态检查发现 `build.py` 少 1 处
      `except KeyboardInterrupt: raise`（Ctrl-C 可能被吞）。昨天改成
      `copytree(dirs_exist_ok=True)` 后重新看该文件断言是否还成立。
- [ ] `tests/test_round235_toolbox_instance.py` 收集期报错（pytest 版本兼容？）。
- [ ] `tests/test_features.py` 曾经测被删的 `ensure_builtins`——昨天已恢复该函数，
      重跑确认（已 ALL PASS，提交前再跑一次）。
- [ ] 91 个测试尾部 `pytest.main(...)` 但缺 `import pytest`：昨天装了 pytest 后
      大部分转绿，但仍有文件顶层没 import。批量补 `import pytest` 或去掉尾巴，
      消除全量回归的假噪音。
- [ ] untracked 清理/归档：`_map_diag.txt`、`_renumber_243.py`、
      `_restore_builtin_features.py`；`assets/icons/launch.svg`、`online.svg`
      确认是否该入库。

## P1 未决产品决策（等用户拍板，不要擅自做）

- [ ] **`AC-Launcher-Features` 远程仓库**：`features.py` 的默认索引 URL 已指向
      `Mists-Star/AC-Launcher-Features/releases/.../features-index.json`，但仓库
      还是空的。用户选了"内置包随包发布 + 远程索引并存"，要问：**远程仓库要不要
      现在建起来**？不建的话远程安装按钮点了只会报"获取索引失败"。
- [ ] **成就页是否剥除**：昨天重做成了进度卡（chips + 分区），用户最初说
      "重做或剥除（用处不大）"，做的重做版用户还没评价。问一下保留还是剥。
- [ ] **排障经验沉淀**：昨天两次踩同一个坑（改了实现没改调用点、探针直接调函数
      假通过）。已写进 CHANGELOG/日志，考虑加进 `docs/OPTIMIZATION-LOOP.md`
      作为硬规则。

## 不需要做的（别浪费时间）

- 不要再用 `.old-<时间戳>` 备份程序文件（round-247 已改成逐文件覆盖）。
- 不要再改第三方原版 skill（`godot-wrap__skillhub` 空壳只标记，不动）。
- 不要再猜用户遇到的 bug——先看他的截图/实际文件，昨天两次假通过就是猜出来的。

## 下次会话开场口令

说"继续"，我先做：`git status` → 确认是否已提交 → 问用户 22:30 包的实测结果。
