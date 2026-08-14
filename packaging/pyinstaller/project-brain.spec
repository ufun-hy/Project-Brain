import json
import os
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


root = Path(SPECPATH).parents[1]
build_sha = os.environ.get("PROJECT_BRAIN_BUILD_SHA", "")
if (
    len(build_sha) != 40
    or any(character not in "0123456789abcdef" for character in build_sha)
):
    raise SystemExit("PROJECT_BRAIN_BUILD_SHA must be the exact lowercase Git SHA")
build_info = (
    Path(tempfile.mkdtemp(prefix="project-brain-build-info-")) / "build-info.json"
)
build_info.write_text(
    json.dumps({"build_sha": build_sha}, sort_keys=True) + "\n",
    encoding="utf-8",
)
datas, binaries, hiddenimports = collect_all(
    "mcp",
    filter_submodules=lambda name: not name.startswith("mcp.cli"),
)
datas.append((str(root / "src" / "project_brain" / "cli_contract.json"), "project_brain"))
datas.append((str(build_info), "project_brain"))

analysis = Analysis(
    [str(root / "packaging" / "pyinstaller" / "entrypoint.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mcp.cli", "pkg_resources", "setuptools"],
    noarchive=False,
    optimize=1,
)
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="project-brain",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
