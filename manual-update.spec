# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Spellcaster Manual Update & Repair tool.
# Produces a lightweight standalone exe — no bundled plugins or manifest needed
# (everything is downloaded fresh from GitHub at runtime).

a = Analysis(
    ['manual_update.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pex = PEX(a.pure)
exe = EXE(
    pex,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='spellcaster-manual-update',
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
)
