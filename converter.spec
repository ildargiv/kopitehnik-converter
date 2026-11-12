# PyInstaller build: pyinstaller converter.spec
# Produces dist/Converter.exe (one file, no console).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

excluded = [
    "pymupdf.layout", "pymupdf4llm",
    "tkinter", "unittest", "pydoc", "IPython", "matplotlib",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
]

a = Analysis(
    ["app.py"],
    pathex=["."],
    datas=[("assets/icon.png", "assets"), ("assets/ocr_models", "assets/ocr_models")] + collect_data_files("rapidocr"),
    hiddenimports=["PySide6.QtPdf", "PySide6.QtSvg", "PySide6.QtPrintSupport", "pillow_heif", "openpyxl", "pymupdf", "cv2", "onnxruntime", "shapely", "pyclipper", "omegaconf", "yaml"] + collect_submodules("rapidocr"),
    excludes=excluded,
    noarchive=False,
)
# Qt parts the app never uses (software OpenGL, QML/Quick, Direct2D platform).
DROP = ("opengl32sw.dll", "Qt6Quick", "Qt6Qml", "qdirect2d", "Qt6VirtualKeyboard", "qtvirtualkeyboard")
a.binaries = [b for b in a.binaries if not any(d.lower() in b[0].lower() for d in DROP)]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/").split("/")[1:2]]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Converter",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    disable_windowed_traceback=False,
)
