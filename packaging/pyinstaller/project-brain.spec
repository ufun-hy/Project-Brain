from pathlib import Path

from PyInstaller.utils.hooks import collect_all


root = Path(SPECPATH).parents[1]
datas, binaries, hiddenimports = collect_all(
    "mcp",
    filter_submodules=lambda name: not name.startswith("mcp.cli"),
)
datas.append((str(root / "src" / "project_brain" / "cli_contract.json"), "project_brain"))

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
