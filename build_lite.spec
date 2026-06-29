# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file — 精简版打包（5个功能模块）
保留：文件生成、订单转合同（含招投标授权）、文件移动、设置
排除：自定义报表、PDF水印、对象查询、BI报表、部门员工、电子表格
"""

import os

block_cipher = None
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(SPEC_DIR, 'Project_zjt_3.5.8.py')],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=[
        # 配置文件
        (os.path.join(SPEC_DIR, '.config', '*.json'), '.config'),
        # 合同模板（整个目录）
        (os.path.join(SPEC_DIR, 'template'), 'template'),
        # 城市数据
        (os.path.join(SPEC_DIR, 'ChinaCitys.json'), '.'),
        # 用户运行时状态目录（空目录结构）
        (os.path.join(SPEC_DIR, 'User', 'RuntimeState'), 'User/RuntimeState'),
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
        # 保留的 mixin 模块（动态导入，PyInstaller 无法自动检测）
        'file_generation',
        'order_to_contract',
        'file_mover',
        'common',
        'core',
        'auth',
        'network',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除未使用的 mixin 模块
        'custom_report',
        '_diag_populate',
        'pdf_watermark',
        'object_query',
        'bi_dashboard',
        'department',
        'spreadsheet_page',
        # 排除 WebEngine（仅 BI 报表和电子表格需要）
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebEngine',
        'PyQt6.QtWebChannel',
        # 排除不需要的大型库
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'tkinter',
    ],
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
    console=False,          # 不弹控制台窗口
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
