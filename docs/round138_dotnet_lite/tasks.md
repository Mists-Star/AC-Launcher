# round-138 任务清单 — .NET 轻量版（按里程碑排序，不做时间估计）

## M0 选型验证（立项门禁：全部通过才进 M1）
- [ ] `dotnet` 环境落位（.NET 10 LTS，失败回落 .NET 8 LTS），WPF 骨架可 `dotnet run`
- [ ] CmlLib.Core spike：下载并启动一个原版版本（含 Java 运行时自动安装）
- [ ] 认证 spike：微软正版登录跑通；盘点现有离线/第三方认证路径的覆盖差距
- [ ] `net_api.py` 端点全量清单（方法/路径/用途），标记 C# 平移工作量
- [ ] mrpack 导入 spike（CmlLib 无此能力，验证自实现路径）；CF 整合包 zip 记为 M2
- [ ] WebView2 spike：宿主页加载 `window.AC.*` 桥（对齐 `plugin_host.py` 协议）
- [ ] 体积验证：WPF hello-world 单文件 self-contained trim 实测大小，校准 G1 < 60MB

## M1 核心闭环（可日常自用）
- [ ] `Ac.Launcher.Core`：版本列表/下载/实例管理/启动参数（对照 `core/*` + `launch.py`）
- [ ] 实例页 + 设置页 + 控制台页（WPF MVVM，对照 `pages_instances`/`settings_dialog`/`pages_console`）
- [ ] 配置读写兼容现有 `launcher_config.json`（双栈期数据互通）

## M2 功能对齐
- [ ] 登录对话框全形态（对照 `login_dialog.py`）
- [ ] 皮肤（渲染/上传对照 `skin_*`）、音效（`core/sound`）、i18n 中英（`i18n.py`）
- [ ] Mod/整合包导入第二批（CF zip）、mod 更新/检查
- [ ] `net_api` 服务侧全接（商店/联机/成就按 M0 清单）

## M3 体验补齐
- [ ] 视觉：AC 主题、亚克力、无边框拖拽、圆角（对照 `win_acrylic`/`win_rounded`/`frameless`）
- [ ] 品牌自定义（round-136：`custom_logo_path`/`custom_title_text`/`splash_bg_image` 语义对齐）
- [ ] 扩展宿主 WebView2 完整移植（授权/沙箱/轮询桥语义对齐 `plugin_host.py`）
- [ ] 启动页动画（功能等价即可）

## M4 发布验收
- [ ] 体积实测 ≤ 60MB（或定档 framework-dependent 第二档）
- [ ] 回归：现有 `regress.py` 12 项在 .NET 版有等价验收脚本
- [ ] 目视双轨：启动/设置/扩展区/皮肤/音效 实跑截图
- [ ] 打包 zip 发布 + release notes（与 Python 双版本并列说明）

## 决策点（遇则回本 spec 修订）
- M0 任一 spike 失败（尤其 mrpack / net_api 协议不明）→ 停下评估，不进 M1
- 体积超预算两次 → 触发 framework-dependent 第二档讨论
