@echo off
REM ── AC Launcher: PyInstaller build (internal/test) ─────────────────────
REM Auto-pip-install + spec bundle + post-fix (SSL dlls beside exe).
REM Usage:  build_pi.bat

setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

REM 1. ensure PyInstaller
"venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1 || (
    "venv\Scripts\python.exe" -m pip install pyinstaller
)
if errorlevel 1 goto :fail

REM 2. spec must exist; generate from the canonical one if needed.
if not exist AC_PiTest_noupx.spec (
    echo [ERROR] AC_PiTest_noupx.spec missing.
    pause & exit /b 1
)

REM 3. clean previous build dir (PyInstaller tries to nuke it and hits the
REM    WorkBuddy safe-delete hook, so leaving it around it safer).
echo [build] PyInstaller 正在打包...
"venv\Scripts\python.exe" -m PyInstaller AC_PiTest_noupx.spec --noconfirm ^
    --distpath dist_pi --workpath build_pi > _pi_build.log 2>&1
if errorlevel 1 (
    echo [FAILED] PyInstaller error. See _pi_build.log.
    type _pi_build.log | findstr /n "^" | findstr "^.*: " | findstr /v "INFO"
    pause & exit /b 1
)

REM 4. post-fix: ship libssl/libcrypto next to the EXE so _ssl.pyd's
REM    delayed-load finds them. Without this, the launcher reports
REM    "Can't connect to HTTPS URL because the SSL module is not available."
set "PYDIR=C:\Users\<user>\.workbuddy\binaries\python\versions\3.13.12\DLLs"
set "EXEDIR=dist_pi\AC_Launcher"
copy /Y "%PYDIR%\libssl-3-x64.dll"    "%EXEDIR%\" >nul
copy /Y "%PYDIR%\libcrypto-3-x64.dll" "%EXEDIR%\" >nul
if exist "%EXEDIR%\libssl-3-x64.dll" if exist "%EXEDIR%\libcrypto-3-x64.dll" (
    echo [ok] SSL dlls placed beside exe.
) else (
    echo [WARN] SSL dll copy failed; launcher may not reach HTTPS.
)

echo.
echo [DONE] dist_pi\AC_Launcher\AC_Launcher.exe
exit /b 0

:fail
echo [FAIL] see output above.
pause
exit /b 1
