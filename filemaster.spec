# -*- mode: python ; coding: utf-8 -*-
# === 文件路径: filemaster.spec ===

import sys
from PyInstaller.utils.hooks import collect_submodules

# ==========================================
# 1. 分析阶段 (Analysis)
# ==========================================
a = Analysis(
    ['main.py'],             # 入口文件
    pathex=[],               # 额外的搜索路径
    binaries=[],             # 不需要额外的二进制 dll/so 文件
    datas=[],                # 不需要打包额外的静态资源(如图片/配置文件)
    hiddenimports=[
        # 显式声明 send2trash 的底层依赖，防止打包后删除功能失效
        'numpy', 'cv2',
        'secrets',
        'send2trash',
        'send2trash.plat_other',
        'send2trash.plat_gio',
        'send2trash.plat_win',
        'send2trash.plat_osx',
        # PySide6 相关的隐藏依赖
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtNetwork', # send2trash 在部分 Linux 环境下可能需要
    ] + collect_submodules('send2trash'), # 自动收集 send2trash 的所有子模块
    
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除未使用的庞大库，大幅减小打包体积
        'tkinter', '_tkinter', 'tk',
        'matplotlib', 'pandas',
        'scipy', 'PIL', 'IPython', 'jupyter',
        'pytest', 'unittest'
    ],
    noarchive=False,
    optimize=0,
)

# ==========================================
# 2. 字节码打包阶段 (PYZ)
# ==========================================
pyz = PYZ(a.pure)

# ==========================================
# 3. 可执行文件生成阶段 (EXE)
# ==========================================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FileMaster',       # 最终生成的 exe 文件名
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,             # 如果 cross-compile 可开启，Windows 下建议 False
    upx=True,                # 使用 UPX 压缩文件体积 (需提前安装 UPX)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # ⚠️ 核心：False 表示不显示黑框控制台 (GUI 模式)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',               # 如果有 .ico 图标文件，请在此填写路径，如 icon='icon.ico'
)

# ==========================================
# 4. 目录收集阶段 (COLLECT) - onedir 模式专属
# ==========================================
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FileMaster',       # 最终输出的文件夹名称
)