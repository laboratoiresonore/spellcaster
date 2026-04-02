# -*- mode: python ; coding: utf-8 -*-
# macOS .app bundle spec
# Build: python build_installer.py --platform macos --onedir
# Or:    python -m PyInstaller spellcaster-installer-macos.spec

from pathlib import Path
HERE = Path(SPEC).resolve().parent  # noqa: F821

datas = [
    (str(HERE / 'manifest.json'), '.'),
    (str(HERE / 'installer_gui.py'), '.'),
    (str(HERE / 'plugins'), 'plugins'),
]
if (HERE / 'assets').exists():
    datas.append((str(HERE / 'assets'), 'assets'))

icon = str(HERE / 'assets' / 'spellcaster.icns') if (HERE / 'assets' / 'spellcaster.icns').exists() else None

a = Analysis(
    [str(HERE / 'install.py')],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=['tkinter', 'tkinter.scrolledtext', 'tkinter.ttk', 'installer_gui', 'customtkinter', 'PIL', 'requests'],
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
    name='Spellcaster Installer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX not recommended on macOS
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # Windowed — opens Terminal via .app
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,   # Set to 'x86_64' or 'arm64' for targeted build
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

app = BUNDLE(
    exe,
    name='Spellcaster Installer.app',
    icon=icon,
    bundle_identifier='com.laboratoiresonore.spellcaster',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleDisplayName': 'Spellcaster Installer',
        'NSRequiresAquaSystemAppearance': False,
    },
)
