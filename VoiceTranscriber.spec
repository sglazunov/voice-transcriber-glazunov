# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the desktop build (onedir).

Bundles the FastAPI app, its template, and the native ML stack
(faster-whisper / ctranslate2 / onnxruntime / PyAV) into dist/VoiceTranscriber/.
Build with:  build_desktop.bat   (or: pyinstaller --noconfirm VoiceTranscriber.spec)
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Native / data-heavy packages: pull their dynamic libs and data files.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "av"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Frameworks with dynamic imports PyInstaller can miss.
for pkg in ("uvicorn", "anyio", "starlette", "webview"):
    hiddenimports += collect_submodules(pkg)

# Our application package (backend + HTML template).
datas += [("app", "app")]
hiddenimports += [
    "app.main", "app.jobs", "app.transcribe", "app.analyze", "app.llm",
    "app.docx_export", "app.formats", "app.glossary", "app.config",
    # lazily-imported optional deps
    "docx", "anthropic",
]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceTranscriber",
    console=False,            # GUI app — no console window
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="VoiceTranscriber",
)
