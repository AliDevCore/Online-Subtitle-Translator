# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

root_dir = Path(SPECPATH).parent.resolve()
assets_dir = root_dir / 'assets'

datas = [
    (str(assets_dir), 'assets'),
]

hiddenimports = [
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'keyring',
    'keyring.backends',
    'keyring.backends.Windows',
    'requests',
    'charset_normalizer',
    'sqlite3',
]

a = Analysis(
    [str(root_dir / 'app' / 'main.py')],
    pathex=[str(root_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'faster_whisper', 'ctranslate2', 'torch', 'psutil'],
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
    name='Online Subtitle Translator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(assets_dir / 'app_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Online Subtitle Translator',
)
