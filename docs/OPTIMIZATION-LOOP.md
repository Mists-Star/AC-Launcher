# AC Launcher 自主优化循环（工作方法）

> 目的：把"优化启动器"从一次性人肉修补，变成**可重复、带判据、能自证**的循环。
> 每轮都按同一套流程走，不靠记忆里"上次修了啥"。

## 循环五步

```
① 调研（Research） → ② 审计（Audit） → ③ 修复（Fix） → ④ 验证（Verify） → ⑤ 交付（Ship）
        ↑                                                                      │
        └──────────────────────────────────────────────────────────────────────┘
```

### ① 调研：从外部输入优化点
- **来源**：主流启动器源码（PCL2/HMCL/Prism/Modrinth App/BakaXL/MultiMC）、
  通用游戏库 UX（Playnite/Steam/LaunchBox）、用户实机反馈。
- **要求**：每条优化点必须带「谁怎么做（源码/参数级证据）」+「对 AC 的一句落地建议」。
- **产出**：`docs/research/YYYYMMDD-<主题>.md`（可选），或直接在审计清单里标注来源。

### ② 审计：跑工具找差距
```bash
# 静态审计（秒级，可每轮都跑）
venv/Scripts/python.exe tools/ac_audit_loop.py --quick

# 全量（静态 + 报告落盘到 <data>/audit_loop_report.json）
venv/Scripts/python.exe tools/ac_audit_loop.py
```
审计维度（A–E）见脚本头部。**报告带 file:line 与判据**，不选"看起来像问题"的项。

### ③ 修复：只改确认的问题
- **先备份**大文件（`cp` 到 `_scratch/`），改完对比。
- **先自证判据**：写一个探针/测试，确认"问题真的存在"再动手，别对着假阳性修。
  - 真实教训：spec 漏列 21 个模块 → 查 PYZ 发现全部在包里（假阳性）；
    `.start()` 无 self 持有 36 条 → 全是 timer/动画/单例（假阳性）。
- **判据必须针对要验证的元素本身**，不能用"日志没报错"这种间接信号。

### ④ 验证：回归 + 端到端
```bash
python tests/smoke_all.py                          # 全页面构造冒烟
python tests/test_roundXXX_<domain>.py             # 每轮新增的行为回归
```
- 回归测试要**独立于被修逻辑**（不能"用同一条公式读备份再比对"）。
- 视觉/动画类：离屏截图（**必须设 `QT_QPA_FONTDIR=C:\Windows\Fonts`**）+ 真机目检。

### ⑤ 交付：打包 + 安全部署 + 记录
```bash
venv/Scripts/python.exe build.py                   # 构建→裁剪→部署 D:\Appdata\AC_Launcher
```
- 部署脚本只覆盖程序文件，**绝不 rmtree 用户数据目录**（data/、配置、lock）。
- 验证新模块进包：`PyInstaller.archive.readers.CArchiveReader(...).extract('PYZ.pyz')`
  再查 `ZlibArchiveReader.toc`（spec 列不列不作数）。
- 旧程序文件 `os.rename` 留底，确认后送回收站（Shell API `FOF_ALLOWUNDO`）。
- 写本地工作日志到开发机的会话记忆目录（`.workbuddy/memory/YYYY-MM-DD.md`，不入库）。

## 每轮的输入：优化清单（来自外部研究，持续补充）

### 已确认有效并在 AC 落地的模式
1. **动画防失效四件套**：stop 旧动画 + 从当前值接力 + `state()==Running` 防重入 + `finished` 清理（round-238）。
2. **昂贵操作只在状态真变时执行**：切版本不重刷 QSS（round-238），壁纸模式没变不重建。
3. **离线译名表**：mod 中文名构建期生成、运行时零网络（round-239）。
4. **双布局兼容**：新版/老版 MC 维度目录都认（round-237）。
5. **测试断言用相对基线**：不写死页数/对象身份，用"回到打开前基线 + 当前页在合法集合"（round-236）。

### 待评估的优化点（下一轮候选）
- [ ] 搜索历史 / 热门词（Playnite/BakaXL 模式，AC 资源中心目前没有）
- [ ] 骨架屏 shimmer（>200ms 才显示，防短操作闪烁）
- [ ] 乐观更新（先改 UI 再后台持久化，失败回滚）
- [ ] QSS 切换集中一处（PolyMC 的 Qt 坑：避免全控件重刷）
- [ ] 跨屏 devicePixelRatio 不缓存（PolyMC issue #331，审计 E 组已覆盖）
- [ ] MC百科离线译名表替换机翻表（网络通时，质量更高）

## 铁律（血泪教训，违反必返工）
1. **判据先自证**：报了问题先证明问题真存在，别对假阳性动手。
2. **离屏截图必设 FONTDIR**，否则全是 tofu 方框。
3. **新模块必进 spec**（虽然 PyInstaller 有时能自动收，但不能赌）。
4. **部署不能删用户数据**：`data/`、配置、lock、备份全是活的。
5. **终端纯 ASCII**；PowerShell stdout 会被吞，写文件再读。
6. **改大文件先备份**；结束锚点用下一个 `def`/`export function` + 语法校验。

## 本轮记录
- 2026-11-21：建立循环方法 + 审计器 `tools/ac_audit_loop.py`；
  自证并清除两个假阳性判据（spec 漏列、Worker 引用）；
  三路扩大范围研究（BakaXL / MultiMC-QT / 游戏库 UX）完成，候选清单已登记。
- 2026-11-21 round-240：用户追问「启动等待长」。自证发现启动前命令/内存优化配置
  全空、共享库检查仅 0.5ms——**启动器侧没有明显瓶颈，大概率是游戏加载 mod 慢**。
  没有耗时日志就无法定位 → 给 `_emit_step` 加 `launch_timing.log`（阶段 + 距上阶段
  耗时），实机跑一次即可看出卡在哪一步。回归 `test_round240_launch_timing.py` 6/6。

## 可观测性工具（诊断优先于盲改）
- 启动阶段耗时：`<data>/launch_timing.log`（round-240，每次启动自动追加）
- 崩溃堆栈：`<data>/crash.log`、`boot_err.log`、`fault.log`（AC_DIAG=1）
- 页面截图：`tests/shots_all.py` → `_shots_r112/`（**先设 QT_QPA_FONTDIR**）
- 审计清单：`<data>/audit_loop_report.json`（`tools/ac_audit_loop.py`）
