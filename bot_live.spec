# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


pygame_datas = collect_data_files("pygame")
pygame_hiddenimports = collect_submodules("pygame")
yt_dlp_hiddenimports = collect_submodules("yt_dlp")
version_file = Path("build_assets") / "version.txt"

if not version_file.exists():
    version_file = Path("version.txt")

extra_datas = []
if version_file.exists():
    extra_datas.append((str(version_file), "."))


a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=pygame_datas + extra_datas,
    hiddenimports=pygame_hiddenimports + yt_dlp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    name="TTSLive",
    icon="icon.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
