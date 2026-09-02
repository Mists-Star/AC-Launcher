# AC Launcher — 毛玻璃（Frosted Glass）实现研究笔记

> 记录时间：2026-08-13（round-30）
> 背景：用户要求毛玻璃要**透用户桌面**（不是透启动器自己的背景），且**全部页面统一**。
> 本文件是后续实现的唯一参考——做毛玻璃先读这里。

## 一、结论先行

| 方案 | 透桌面？ | 实现成本 | 备注 |
|---|---|---|---|
| **系统级 Acrylic（Win DWM）** | ✅ 真透桌面 | 中（ctypes 调 DWM） | **唯一满足用户"透桌面"要求的方案**，本文件第 4 节 |
| PCL2 式（背景图 + BlurEffect） | ❌ 透的是启动器自己的背景图 | 低（Qt 自带 QGraphicsBlurEffect） | PCL2 实际做法，见第 2 节 |
| HMCL 式（背景图 + 透明度） | ❌ 同上 | 低 | 见第 3 节 |

用户明确要"透用户的桌面，不是透启动器背景" → **只能走系统级 Acrylic**。

## 二、PCL2 的真实实现（源码摘录）

仓库：`github.com/fuyn101/PCL2`（VB.NET / WPF）。
文件：`Plain Craft Launcher 2/Pages/PageSetup/ModSetup.vb`

```vb
' 背景图（铺满整个窗口的 Image，名叫 ImgBack）
' 模糊 = 对这张背景图应用 WPF 的 BlurEffect，不是系统模糊！
Public Sub UiBackgroundBlur(Value As Integer)
    If Value = 0 Then
        FrmMain.ImgBack.Effect = Nothing
    Else
        FrmMain.ImgBack.Effect = New Effects.BlurEffect With {.Radius = Value + 1}
    End If
    FrmMain.ImgBack.Margin = New Thickness(-(Value + 1) / 1.8)  ' 负边距防边缘露白
End Sub

' 背景透明度
Public Sub UiBackgroundOpacity(Value As Integer)
    FrmMain.ImgBack.Opacity = Value / 1000
End Sub
```

PCL2 完整链路：
1. 玩家选一张背景图 → 铺满整个主窗口（`ImgBack`）
2. 对背景图应用 `BlurEffect`（模糊半径可调 0-40，工具提示"较强模糊会导致严重掉帧"）
3. 前景 UI 面板覆盖在模糊背景图上
4. **透出的是模糊后的背景图，不是桌面**

## 三、HMCL 的实现

HMCL（Java/JavaFX）：
- `HMCL/src/main/java/org/jackhuang/hmcl/theme/` 主题系统
- 背景 = 玩家选择的图片（内置风景图/纯色/网络图片/本地图片）
- 只有**背景透明度**滑块，没有模糊
- 同样不透桌面

## 四、系统级 Acrylic（透桌面）—— 本项目要走的路

### 4.1 API 选择

| API | 系统版本 | 说明 |
|---|---|---|
| `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE=38, 3)` | Win11 22H2+ (22621+) | 新 API，Acrylic/Mica，最干净 |
| `SetWindowCompositionAttribute(ACCENT_ENABLE_ACRYLICBLURBEHIND=4)` | Win10 1809+ | 老 API，带 tint 颜色，兼容性最好 |

**注意**：`DWMWA_SYSTEMBACKDROP_TYPE` 在部分 Windows 版本/窗口类型上静默失败——稳妥做法是**先试 Win11 API，失败回退 Win10 API**（`src/win_acrylic.py` 已实现此逻辑）。

### 4.2 Qt 侧必须满足的条件（决定成败）

1. **窗口 `WA_TranslucentBackground = True`** —— 否则窗口是实色，Acrylic 透不出来。
2. **窗口不能完全透明** —— DWM 对完全透明的窗口不渲染模糊层（这就是 round-30"啥都看不到"的根因之一）。
   - 正确做法：给窗口一个**极淡的不透明底色**（如 `rgba(255,255,255,0.02)`）当"底盘"，
     或保证窗口至少有一层不透明/半不透明内容。
3. **卡片/面板用半透明 rgba（#AARRGGBB）** 覆盖在 Acrylic 上 → 透出模糊桌面。
4. Acrylic 只对**顶层窗口**生效——每个独立窗口（主窗口、Onboarding、扫描对话框、设置）
   都要单独调用 enable_acrylic。

### 4.3 已知坑（round-30 踩过）

