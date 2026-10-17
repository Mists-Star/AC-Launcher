# round-109 记忆：下载止血 + PCL 式详细进度

> 日期：2026-10-17。提交：`ba778dc`。承接用户实测反馈「下载卡死半个多小时，最后只能杀进程」。

## 背景：用户实测的卡死

用户在某次全新实例下载中**卡在某个哈希上超过 30 分钟**，进度条不动、不报错、无法取消，最后只能强制终止进程。正常下载远不需要这么久 → 这不是「慢」，是**挂死**。

根因（`minecraft-launcher-lib`，下称 mll）：mll 的每一次下载都走 `requests.session()` / `requests.get()`，**从不传 `timeout`**。一个卡住的 socket 会让它所属的 `ThreadPoolExecutor` 线程永久阻塞 —— `future.result()` 永不返回、不抛错、无法取消，UI 侧只能看到进度条钉死。

排查中发现一个关键陷阱：

```python
# requests.Session.request() 总会把 timeout 显式塞进 send 的 kwargs（默认 None）
# → kwargs.setdefault("timeout", ...) 永远不生效，必须判断「是 None」
if kwargs.get("timeout") is None:
    kwargs["timeout"] = _SEND_TIMEOUT
```

## 插曲：这批代码曾被历史改写冲掉

本轮改动首次落地后，**于 20:41:03 被 PII 脱敏的历史改写（filter-repo 类）重置工作区冲掉** —— 5 个文件同时被回退、`git status` 干净、`git stash` / `reflog` / 不可达对象均为空。改写同时改变了 SHA（`a9ffef4 → b35fe81`、`34c33c1 → a0c02fb`），**未提交的工作区改动不进任何 git 对象**，因此连 `_scratch/ac_backup_before_rewrite.git` 备份里也搜不到（全历史 grep `_SEND_TIMEOUT` / `_STALL_SECONDS` 零命中）。

唯一可用的恢复源是**编译前的 `.pyc`**。做法：先把 20:32–20:35 的四份 `.pyc` 快照到 `%TEMP%`（避免重新编译覆盖 oracle），再逐 **code object** 比对 `co_consts` / `co_names` / `co_varnames` 重建。

恢复后的忠实度（与快照比对）：

| 文件 | 差异数 | 性质 |
|---|---|---|
| `src/core/install.py` | 0 → 后 1 | 原本逐字节等价；后补的体检加固为其唯一的 1 处 |
| `src/core/mirror.py` | 1 | 仅 module docstring 的 `round-108→109` |
| `src/worker.py` | 2 | round 号 + `_DlStatus` 类行号常量（3.13 `__firstlineno__` 伪差异） |
| `src/main_window.py` | 1 | 仅 docstring 的 round 号 |

> 踩过的坑：Python 3.13 的类会带 `__firstlineno__`（类首行号作为常量出现），行号偏移会造成「伪 diff」；`__static_attributes__` 由编译器自动生成（按字母序的 `self.X` 名），原版 `_DlStatus` 因此**没有**显式 `__slots__`，重建时不能自作主张加。

## 本轮改动（5 文件）

| 文件 | 改动 |
|---|---|
| `src/core/mirror.py` | `MirrorSession` 注入 `_SEND_TIMEOUT=(10,30)` 超时 + `_RETRIES=1` 单次重试；`_try_source()` 分流 strict；`InstallContext` + `install_scope()`（`threading.local()` 令牌）+ `abort()`；`_RequestsShim` 替换 mll 子模块的 `requests`；`patch_install_session()`（进程级 `_PATCHED` 幂等门） |
| `src/core/install.py` | **打补丁与走镜像解耦**：`install_instance` / `install_mrpack` 的 `if mirror == "bmclapi" or proxy:` 条件包裹改为**无条件** `set_proxy` / `set_mirror` / `patch_install_session()`；`repair_minecraft_dir` 补上同一组加固 |
| `src/worker.py` | `_DlStatus` 把 mll 裸状态串翻译成「阶段 + 计数 + 文件名」；`ProgressWorker` 新增 `abort()` / `_arm_stall()` / `_disarm_stall()` / `_on_stall()`；`run()` 用 `install_scope()` 包裹 |
| `src/main_window.py` | `_dl_pct` / `_dl_aborted` 状态；`_on_download_progress` 记录百分比；`_on_download_error` 区分「取消」与「失败」；新增 `_confirm_launch_while_downloading()` 逃生口；`_handle_play` 护栏改调逃生口 |
| `src/i18n.py` | 新增 12 键 × zh/en（`dl.phase.*` / `dl.downloading` / `dl.complete` / `launch.dl_busy_*` / `launch.dl_cancelled` / `status.download_stalled` / `status.download_cancelled`） |

### 1. 四项止血

