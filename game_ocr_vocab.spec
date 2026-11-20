# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: onedir 免安装文件夹，含词典与 OCR 模型。"""
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("data/dict.db", "data"),
]
datas += collect_data_files("rapidocr")  # config.yaml + models/*.onnx

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=["dxcam", "comtypes"],
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtPrintSupport",
        "PySide6.QtNetworkAuth",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "tkinter",
        "matplotlib",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="游戏单词助手",
    icon="app.ico",
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="game_ocr_vocab",
)
