@echo off
rem ═══════════════════════════════════════════════════════════════════════
rem  AC Launcher — 一键构建脚本（PyInstaller onedir）
rem
rem  产物：dist_beta\AC_Launcher\AC_Launcher.exe（含 _internal 目录）
rem  分发：整个 dist_beta\AC_Launcher 文件夹打包（zip）即可。
rem        用户数据（data\）与 launcher_config.json 在 exe 旁首次运行自动创建。
rem
rem  为什么用 PyInstaller：Nuitka 4.1.3 + PySide6 6.11 + Python 3.13 打包后
rem  报 shiboken6 ImportError（最小探针已复现，dist 内缺 shiboken6/__init__.py
rem  且 abi3 dll 位置错误）。PyInstaller 的 PySide6 hook 成熟，开箱可用；
rem  运行期性能两者持平，Startup 差距 <1s，对启动器无感。
rem
rem  依赖：venv（已装 pyinstaller）
rem ═══════════════════════════════════════════════════════════════════════
@echo on
cd /d "%~dp0"

IF NOT EXIST "venv\Scripts\python.exe" (
  echo [ERROR] venv not found. Create it with: python -m venv venv
  pause
  exit /b 1
)

IF NOT EXIST "assets\icons\logo.ico" (
  echo [ERROR] logo.ico missing. Run once:
  echo   venv\Scripts\python.exe _make_ico.py
  pause
  exit /b 1
)

"venv\Scripts\python.exe" build.py

IF %ERRORLEVEL% NEQ 0 (
  echo.
  echo [FAILED] PyInstaller build error. Check the output above.
  pause
  exit /b 1
)

echo.
echo [DONE] dist_beta\AC_Launcher\AC_Launcher.exe
echo 分发：整个 dist_beta\AC_Launcher 文件夹打包（zip）即可。
pause
