# PyInstaller build for Meerkat.  Build:  uv run pyinstaller meerkat.spec --noconfirm
# Output: dist/Meerkat/Meerkat.exe (one folder; starts faster than a one-file exe).
# Needs the models first:  uv run python scripts/download_models.py
# -*- mode: python -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH)

missing = [p for p in ("models/face_landmarker.task", "models/pose_landmarker_lite.task")
           if not (ROOT / p).exists()]
if missing:
    raise SystemExit(f"missing {missing}: run  uv run python scripts/download_models.py")

datas = [
    (str(ROOT / "models" / "*.task"), "models"),
    (str(ROOT / "assets" / "icons" / "*.png"), "assets/icons"),
    (str(ROOT / "assets" / "sounds" / "*.wav"), "assets/sounds"),
]
datas += collect_data_files("mediapipe")
datas += collect_data_files("desktop_notifier")

binaries = collect_dynamic_libs("mediapipe")

hiddenimports = [
    "pystray._win32",
    *collect_submodules("desktop_notifier"),
    *collect_submodules("winrt"),
]

a = Analysis(
    [str(ROOT / "src" / "meerkat" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython"],  # mediapipe imports matplotlib
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Meerkat",
    icon=str(ROOT / "assets" / "icons" / "meerkat.ico"),
    console=False,  # tray app: no terminal window
    upx=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="Meerkat", upx=False)
