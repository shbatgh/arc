# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect necessary data and hidden imports
# You might need to add more hidden imports depending on your dependencies
hidden_imports = []
hidden_imports += collect_submodules('cellpose')
hidden_imports += collect_submodules('vedo')

# Find Python shared library for macOS
binaries = []
if sys.platform == 'darwin':
    python_lib = Path(sys.executable).parent.parent / 'lib' / f'libpython{sys.version_info.major}.{sys.version_info.minor}.dylib'
    if python_lib.exists():
        binaries.append((str(python_lib), '.'))

a = Analysis(
    ['Arc/main.py'],
    pathex=[],
    binaries=binaries,
    datas=[('Arc/resources', 'Arc/resources')],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2'],
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
    name='Arc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Set to True if you want to see the console output for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Arc',
)

app = BUNDLE(
    coll,
    name='Arc.app',
    icon=None,
    bundle_identifier='com.arc.app',
)
