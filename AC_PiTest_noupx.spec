# -*- mode: python ; coding: utf-8 -*-
# AC Launcher — PyInstaller build spec.
# Build: venv\Scripts\pyinstaller.exe AC_PiTest.spec --noconfirm
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

# PyInstaller needs to find src.* as a real package, not a namespace package.
# Two adjustments:
#   1. Add src/ to pathex so PyInstaller's analysis can resolve "src.pages_*"
#      imports the same way Python does at runtime.
#   2. Hardcode every src.* submodule — collect_submodules + hiddenimports
#      both silently dropped src.pages_instances once the list grew large.
_src_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(SPEC)), "src"))
_src_modules = [
    "src", "src.accounts", "src.achievements", "src.achievements_page",
    "src.async_image", "src.brand", "src.core", "src.core.auth",
    "src.core.authlib", "src.core.easytier", "src.core.install",
    "src.core.java", "src.core.java_install", "src.core.mirror",
    "src.core.sound", "src.core.utils", "src.crash_analysis",
    "src.crash_dialog", "src.diagnostics", "src.diagnostics_dialog",
    "src.frameless", "src.i18n", "src.icons", "src.instances",
    "src.java_manager_dialog", "src.launch", "src.lobby", "src.lobby_dialog",
    "src.login_dialog", "src.main_window", "src.music_page", "src.net_api",
    "src.onboarding", "src.pages_browse", "src.pages_instances", "src.paths",
    "src.repair_log", "src.scan", "src.scan_dialog", "src.settings_dialog",
    "src.skin_dialog", "src.skin_render", "src.skins", "src.splash_window",
    "src.theme", "src.wallpaper", "src.win_rounded", "src.worker",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[
        # Force-ship libssl/libcrypto next to the exe so _ssl.pyd's *delayed*
        # load can find them. PyInstaller normally only places them in
        # _internal/, which is not on the DLL search path used by Python's
        # dynamic-load of _ssl.pyd at runtime → "SSL module is not available".
        ("C:/Users/<user>/.workbuddy/binaries/python/versions/3.13.12/DLLs/libssl-3-x64.dll", "."),
        ("C:/Users/<user>/.workbuddy/binaries/python/versions/3.13.12/DLLs/libcrypto-3-x64.dll", "."),
    ],
    datas=datas,
    hiddenimports=_src_modules + [
        # --- networking: PyInstaller misses these transitive deps ---
        # idna missing → urllib3 HTTPS raises ImportError → "HTTP 连接失败"
        "idna",
        "idna.core",
        "idna.idnadata",
        "idna.intranges",
        "idna.uts46data",
        "requests",
        "requests.adapters",
        "requests.auth",
        "requests.cookies",
        "requests.exceptions",
        "requests.hooks",
        "requests.models",
        "requests.packages",
        "requests.sessions",
        "requests.status_codes",
        "requests.structures",
        "requests.utils",
        "urllib3",
        "urllib3.connection",
        "urllib3.connectionpool",
        "urllib3.fields",
        "urllib3.filepost",
        "urllib3.poolmanager",
        "urllib3.response",
        "urllib3.util",
        "urllib3.util.connection",
        "urllib3.util.request",
        "urllib3.util.retry",
        "urllib3.util.ssl_",
        "urllib3.util.url",
        "ssl",
        "_ssl",
        "certifi",
        "charset_normalizer",
        "charset_normalizer.md__mypyc",
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
    upx=False,
    console=False,  # GUI app — no console window
    icon="assets/icons/logo.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AC_Launcher",
)
