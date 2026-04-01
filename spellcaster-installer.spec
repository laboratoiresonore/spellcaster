# -*- mode: python ; coding: utf-8 -*-
# Windows standalone EXE spec
# Build: python build_installer.py --platform windows
# Or:    python -m PyInstaller spellcaster-installer.spec

from pathlib import Path
HERE = Path(SPEC).resolve().parent  # noqa: F821  (SPEC is PyInstaller built-in)

datas = [
    (str(HERE / 'manifest.json'), '.'),
    (str(HERE / 'plugins'), 'plugins'),
]
if (HERE / 'assets').exists():
    datas.append((str(HERE / 'assets'), 'assets'))

icon = str(HERE / 'assets' / 'spellcaster.ico') if (HERE / 'assets' / 'spellcaster.ico').exists() else None

a = Analysis(
    [str(HERE / 'install.py')],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=['tkinter', 'tkinter.scrolledtext', 'tkinter.ttk'],
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
    name='spellcaster-installer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
