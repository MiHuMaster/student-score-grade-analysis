# PyInstaller onedir: no project directory is recursively copied.
import sys
from pathlib import Path
root = Path(SPECPATH)
sys.path.insert(0, str(root / "release"))
from manifest import datas
from audit import audit_sources
audit_sources()

a = Analysis(
    [str(root / "run.py")], pathex=[str(root)], binaries=[], datas=datas(),
    hiddenimports=[], hookspath=[], runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest", "app.services.demo", "supabase", "flask_session", "docx", "cryptography", "OpenSSL", "cffi"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="StudentScoreAnalysis",
    debug=False, strip=False, upx=False, console=False,
    icon=str(root / "release" / "app.ico"),
    version=str(root / "release" / "version.txt"),
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="StudentScoreAnalysis")
