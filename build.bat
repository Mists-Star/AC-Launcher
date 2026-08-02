@echo off
rem ═══════════════════════════════════════════════════════════════════════
rem  AC Launcher — 一键构建脚本（Nuitka，真·防反编译）
rem
rem  说明：用 Nuitka 把 main.py + src/ 编译成 C 再生成原生二进制，
rem        比 PyInstaller(pyc 字节码) / pyarmor(混淆) 更难反编译。
rem        首次构建需 10~20 分钟（PySide6 全量编译）。
rem
rem  产物：dist\AC_Launcher\AC_Launcher.exe （standalone 目录）
rem  依赖：venv + VS2022 MSVC（本机已装）
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

"venv\Scripts\python.exe" -m nuitka ^
  --standalone ^
  --enable-plugin=pyside6 ^
  --windows-console-mode=disable ^
  --include-qt-plugins=multimedia ^
  --jobs=1 ^
  --include-data-dir=assets=assets ^
  --include-package-data=minecraft_launcher_lib ^
  --windows-icon-from-ico=assets\icons\logo.ico ^
  --output-dir=dist ^
  --output-filename=AC_Launcher.exe ^
  --assume-yes-for-downloads ^
  main.py

IF %ERRORLEVEL% NEQ 0 (
  echo.
  echo [FAILED] Nuitka build error. Check the output above.
  pause
  exit /b 1
)

echo.
echo [DONE] dist\AC_Launcher\AC_Launcher.exe
echo 分发：整个 dist\AC_Launcher 文件夹打包（zip）即可。
echo 用户数据（data\）在 exe 旁首次运行时自动创建。
pause
