# round-113 记忆：官方源提速 + 镜像路径修正 + loader maven 补全

> 日期：2026-10-22。承接 `2026-10-22_AC启动器_官方源加速实测.md`（前一轮只做了实测，
> 没动代码）与 round-110 的「下载测速 + 大文件分片」。
> 本轮目标：把实测结论**落进代码**——默认源、并发、连接池、镜像路径、loader maven。
> 实测全部在用户本机（12 核 / Windows / 该网络）完成，样本为 MC 1.21.11 的真实资源对象。

## 一、为什么改默认源（结论翻转）

round-110 时期本机的实测结论是「BMCLAPI 更快 / 官方源跨境慢」。2026-10-22 重新实测，
**结论反转**：官方源比 BMCLAPI 快约 10 倍。

同口径（官方 manifest 里 80 个真实资源对象，共 41.9MB）：

| 源 | workers | pool | 耗时 | 速度 | p50 延迟 |
|---|---|---|---|---|---|
| 官方 | 8 | 8 | 15.31s | 2.67MB/s | 1192ms |
| 官方 | 16 | 16 | 6.78s | 6.03MB/s | 987ms |
| 官方 | 32 | 32 | 5.30s | 7.71MB/s | 1301ms |
| **官方** | **48** | 48 | 4.90s | **8.35MB/s** | 1779ms |
| 官方 | 64 | 64 | 5.63s | 7.27MB/s | 1934ms |
| 官方 | 96 | 96 | 6.05s | 6.76MB/s | 2453ms |
| 官方 | 32 | 10（requests 默认） | 6.29s | 6.50MB/s | 1778ms |
| 官方 | 32 | 32，每请求新 session | 7.66s | 5.34MB/s | 2168ms |
| BMCL `/assets` | 16 | 16 | 48.80s | 0.84MB/s | 4001ms |
| BMCL `/assets` | 32 | 32 | 49.47s | 0.83MB/s | 3744ms |

三条可复用的结论：

1. **48 并发是拐点**。再往上 p50 延迟从 1779ms → 1934ms → 2453ms 持续恶化，
   整体吞吐反而回落（8.35 → 7.27 → 6.76MB/s）。不是「越多越快」。
2. **连接池比并发数更关键**。同样 32 workers，pool=10（requests 默认）比 pool=32
   慢 16%；而「每请求新建 session」比复用 session 慢 30%。
3. **BMCLAPI 单连接抖动剧烈**。同一文件不同次请求会落到
   `bmclapi21.sakura.sld.tw` / `bmclapi.zhuqiy.top` / `bmclapi22.sakura.sld.tw`
   等不同后端节点，单连接速度在 0.02~1.35MB/s 之间乱跳。官方 CDN 响应头带
   `X-Cache: TCP_HIT`，无 302 抖动。

⇒ `download_mirror` 默认值从 `"bmclapi"` 改为 `"official"`，BMCLAPI 保留在设置里手动可选。

## 二、代码改动

### A. 默认源：`bmclapi` → `official`（P0-a）

`settings_dialog.py` 的 `DEFAULTS` 改了默认值，同时把 **10 处散落的兜底默认值**
全部对齐（否则老配置缺字段时会回落到旧默认）：

| 文件 | 位置 | 兜底值 |
|---|---|---|
| `src/settings_dialog.py` | `DEFAULTS["download_mirror"]`（130） | `"official"` |
| `src/settings_dialog.py` | 测速页 radio 选中态（912） | 跟随配置 |
| `src/launch.py` | 613 | `mirror=settings.get("download_mirror", "official")` |
| `src/main_window.py` | 1668 | 同上 |
| `src/core/install.py` | 159 | `mirror = cfg.get("download_mirror", "official")` |
| `src/net_api.py` | 573 | `mode = load_config().get("download_mirror", "official")` |
| `src/pages_instances.py` | 2094 | 跟随配置 |
| `src/pages_instances.py` | 2973-2977 | 硬编码 BMCLAPI → 跟随设置 |
| `src/modpack_import.py` | 117 / 148 | 函数签名默认 `mirror: str = "official"` |

`pages_instances.py` 那处原来是**硬编码**的 BMCLAPI，集成包导入无论用户设置什么都走镜像。

### B. mll 库/资源并发 16 → 48（P0-b，新增 `_patch_install_concurrency()`）

