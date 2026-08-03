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
    hiddenimports=[
        "src",
        "src.core",
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
    runtime_hooks=["_rt_hook_ssl.py"],
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
    runtime_hooks=[],  # no ssl debug hook in release builds
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
