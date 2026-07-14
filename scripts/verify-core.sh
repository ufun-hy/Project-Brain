#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"

PYTHONPATH=src "$PYTHON_BIN" -m compileall -q src tests
PYTHONPATH=src "$PYTHON_BIN" -m unittest discover -s tests -v
bash -n scripts/verify-core.sh
"$PYTHON_BIN" -c 'import json; json.load(open("config/project-brain.example.json", encoding="utf-8"))'
"$PYTHON_BIN" -c 'import pathlib; data=pathlib.Path("pyproject.toml").read_bytes();
try:
 import tomllib
except ModuleNotFoundError:
 from pip._vendor import tomli as tomllib
tomllib.loads(data.decode())'
