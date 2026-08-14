# -*- mode: python ; coding: utf-8 -*-
#
# Build (from the project root, using the swat conda env's Python so
# PyInstaller's import analysis sees the exact same site-packages):
#
#   C:\Users\Server\.conda\envs\swat\python.exe -m PyInstaller swat_app.spec --noconfirm
#
# Output: dist\SWAT_Wetlands_App\SWAT_Wetlands_App.exe (onedir build).
# Distribute the *whole* dist\SWAT_Wetlands_App folder, not just the .exe --
# the DLLs (GDAL/rasterio, Tk, etc.) live alongside it in _internal\.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import pathlib

block_cipher = None

PROJECT_ROOT = pathlib.Path(SPECPATH).resolve()

# --- rasterio: vendored GDAL DLLs -------------------------------------
# rasterio/__init__.py registers a *sibling* folder "rasterio.libs" via
# os.add_dll_directory(dirname(__file__)/../rasterio.libs) -- so that
# folder must land next to the frozen "rasterio" package folder, not
# inside it. We reproduce that exact layout in the onedir build.
import rasterio
_rasterio_pkg_dir = pathlib.Path(rasterio.__file__).resolve().parent
_rasterio_libs_dir = _rasterio_pkg_dir.parent / "rasterio.libs"

rasterio_binaries = []
if _rasterio_libs_dir.is_dir():
    for dll in _rasterio_libs_dir.glob("*.dll"):
        rasterio_binaries.append((str(dll), "rasterio.libs"))

datas = [
    ("resources", "resources"),
    ("config/hru_variable_aggregation.json", "config"),
]
datas += collect_data_files("customtkinter")
# rasterio's own gdal_data/proj_data live *inside* the rasterio package
# dir and are found by rasterio via its own __file__ at runtime -- no
# env vars to set manually, just make sure they're copied along.
datas += collect_data_files("rasterio")

hiddenimports = [
    "matplotlib.backends.backend_tkagg",
    "PIL._tkinter_finder",
]
# rasterio's Cython extensions (rasterio._io etc.) cimport sibling
# submodules like rasterio.sample at C level, which PyInstaller's static
# import scanner can't see -- pull in every rasterio submodule explicitly
# so none of its compiled .pyd pieces go missing at runtime.
hiddenimports += collect_submodules("rasterio")

# This app only ever uses the Tk backend for matplotlib (FigureCanvasTkAgg,
# no pyplot -- see CLAUDE.md) and never touches Qt/scipy/numba directly.
# matplotlib's PyInstaller hook still drags in every optional backend it
# finds importable in the env (PySide6/Qt6 here) "just in case" -- exclude
# them explicitly so the build stays small and doesn't chase Qt DLLs that
# aren't actually needed at runtime.
excludes = [
    "PySide6",
    "shiboken6",
    "PyQt5",
    "PyQt6",
    "scipy",
    "numba",
    "llvmlite",
]

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=rasterio_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={"matplotlib": {"backends": ["TkAgg"]}},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SWAT_Wetlands_App",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SWAT_Wetlands_App",
)