`minecraft_launcher_lib.install` 的 `install_libraries` / `install_assets` **都支持
`max_workers`**，但 `do_version_install` 调用时**不传** → 落到
`ThreadPoolExecutor` 默认值 `min(32, cpu_count + 4)` = **16**（本机 12 核）。
我们一直在吃这个亏。

两个关键机制细节（读源码确认，不是猜的）：

* 这两个函数在 mll 内部是**模块级全局查找**（`install_libraries(...)` 而非
  `install.install_libraries(...)`），所以 `setattr(mll_install, "install_libraries", wrapper)`
  **精确生效**；
* `_forge.py` 用的是 `from ..install import install_libraries` **直接引用**，
  替换 `install` 模块属性对它**无效**，必须单独替换 `minecraft_launcher_lib.mod_loader._forge.install_libraries`。

包装器保留调用方显式传入的 `max_workers`（不覆盖调用方意图），并打
`_ac_concurrency_patched` 标记保证**幂等**——`patch_install_session()` 会被多次调用。

### C. HTTP 连接池 10 → 64（P0-c）

`requests.adapters.HTTPAdapter` 默认 `pool_maxsize=10`（`pool_block=False`），
并发 48 时其余 38 条每次都要重新握手。在 `MirrorSession.__init__` 里挂自建 adapter：

```python
adapter = requests.adapters.HTTPAdapter(
    pool_connections=_POOL_SIZE, pool_maxsize=_POOL_SIZE, pool_block=False)
self.mount("https://", adapter)
self.mount("http://", adapter)
```

### D. 镜像重写表：host 级 → **路径感知**（P1-a / P1-b / P2）

原表只做「主机 → BMCLAPI 主机」的一对一替换，漏了两类：

1. **`piston-meta.mojang.com` 根本没进表** → 镜像模式下版本 json 与 assetIndex
   **一直直连官方**。真实路径是 `/v1/packages/<sha1>/<id>.json` 与
   `/v1/packages/<sha1>/<index>.json`（不是旧认知里的 `/mc/game/<id>.json`，
   后者上游实测 404），BMCLAPI 同构路径全部 200/206 可用。
2. **`libraries.minecraft.net` 的路径前缀错了** —— 按 PCL2 的映射应为
   `/maven` 而非 `/libraries`（实测两路径命中同一批文件、字节数一致）。

新表是 `(完整 URL 前缀, 替换前缀)` 的列表，共 **12 条规则 / 12 个主机**：

| 上游前缀 | 替换为 | 实测 |
|---|---|---|
| `launchermeta.mojang.com` | BMCLAPI 根 | ✓ |
| `launcher.mojang.com` | BMCLAPI 根 | ✓ |
| `piston-meta.mojang.com` | BMCLAPI 根 | ✓（新补） |
| `piston-data.mojang.com` | BMCLAPI 根 | ✓ |
| `libraries.minecraft.net` | BMCLAPI `/maven` | ✓（路径修正） |
| `resources.download.minecraft.net` | BMCLAPI `/assets` | ✓ |
| `meta.fabricmc.net` | BMCLAPI `/fabric-meta` | ✓ |
| `meta.quiltmc.org` | BMCLAPI `/quilt-meta` | ✓ |
| `maven.minecraftforge.net` | BMCLAPI `/maven` | ✓ |
| `maven.fabricmc.net` | BMCLAPI `/maven` | ✓（loader jar） |
| `maven.quiltmc.org/repository/release` | BMCLAPI `/maven` | ✓ |
| `maven.neoforged.net/releases/net/neoforged` | BMCLAPI `/maven/net/neoforged` | ✓ |

**P2 的最大价值点**：上游 `maven.neoforged.net` 在本机**直接 ConnectTimeout /
ConnectionReset**，BMCLAPI 代理能救 —— 也就是说不走镜像的话，NeoForge 根本装不上。

### E. 前缀匹配加路径边界保护

原 `_rewrite` 用 `url.startswith(prefix)`，会把 `https://libraries.minecraft.net.evil.com/...`
误判成命中。改为前缀后必须紧跟 `/` 或 URL 结束：

```python
rest = url[len(prefix):]
if rest and not rest.startswith("/"):
    continue
```

### F. 大文件分片：`chunk_mb` 4 → 2 + 显式 `threads=16`（P1-c）

