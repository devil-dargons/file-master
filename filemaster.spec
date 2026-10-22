# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 代码以 Path(__file__).parent 读取的资源，必须保持源码目录结构打进包里
    datas=[
        ('src/ui/themes/dark.qss', 'src/ui/themes'),
        ('src/ui/themes/light.qss', 'src/ui/themes'),
        ('src/db/migrations/001_init.sql', 'src/db/migrations'),
        ('src/db/migrations/002_v2.sql', 'src/db/migrations'),
    ],
    hiddenimports=[],
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
    name='FileMaster',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
