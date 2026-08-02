# -*- mode: python ; coding: utf-8 -*-
# AC Launcher — PyInstaller build spec.
# Build: venv\Scripts\pyinstaller.exe AC_Launcher.spec --noconfirm
import os

block_cipher = None

# Collect src/ as a package so relative imports (src.core.*, src.pages_*) work.
datas = [
    ("assets", "assets"),
]
# minecraft-launcher-lib ships data files (mirror patch json etc.)
try:
    import minecraft_launcher_lib
    mll_dir = os.path.dirname(minecraft_launcher_lib.__file__)
    datas.append((mll_dir, "minecraft_launcher_lib"))
except Exception:
    pass

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "src",
        "src.core",
        "src.pages_instances",
        "src.pages_browse",
        "src.scan_dialog",
        "src.lobby_dialog",
        "src.login_dialog",
        "src.settings_dialog",
        "src.onboarding",
        "src.splash_window",
        "src.skin_dialog",
        "src.diagnostics_dialog",
        "src.crash_dialog",
        "src.java_manager_dialog",
        "src.lobby",
        "src.accounts",
        "src.skins",
        "src.skin_render",
        "src.worker",
        "src.theme",
        "src.icons",
        "src.i18n",
        "src.instances",
        "src.scan",
        "src.diagnostics",
        "src.net_api",
        "src.launch",
        "src.paths",
        "src.brand",
        "src.frameless",
        "src.win_rounded",
        "src.wallpaper",
        "src.async_image",
        "src.core.auth",
        "src.core.authlib",
        "src.core.mirror",
        "src.core.install",
        "src.core.java",
        "src.core.easytier",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AC_Launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no console window
    icon="assets/icons/logo.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AC_Launcher",
)
