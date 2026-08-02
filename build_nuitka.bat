@echo off
rem ═══════════════════════════════════════════════════════════════════════
rem  AC Launcher — Nuitka release build
rem  Compiles main.py + src/ to native C then machine code (真正防反编译，
rem  比 PyInstaller 的 pyc / pyarmor 的混淆强一个量级).
rem
rem  Output: dist\AC_Launcher\AC_Launcher.exe  (standalone dir)
rem  Build time: a few minutes. Needs VS2022 MSVC (already installed).
rem ═══════════════════════════════════════════════════════════════════════
@echo on
cd /d "%~dp0"

IF NOT EXIST "venv\Scripts\python.exe" (
  echo [ERROR] venv not found.
  exit /b 1
)

rem Nuitka standalone: -m nuitka --standalone main.py
rem   --enable-plugin=pySide6      PySide6/Qt plugins & dlls auto-collected
rem   --include-data-dir=assets    ship icons/artwork (read-only data)
rem   --include-package-data=minecraft_launcher_lib   mll data files
rem   --windows-icon-from-ico      exe icon
rem   --output-dir=dist --output-filename=AC_Launcher.exe
rem   --assume-yes-for-downloads   auto-fetch any missing ccache/ordering deps

"venv\Scripts\python.exe" -m nuitka ^
  --standalone ^
  --enable-plugin=pySide6 ^
  --include-data-dir=assets=assets ^
  --include-package-data=minecraft_launcher_lib ^
  --windows-icon-from-ico=assets\icons\logo.ico ^
  --output-dir=dist ^
  --output-filename=AC_Launcher.exe ^
  --assume-yes-for-downloads ^
  main.py

IF %ERRORLEVEL% NEQ 0 (
  echo.
  echo [FAILED] Nuitka build error. Check output above.
  exit /b 1
)

echo.
echo [DONE] dist\AC_Launcher\AC_Launcher.exe
echo Data (per-user) will be created next to the exe on first run.
pause
