# round-114 记忆：live view —— 给 Agent 的「实际体验」工具（AC 启动器版）

> 日期：2026-10-23。动机：用户问「ac 能不能像 live view 一样可以直接看到，
> 然后直接循环地修复视觉、对照修改」——此前 AC 只有 `regress.py --shots` 的
> **一次性离屏截图**（每次都要重新起进程），没有「看着画面 → 操作 → 再看」的闭环，
> 也就没法「自己操作应用实验功能」。
>
> 对标物是共享工具目录里的 liveview（Chromium CDP 版）：CDP 收帧 → WS 推面板 →
> HTTP 控制口收命令。AC 是 PySide6 原生窗口，等价物逐项对应如下。

## 一、能力对照

| liveview（浏览器） | aclive（AC 启动器） | 实现 |
|---|---|---|
| `Page.startScreencast` 收帧 | QTimer 定时 `win.grab()` → JPEG | `src/aclive.py` `_tick_grab` |
| CDP `Page.screencastFrame` → WS 推面板 | 自写 RFC6455 服务端广播二进制帧 | `_WSHub` / `_Handler._handle_ws` |
| 面板假光标 + 坐标回传 | 同（面板 HTML 结构照抄） | `tools/aclive/panel.html` |
| CDP `Input.dispatchMouseEvent` | `QMouseEvent` + `QApplication.sendEvent` | `_cmd_click` / `_cmd_move` / `_cmd_wheel` |
| CDP `Input.dispatchKeyEvent` | `QKeyEvent` | `_cmd_key` / `_cmd_type` |
| `Page.captureScreenshot` 存 PNG | `pixmap.save(path, "PNG")` | `_cmd_shot` |
| `Runtime.evaluate` 跑 JS | **`eval` 跑 Python**（AC 是 Python，等价能力更强） | `_cmd_eval` / `_cmd_exec` |
| 面板页 | 面板页 | `tools/aclive/panel.html` |

## 二、文件

| 文件 | 作用 |
|---|---|
| `src/aclive.py` | 服务端模块：帧流 + 控制口 + 输入注入 + eval 上下文 |
| `tools/aclive/panel.html` | 浏览器面板（画布 + 假光标 + 鼠标/键盘/滚轮回传） |
| `tools/aclive/live.py` | 启动器 / 控制口 CLI（start / stop / restart / ctl / shot） |
| `main.py` | 三个小钩子（见下） |

## 三、启用方式

**正式启动完全不受影响**——只有 `AC_LIVE=1` 时才挂载，代码路径与原来一模一样。

```bash
# 离屏（agent 独占，不弹窗、不抢焦点）
python tools/aclive/live.py start

# 有头真窗口（用户自己也能看和点）
python tools/aclive/live.py start --headful

# 改完源码热重启
python tools/aclive/live.py restart --page store
```

面板：http://127.0.0.1:8788/ ；控制口：`POST /ctl`。

环境变量：`AC_LIVE=1`、`AC_LIVE_PORT`(8788)、`AC_LIVE_FPS`(8)、`AC_LIVE_QUALITY`(62)、
`AC_NO_ONBOARDING=1`、`AC_NO_SPLASH=1`。沿用仓库既有的 `AC_JUMP` / `AC_DIAG` /
`AC_NO_ONBOARDING` 环境变量开关惯例。

## 四、命令集

| 命令 | 说明 |
|---|---|
| `shot {path}` | 抓当前窗口存 PNG（Agent 直接 Read 这张图 → **看**） |
| `nav {key}` | 切页（home / instances / store / settings / versions / mods …） |
| `click {x,y,button}` | 坐标点击（窗口绝对坐标） |
| `move {x,y}` / `wheel {x,y,dx,dy}` | 悬停 / 滚轮 |
| `key {key,text}` / `keys` / `type {text}` | 键盘 |
| `eval {expr}` | **在应用进程里跑 Python 表达式**（返回 repr） |
| `exec {code}` | 在应用进程里跑 Python 语句 |
| `info` | 标题 / 尺寸 / 当前页 / 可用页列表 / 观众数 |
| `wait {ms}` | 等待 |

eval 上下文里预置了：`win`、`app`、`Qt`/`QtCore`/`QtGui`/`QtWidgets`，
以及两个便捷函数：

* `find(text=..., cls=...)` → 控件列表（坐标是**窗口绝对坐标**，可直接拿去 click）
* `click_text('按钮文字')` → 按文字点第一个匹配的按钮

