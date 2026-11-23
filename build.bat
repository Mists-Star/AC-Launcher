@echo off
rem ═══════════════════════════════════════════════════════════════════════
rem  AC Launcher — 一键构建并部署到测试目录（PyInstaller onedir）
rem
rem  流程：构建(临时目录) → 裁剪(Qt翻译只留zh_CN/en) → 部署到 D:\Appdata\AC_Launcher
rem  用户数据（data\）与 launcher_config.json 在 exe 旁首次运行自动创建。
rem
rem  使用 PyInstaller onedir：PySide6 hook 成熟、开箱可用；
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
echo [DONE] 已部署到 D:\Appdata\AC_Launcher\AC_Launcher.exe
echo 直接运行该 exe 即可测试（便携模式，数据自带）。
pause