1. **超时**：所有经 `MirrorSession` 的请求注入 `(connect, read) = (10, 30)`。read 是「相邻两次读之间的间隔」上限，持续有数据到达的慢速下载不会被误杀，只有真正挂死的 socket 才抛 `ReadTimeout`。
2. **覆盖 mll 的三条自持 session 路径**：`_helper` / `install` / `runtime`（mrpack / fabric / forge / quilt 均经由 `_helper.download_file`，被传递覆盖）。`_helper.download_file` 在**无 session** 时走的裸 `requests.get()`（版本 json / logging config / 客户端 jar）与 `runtime` 的裸 `requests.get(_JVM_MANIFEST_URL)` 也一并被 `_RequestsShim.get()` 收进 MirrorSession。
3. **显式失败**：此前两源皆 404 时 `download_file` 只静默 `return False`，安装却照报 `"Installation complete"` —— 缺文件被误报为成功。现游戏文件两源皆失败时 `raise_for_status()` 显式抛出。
4. **护栏逃生口**：`_handle_play` 对「后台下载仍在进行」的实例默认拦截（防双写同一目录），但给出「取消下载并启动」按钮 —— `worker.abort()` 让在途下载立即抛错退出，护栏不再变成「永久拦住启动」。

多源回退：BMCLAPI（主源）失败 → 原始 Mojang URL（次源）。非 Mojang 主机（Modrinth / maven / 自有 API）不重写主机，但同样拿到超时 + 重试。

### 2. PCL 式详细进度

mll 的裸状态串对用户毫无意义：`"Download 4ab9e7d182a9a2a6a5d800764cf0b174343ecf92"`（资源文件就是一条 sha1）。回调包装层做格式化：

* **阶段名** —— 依赖库 / 资源文件 / Java 运行时，取自 mll 每段下载前发出的 `"Download Libraries"` / `"Download Assets"` / `"Install java runtime"`；
* **计数** —— 复用 mll 已在推的 `setMax` / `setProgress`（如 `12/89`）；
* **文件名** —— 库文件名保留，40 位 sha1 一律折叠（阶段名已说明是资源文件）。

效果举例：`正在下载依赖库（12/88） · asm-9.7.1.jar` → `正在下载资源文件（3021/5056）`（sha1 已折叠）→ `下载完成`。阶段未知时透传原始串（如 `Installing Fabric loader 0.16.9`），不做无根据的翻译。

### 3. 停滞检测

`_STALL_SECONDS = 45`：每次收到 mll 回调都重新计时，静默超时则提示「网络较慢，仍在等待下载…」。目的正是让用户能区分「慢」与「挂死」，而不是让进度条假装在动。

### 4. 体检修复路径加固（本轮追加）

`repair_minecraft_dir`（被 `diagnostics.py:445` 的实例体检调用）此前**直连 mll、完全无加固**。由于 `patch_install_session()` 有进程级 `_PATCHED` 幂等门，缺口仅在「**本次会话的第一个网络动作就是体检修复**」时暴露（跑过一次 `install_instance` 后就被覆盖）。现补上与 `install_instance` 一致的读 config → `set_proxy` / `set_mirror` / `patch_install_session()`，置于版本循环之前。

## 验证

* `python -m compileall -q src main.py` → **exit 0**
* i18n parity：**zh 1283 / en 1283，零单边键**（与冲掉前的数字完全一致）
* 离线 15 项断言（`%TEMP%` 临时脚本，不入库）→ **ALL CHECKS PASSED**：镜像重写 + 官方源回退 + 非 Mojang 透传 + `abort()` 作用域内/外/并发独立令牌 + shim 覆盖面 + `install_instance`/`mrpack`/`repair` 三处无条件 patch + 进度格式化（sha1 必须被折叠）+ 停滞文案 + i18n 占位符一致 + 离屏 UI 冒烟
* **挂死实测**（对「accept 后一个字节都不发」的本地 socket）：`MirrorSession` **4.0s 抛 ReadTimeout**（测试期把超时缩短为 (2,2)），而裸 `requests.Session`（mll 的做法）同一时刻**仍在阻塞** —— 正是用户那次卡死的形状
* **真实网络 4/4**：资源文件被重写到 BMCLAPI 并下到 8140 B、sha1 校验通过；JVM 清单 200；`version_manifest_v2.json` 277 KB；单文件最坏边界 `2 源 × 2 次 × 30s read = 120s`

## 设计取舍

* **最坏 120s**：一个死文件两源各两次（连接 + 读）→ 120s 后抛错。相比「永久挂死」是可接受的确定上界。
* **非 Mojang 主机保持透传**：只加超时/重试，不改主机 —— 保证补丁在整个 app 生命周期常驻也不会误伤 Modrinth / maven / 自有 API。
* **`_MIRROR_ON` 在请求时判定**：打补丁与走镜像解耦，官方源用户同样拿到超时/重试/取消。
* **round 编号**：`round-108` 已被 CurseForge 合规批次占用（`docs/round108_memory.md` + `CHANGELOG.md`），故本批代码注释与本文档统一用 **round-109**（与原件 docstring 里的 round-108 有意不同）。

## 待办 / 未做

* **真机目检一次**：状态栏 / 下载对话框新文案（`正在下载资源文件（3021/5056） · xxx.jar`、`网络较慢，仍在等待下载…`）与护栏逃生口对话框的排版 —— 离屏无字体，文字为 tofu，只能验结构与配色。
* `launch.py:878` 启动前补库亦直连 mll，但只对 AC 自有实例触发，而自有实例必然先跑过 `install_instance`（补丁已生效），实际不暴露，本轮未改。
* 离屏 teardown 退出码 `0xC0000409 (-1073740791)` 为**既存问题**（HEAD 亦可复现），与本轮无关，判定以 stdout 为准。
