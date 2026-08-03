@echo off
REM ── Manual MSVC environment (Build Tools on D:) ──────────────────────
set "MSVC=D:\VS Installer\VC\Tools\MSVC\14.44.35207"
set "SDK=D:\Windows Kits\10"
set "SDKVER=10.0.26100.0"
set "PATH=%MSVC%\bin\Hostx64\x64;%SDK%\bin\x64;%PATH%"
set "INCLUDE=%MSVC%\include;%SDK%\Include\%SDKVER%\ucrt;%SDK%\Include\%SDKVER%\um;%SDK%\Include\%SDKVER%\shared;%SDK%\Include\%SDKVER%\winrt"
set "LIB=%MSVC%\lib\x64;%SDK%\Lib\%SDKVER%\ucrt\x64;%SDK%\Lib\%SDKVER%\um\x64"
REM Verify
where cl.exe >nul 2>&1 && echo [ok] cl.exe on PATH || echo [FAIL] cl.exe missing
