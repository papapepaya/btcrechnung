# -*- mode: python ; coding: utf-8 -*-
# BTCRechnung PyInstaller Spec
# Build: pyinstaller BTCRechnung.spec

import os
import pathlib
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

PROJECT_ROOT = os.path.abspath(os.getcwd())

# Alle xhtml2pdf Submodule sammeln
xhtml2pdf_hidden = collect_submodules('xhtml2pdf')
xhtml2pdf_data = collect_data_files('xhtml2pdf')

# reportlab Submodule
reportlab_hidden = collect_submodules('reportlab')

# lxml
lxml_hidden = collect_submodules('lxml')

# bip_utils
bip_utils_hidden = collect_submodules('bip_utils')

# facturx
facturx_hidden = collect_submodules('facturx')

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'run.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=[
        (os.path.join(PROJECT_ROOT, 'app', 'templates'), 'app/templates'),
        (os.path.join(PROJECT_ROOT, 'app', 'static'), 'app/static'),
        (os.path.join(PROJECT_ROOT, 'docs'), 'docs'),
        (os.path.join(PROJECT_ROOT, 'Bitcoin.svg'), '.'),
        (os.path.join(PROJECT_ROOT, 'Bitcoin.png'), '.'),
    ] + xhtml2pdf_data + collect_data_files('bip_utils'),
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.middleware.sessions',
        'starlette.staticfiles',
        'multipart',
        'jinja2.ext',
        'qrcode.image.pil',
        'coincurve',
        'coincurve._cffi_backend',
        'cffi',
        '_cffi_backend',
        'app',
        'app.main',
        'app.bookkeeping',
        'app.zugferd',
        'app.models',
    ] + xhtml2pdf_hidden + reportlab_hidden + lxml_hidden + bip_utils_hidden + facturx_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL.ImageTk',
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
    name='BTCRechnung',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BTCRechnung',
)
