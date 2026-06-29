# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file — 完整版打包（所有模块）
"""

import os

block_cipher = None
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(SPEC_DIR, 'Project_zjt_3.5.8.py')],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=[
        (os.path.join(SPEC_DIR, '.config', '*.json'), '.config'),
        (os.path.join(SPEC_DIR, 'template'), 'template'),
        (os.path.join(SPEC_DIR, 'ChinaCitys.json'), '.'),
        (os.path.join(SPEC_DIR, 'User', 'RuntimeState'), 'User/RuntimeState'),
        (os.path.join(SPEC_DIR, 'echarts'), 'echarts'),
        (os.path.join(SPEC_DIR, 'univer'), 'univer'),
    ],
    hiddenimports=[
        'comtypes',
        'comtypes.client',
        'openpyxl',
        'certifi',
        'psutil',
        'requests',
        'urllib3',
        'qfluentwidgets',
        'file_generation',
        'order_to_contract',
        'file_mover',
        'pdf_watermark',
        'object_query',
        'bi_dashboard',
        'department',
        'spreadsheet_page',
        'custom_report',
        'common',
        'core',
        'auth',
        'network',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='数据批量处理工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
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
    name='数据批量处理工具',
)