## 五、main.py 的三处改动

1. **独立锁文件** —— live 实例用 `ac.live.lock`，用户的正常启动器可以照常开着；
   同时 live 模式**跳过**「提升已有窗口」逻辑（否则会直接退出）。
2. **`AC_NO_SPLASH=1`** —— 跳过启动动画，画面第一帧就该是主窗口。
3. **`_show_main()` 里挂载** —— `if os.environ.get("AC_LIVE") == "1": attach_live(win)`。

## 六、踩过的坑

1. **Windows argv 会吃掉 JSON 的双引号** —— `live.py ctl '{"cmd":"info"}'` 传进去
   变成 `{cmd:info}`。两条解法：① 位置参数用 `'{\"cmd\":\"info\"}'`（反斜杠转义）；
   ② **推荐**：新增 `--cmd/--key/--x/--y/--text/--expr/--path` 形式，不用引号。
2. **所有碰 QWidget 的命令必须回主线程执行** —— 跨线程操作 QWidget 不安全。
   实现是 HTTP 线程把 `(fn, body, box, ev)` 塞进队列，Qt 主线程的 20ms 定时器取出来执行，
   再用 `threading.Event` 回传结果。
3. **弹窗是独立顶层窗口** —— `win.grab()` 抓不到模态对话框 / 右键菜单。
   `_current_window()` 按「弹出菜单 > 模态框 > 焦点顶层窗口 > 主窗口」的优先级选抓取目标。
4. **WS 帧是二进制的**，不是 base64 JSON —— 面板用 `createImageBitmap(blob)` 解码，
   比 base64 省一半带宽。
5. **客户端→服务端的帧必须解掩码**（RFC6455 强制），服务端→客户端不加掩码。
6. **离屏渲染的字体回退会变成方框** —— 设置 `QT_QPA_FONTDIR` 指向系统字体目录。
7. **离屏模式下导航栏的分组小字（游戏/资源/联机/系统）会糊成一团** ——
   这是离屏字体渲染的 artifact，**有头模式完全正常**。别把它当成 UI bug 去修。

## 七、验证（2026-10-23，本机实测）

| 项目 | 结果 |
|---|---|
| `compileall` | EXIT=0 |
| `regress.py` | 通过 10 / 失败 1（PII 门禁，根因**本机未装 git**，与改动无关） |
| PII 手工核验（4 个新/改文件） | 0 条残留 |
| `/ctl` info / nav / eval / find | 全部正常 |
| `/ctl` click（主题切换按钮） | 点击生效，按钮文本 `浅色`→`深色`，应用保持响应 |
| `/ctl` shot | 1100×720 PNG，截图内容与点击后的状态一致 |
| WS 帧流 | 3 秒 25 帧（≈8.3fps），单帧 ~27KB JPEG（magic `ffd8ff`） |
| 真实浏览器打开面板 | 7 fps，canvas 正确渲染启动器界面，控制台无报错 |
| 有头模式 | 窗口 1375×900，截图正常，分组小字清晰可读 |

### 一次真实事故：主线程被业务代码占死

点「开始游戏」→ 启动流程把 **UI 线程堵住**，`/ctl` 连续返回
`main-thread timeout`（10 秒上限）。这不是 liveview 的 bug，而是应用自身的
阻塞行为——但它暴露了一个必须说清的事实：

> **主线程被占死时，帧流和截图会一起停**（`grab()` 只能在主线程做）。
> 这与真实用户看到的「界面卡死」是同一件事，liveview 只是如实反映。

### 已知限制

* 主线程忙时 `/ctl` 全部超时（错误信息里写明 `main-thread timeout`）——
  这是特性不是缺陷：它让「界面卡住」变成可观测信号。
* 帧流只在**有面板连接时**才抓帧（没人看就不抓，省 CPU）。
* 离屏模式下鼠标是「幽灵」——事件注入不经过系统光标，屏幕上看不到真实指针位置。

## 八、下一步（未做）

* `eval` 通道目前只能读状态 / 改运行时对象，**改源码后必须重启**（`live.py restart`）。
  真正的「热重载」需要在应用里做模块 `importlib.reload`，风险较高，暂未做。
* 面板缺少「点击坐标回显」等调试辅助 UI。
* 帧流在 4K 窗口下 27KB/帧 → 8fps 约 220KB/s，本机局域网无压力，未做自适应码率。