- `frosted=True` 时 QSS 全局 `background: transparent` 让**所有控件透明**，卡片半透明白
  alpha 168 在纯透明窗口上叠不出层次 → 看起来"啥都看不到"。
  **修法**：窗口必须有"底盘"色 + 卡片半透明度别太低（≥0.55）。
- 只对 MainWindow 调 enable_acrylic → 其他顶层窗口（对话框）不透 → 用户觉得"只有首页有"。
  **修法**：所有顶层窗口统一调。

### 4.4 推荐实现（下一轮按此做）

```
frosted_theme=True 时：
1. MainWindow + 所有顶层对话框（OnboardingDialog / 扫描 / 设置 / 登录 …）：
   setAttribute(WA_TranslucentBackground, True) + enable_acrylic(winId())
2. QSS：bg_app_frost = rgba(255,255,255,0.03)（极淡底盘，不是 transparent）
   bg_frost = rgba(255,255,255,0.62)（卡片，透出模糊桌面）
   bg_panel/bg_input 同理半透明
3. 壁纸层（WallpaperWidget）在 frosted 时隐藏（透桌面不需要启动器背景）
4. 深色主题：底盘 rgba(20,20,30,0.05)，卡片 rgba(35,37,48,0.55)
```

## 五、文件清单

- `src/win_acrylic.py` —— DWM Acrylic 封装（Win11 + Win10 双 API 降级）
- `src/theme.py` —— `_frosted` 开关 + QSS token（bg_app_frost / bg_frost）
- `src/main_window.py` —— `_apply_acrylic_once()`（MainWindow 级）
- `src/settings_dialog.py` —— 设置「毛玻璃清透主题」开关

## 六、BlockHelm 的实现（2026-08-13 补充，用户指定参考）

仓库：`github.com/zqq-699/BlockHelm-Launcher`（.NET 8 / WPF，GPL-3.0）
关键文件：
- `Launcher.App/Services/Windowing/NativeBackdrop.cs` —— 系统 Acrylic 核心
- `Launcher.App/Services/Windowing/LauncherWindowBackdrop.cs` —— 模式切换 + 事件驱动
- `Launcher.App/Effects/ProgressiveGaussianBlurShader.cs` —— 图片背景渐进模糊（PCL2 式，非必需）

### 6.1 NativeBackdrop.cs 要点（比我们 win_acrylic.py 多的一步）

```csharp
// 1) 关键：把 DWM 玻璃帧扩展到整个客户区 —— 没有这步 Acrylic 只作用标题栏！
var margins = new Margins { Left=-1, Right=-1, Top=-1, Bottom=-1 };
DwmExtendFrameIntoClientArea(hwnd, ref margins);

// 2) 深色标题栏（Win10 20H1+）
DwmSetWindowAttribute(hwnd, 20, ref darkMode, 4);

// 3) 圆角
DwmSetWindowAttribute(hwnd, 33, ref round, 4);

// 4) 边框透明色（Win11 23H2+，0xFFFFFFFE = 无边框色）
DwmSetWindowAttribute(hwnd, 34, ref unchecked((int)0xFFFFFFFE), 4);

// 5) 系统背景类型（Win11 22H2+）—— None=1, Mica=2, Acrylic=3, Tabbed=4
DwmSetWindowAttribute(hwnd, 38, ref (int)TransientWindow, 4);
```

**结论：我们 win_acrylic.py 缺 `DwmExtendFrameIntoClientArea(margins=-1)`！** 这是 Acrylic 铺满窗口的关键。

### 6.2 LauncherWindowBackdrop.cs 要点（模式切换）

```
Acrylic 开：  GlassFrameThickness = -1（等价 ExtendFrameIntoClientArea）
              + window.Background = Transparent
              + SystemBackdropType = TransientWindow(3)
Acrylic 关：  SystemBackdropType = None(1) + 实色背景（light=白, dark=#151515）

事件驱动重刷：主题变化 / 背景效果变化 → 重新 Apply（不需要重启）
```

### 6.3 对我们实现的修正清单

1. `enable_acrylic()` 加 `DwmExtendFrameIntoClientArea(hwnd, {-1,-1,-1,-1})`
2. 加 `disable_acrylic()`（SystemBackdropType=None + 实色背景）—— 关闭时恢复
3. 设置页切换 frosted 时：开→enable，关→disable（不用重启）
4. 深色主题关 Acrylic 时的实色 = `#151515`（BlockHelm 用这个）
5. Acrylic 期间窗口背景必须 Transparent（Qt 的 WA_TranslucentBackground 等价）
