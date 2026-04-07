# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('manifest.json', '.'), ('installer_gui.py', '.'), ('C:\\Users\\redacted\\Documents\\AI\\Spellcaster\\spellcaster\\plugins', 'plugins'), ('C:\\Users\\redacted\\Documents\\AI\\Spellcaster\\spellcaster\\assets', 'assets')]
binaries = []
hiddenimports = ['tkinter', 'tkinter.scrolledtext', 'tkinter.ttk', 'installer_gui', 'darkdetect', 'PIL', 'requests']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['install.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    console=Fal