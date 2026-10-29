# round-139 任务清单 — 组件化下载（按顺序执行）

## B1 构建侧：组件包 — ✅ 完成（2026-10-28）
- [x] diff 法生成 Chromium 栈文件清单（完整构建 vs 主包，文件级差集）
- [x] 清单复核：31 文件 = WebEngine 专属件 + **幽灵链 10 件**（全量 PE 扫描发现
      `qtvirtualkeyboardplugin → Qt6VirtualKeyboard → Qt6Quick → Qt6Qml*` 与
      `imageformats/qpdf → Qt6Pdf` 封闭集合，定点清出主包、diff 自动收进组件）
- [x] `build.py --components`：一键「完整包→暂存→主包→组件包」，
      产出 `ac_webengine_runtime_1.0.0-beta.zip`（**96.9MB** / 解压 231.1MB /
      31 文件）+ `.zip.sha256` + `.manifest.json`（逐文件 sha256、组件版本绑定）
- [x] 主包改由 lite 形态产出：`build.py` 默认即主包（`--full` 才出完整包），
      实测 **117.9 MB**（幽灵链转移后，原 135.4）
- [x] 验证：主包无任何 WebEngine/Qml/Quick/Pdf 残留；regress **12/12**；
      主包 exe 实启 15s 存活 + 欢迎页目视（`_main117_run.png`）

## B2 运行侧：核心机制 — ✅ 完成（2026-10-28）
- [x] `src/feature_pack.py`：`state()`（reason 细分 version-mismatch/files-missing/
      manual 手动合并/downloading+进度）/ `ensure_downloaded()`（复用
      `net_api.download_file` 断点续传+分片+退避；源顺序 env `AC_PACK_SRC` →
      配置 `component_src` → `DEFAULT_URLS`（release 填）→ exe 旁/
      `data/incoming` 旁置 zip）/ `install()`（同卷 `_tmp_pack` 解压→逐文件
      sha256→os.replace 落位→写 state）/ `uninstall()`（按清单删，不碰
      `data/extensions/` 与插件目录）
- [x] 版本绑定：state `launcher_version`+`component_version` 与当前不一致 →
      absent(reason=version-mismatch)（B5）
- [x] 失败回滚：校验/落位中途失败删已移动文件+临时目录，state 不写，不留半套
- [x] manifest 内嵌 zip 成员（`component.manifest.json`，build.py 同步改，
      运行端免二次请求；旧包回退 sidecar）
- [x] **验证 20/20 PASS**（`_b2_test.py`）：真件 A1-A9 全链路（31 文件落位/
      卸载 0 残留/插件数据存活/版本绑定）+ 合成边界 B1-B8（哈希回滚/旧版拒装/
      路径穿越/手动合并/无源报错）；regress 12/12

## B3 UI 接入 — ✅ 完成（2026-10-28）
- [x] `modules_page` 扩展区状态机：
      未装/版本过期/文件缺失 → **安装卡**（标题+说明+「安装扩展组件(~110MB)」/
      「组件已更新重新下载」按钮+进度条+%+取消钮）；装完未重启 →
      「待重启」提示（附 import 失败原因，不误报为没装）；可用 →
      **状态行**「已安装 · vX」+ 卸载钮（有安装记录才给，手动/开发环境不给）
- [x] 下载/安装在后台线程 + QTimer 200ms 轮询进度（不卡 UI）；取消走
      `threading.Event` → `net_api.cancel`（.part 保留可续传）；取消不弹错
- [x] 卸载确认 → 回安装卡（本会话宿主 import 已缓存，显式 `_pack_uninstalled`
      保持入口态，B4）；插件数据不碰（B2 已验）
- [x] i18n 中英词条：`ext.pack.*`（UI 15 键）+ `pack.err.*`（feature_pack
      错误 10 键，中英双语，feature_pack 经 `i18n.t` 抛文案）
- [x] spec `_src_modules` 补 `src.feature_pack`
- [x] 验证：py_compile 通过；离屏渲染三态目视 OK
      （安装卡 / 下载中 44%+取消 / 状态行+卸载，`_b3_*.png`）；
      B2 测试 20/20 + regress 12/12 复跑通过

## B4 验收与发布
- [ ] B1 主包 ≈135MB 实测（`[size]` 输出留档）
- [ ] B2 全新机路径实跑：装组件→重启→**示例插件真实渲染截图**
- [ ] B3 断网/中断重试；B4 卸载不清插件数据；B5 换版本强制重下
- [ ] B6 regress 12/12 + 断网冷启动无报错
- [ ] release 三资产说明文案（主包推荐 / 组件包 / 手动合并=完整版）
- [ ] CHANGELOG round-139 + 任务记忆落盘

## 决策点
- diff 清单与「示例插件实跑」对不上 → 补清单迭代，不改架构
- 组件下载源首站（GitHub release 资产 vs 自有镜像）实现时按 mirror.py 现状定
