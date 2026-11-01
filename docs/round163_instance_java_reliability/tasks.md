# round-163 任务清单

> 规格：[spec.md](spec.md) · 状态：待批准 → 批准后按顺序执行
> 每项完成后立即回写本文件状态，并在 `CHANGELOG.md` 汇总验证结果。

## 阶段 A：P0 缺陷修复

- [x] **T1 启动对话框不再无限增高**
  - 文件：`src/launch_dialog.py`
  - 改：删除 `resizeEvent`；`_fit_text_heights` 改用对话框宽度 + 2~5 行钳制 + 幂等 setMinimumHeight；`showEvent` 延迟一次；单行标签只设一次静态高度。
  - 验：`tests/test_launch_dialog_layout.py`（offscreen 稳定性断言）+ 真机观察。

- [x] **T2 安装器公开完整性判定**
  - 文件：`src/core/install.py`、`src/launch.py`
  - 改：新增 `find_installed_loader`；`launch._find_installed_loader` 转发；新增 `cleanroom_installer_java()`。
  - 验：`tests/test_instance_java_plan.py` 覆盖 cleanroom/forge/neoforge 匹配。

- [x] **T3 体检新增安装完整性层**
  - 文件：`src/core/instance_health.py`
  - 改：`_check_install`（loader_missing / client_missing / base_missing）；`scan_health` 与 `quick_check` 接入；`_check_java` 感知强制；`apply_fix` 增 `install_loader`（UI 层处理）/`set_java_force`/`clear_java_force`。
  - 验：单元测试 + 真机 `_diag_instances_java.py` 两个实例都出现 `loader_missing`。

- [x] **T4 体检对话框反馈 + 一键补装**
  - 文件：`src/mod_check_dialog.py`
  - 改：`note_lbl`；`_apply` 区分 changed/unchanged；`extra_fixes` 多按钮；`_run_install()` 复用 `LaunchProgressDialog` + Worker，完成后 save + rescan。
  - 验：手动点修复可见提示；补装跑通后 finding 消失。

- [x] **T5 启动格式结构优先**
  - 文件：`src/instances.py`、`src/pages_instances.py`
  - 改：`detect_format` 先判 `_is_ac_owned`；`_update_fmt_hint` 增加「实际识别」与不一致提示。
  - 验：单测断言 stale curseforge → ac；真机实例徽章/提示正确。

- [x] **T6 Cleanroom 安装器 Java 解耦**
  - 文件：`src/core/install.py`
  - 改：安装器 JVM 用 `cleanroom_installer_java()`；无 25 时 `--provision-java` 且状态明示；完成后 `reset_scan_cache()`。
  - 验：真机 Cleanroom 补装日志出现自动下载；`~/.cleanroom/java` 出现 25。

## 阶段 B：P1 强制 Java 功能

- [x] **T7 统一 Java 计划**
  - 文件：`src/core/java.py`
  - 改：`java_major_or_zero`、`java_plan(inst, settings)`（need/auto/user/compatible/forced/detected）。
  - 验：单测 monkeypatch `scan_javas` 断言选型与 forced 语义。

- [x] **T8 实例字段与设置开关**
  - 文件：`src/instances.py`、`src/settings_dialog.py`、`src/pages_instances.py`
  - 改：`Instance.java_force` + `_from_dict` + `duplicate`；`_DEFAULTS["java_force_incompatible"]=False`；设置页复选框与配置收集；实例设置页 Java 需求/将使用/强制复选框。
  - 验：设置保存后 `launcher_config.json` 出现键；实例 JSON 出现 `java_force`（仅勾选时）。

- [x] **T9 启动链路强支**
  - 文件：`src/launch.py`、`src/main_window.py`
  - 改：`launch_instance(force_java=...)` 跳过兼容拦截并明示；无 Java 报错列出已检测项；`_confirm_java_before_launch` 返回三值并支持「仍然使用」；调用点传参。
  - 验：手动选不兼容 Java → 弹框三选；强制 → 不再拦截；全局强制 → 不弹框。

## 阶段 C：回归与交付

- [x] **T10 文案与测试**
  - 文件：`src/i18n.py`（zh-CN / en-US 同步新增 spec §3.11 全部键）、`tests/test_instance_java_plan.py`、`tests/test_launch_dialog_layout.py`、`regress.py`（SUITES 追加两项）。
  - 验：`venv\Scripts\python.exe regress.py` 全绿（24 项，i18n 键数对称）。

- [x] **T11 真机验收**
  - 自动 / 只读部分已过：24 套件全绿、`_diag_instances_java.py` 两实例均暴露
    `loader_missing`、格式纠正为 `ac`、Cleanroom 安装器 JVM 取到 Java 26。
  - GUI 手动六条（补装实跑、强制弹框、实例设置提示）留待用户真机实测。
  - 步骤：spec §4.2 六条逐条执行；记录到 `CHANGELOG.md`「### 🔍 验证」。
  - 必过：启动窗口稳定；体检有反馈；Forge 补装后能启动；Cleanroom 无 25 时安装器自动拉 25；强制 Java 生效。

- [x] **T12 打包部署**
  - 已完成：`build.py` → 部署 `<install-dir>`（新 exe 6,236,179 B /
    `_internal` 4104 文件），保留 `launcher_config.json` 与 `data/`；
    `AC_NO_TERMS=1 AC_LIVE=1` 冒烟运行 10s 正常，已清理 `ac.lock` /
    `ac.live.lock` / `.upd_bak`。
  - 步骤：`venv\Scripts\python.exe build.py` → 备份 `<install-dir>` 的 exe 与 `_internal` → 部署（保留 `launcher_config.json` / `data`）→ `AC_NO_TERMS=1` 冒烟 → 清理 `ac.lock` / `.upd_bak`。
  - 验：新 exe 大小与 `dist_beta` 产物一致；启动无异常。
