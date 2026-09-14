# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "penghu_map_v1"), "penghu_map_v1"),
    (str(ROOT / "fall_of_penghu" / "data"), "fall_of_penghu/data"),
    (
        str(ROOT / "fall_of_penghu" / "render" / "static" / "backends" / "shaders"),
        "fall_of_penghu/render/static/backends/shaders",
    ),
]
binaries = []
hiddenimports = []
for pkg in ("pygame", "moderngl", "numpy", "shapely"):
    extra_datas, extra_binaries, extra_hidden = collect_all(pkg)
    datas += extra_datas
    binaries += extra_binaries
    hiddenimports += extra_hidden

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FallOfPenghu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="FallOfPenghu",
)