客户端 jar（40.1MB）分片实测：单连接 0.39MB/s、4 路 1.62MB/s、**8 路 1.39MB/s（反而慢）**、
**16 路 3.19MB/s（最优）**。分片不是越多越好——跨境链路 RTT 才是瓶颈，
8 路起内耗占比就上来了。

关键陷阱：`net_api.parallel_download_file` 的 `cap = threads or min(ncpu, 8)`，
**不显式传 `threads` 就永远只有 8 路**。所以只改 `chunk_mb` 达不到最优，必须同时传：

```python
net_api.parallel_download_file(real_url, path, timeout=120,
                               threads=16, chunk_mb=2, cancel=_cancel)
```

2MB 切块让 40MB 文件有 21 个候选块，配合 cap=16 正好 16 路；
8MB 阈值文件则自然落到 5 路，不会过切。

## 三、验证

| 项目 | 结果 |
|---|---|
| `python -m compileall -q src main.py` | EXIT=0 |
| `tests/test_round113.py`（离线，44 断言） | **ALL PASS**（EXIT=0） |
| `tests/test_round113_live.py`（真机） | MirrorSession/48 比基线快 **2.06×** |
| `regress.py` | 通过 10 / 失败 1 |
| i18n parity | zh-CN=1287 en-US=1287 差异=0 |

真机实测（80 个真实资源对象）：

```
plain requests / 16 workers   7.51s   0.87MB/s   (6.6MB)
plain requests / 48 workers   6.35s   1.03MB/s   (6.6MB)
MirrorSession / 16 workers    4.35s   1.50MB/s   (6.6MB)
MirrorSession / 48 workers    3.64s   1.80MB/s   (6.6MB)
```

⇒ 连接池的贡献**大于**并发数本身（plain 16→48 只快 18%，MirrorSession 16→48 快 19%，
而 plain→Mirror 同并发下快 43%）。

`regress.py` 唯一的失败项是 **PII 门禁**，根因：`/repo/_pii_gate.py` 依赖
`git status --porcelain`，**本机没装 git** → `FileNotFoundError: [WinError 2]`。
与本轮改动无关；已用自写脚本手工核验本轮 10 个改动文件，**0 条 PII 残留**。

## 四、顺带查清的事实（避免下次再踩）

* **BMCLAPI loader 端点逐条探测**：
  * ✓ 可用：`/fabric-meta/v2/versions/{game,loader}`、`/quilt-meta/v3/versions/{game,loader}`、
    `/maven/net/minecraftforge/forge/maven-metadata.xml` + installer、
    `/maven/net/neoforged/neoforge/maven-metadata.xml` + installer、
    `/maven/net/fabricmc/fabric-loader/<v>/*.jar`、`/v1/packages/...`、`/v1/objects/...`、
    `/assets/<h[:2]>/<hash>`
  * ✗ 404：`/maven/net/fabricmc/fabric-installer/*`、`/maven/org/quiltmc/**`、
    `/api/maven/versions/releases/net/neoforged/neoforge`（该 JSON 端点保持走官方）
* **国内高校镜像站全部不可用**：nyist / nju / ustc / lzu / hit / ha / cqu 的
  `/bmclapi/libraries` 与 `/bmclapi/maven` 一律 404（cqu 直接 ReadTimeout）→ 不作为候选源。
* **HEAD 判定可用性不可靠**：多个端点 HEAD 返回 403/404 但 GET 正常
  （如 BMCLAPI `/maven/net/fabricmc/fabric-installer/...` HEAD 403）→ 探测一律用
  `GET + Range: bytes=0-0`。
* `launchermeta` 的 java-runtime manifest 官方与 BMCL 都是 404 —— 组件名已改成
  `java-runtime-epsilon`，**不是缺陷**。

## 五、未做 / 明日继续

* 真机整合包安装整体提速实测（单看官方源 + 48 并发下的端到端收益）。
* 资源中心 store 页的下载进度 UI。
* `download_mirror = "auto"`（测速选优）的自动判定逻辑目前只在设置页手动点测速时生效，
  尚未接入安装流程自动选源。

## 六、相关文件

* 改动：`src/core/mirror.py`、`src/settings_dialog.py`、`src/launch.py`、`src/main_window.py`、
  `src/core/install.py`、`src/net_api.py`、`src/modpack_import.py`、`src/pages_instances.py`
* 新增测试：`tests/test_round113.py`（离线）、`tests/test_round113_live.py`（真机）
* 前置实测记录：`2026-10-22_AC启动器_官方源加速实测.md`
