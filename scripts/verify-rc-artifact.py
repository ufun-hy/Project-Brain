#!/usr/bin/env python3
"""Verify an RFC-007 RC artifact manifest without trusting paths from it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(directory: Path) -> None:
    directory = directory.resolve(strict=True)
    manifest_path = directory / "build-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["artifact_classification"] == "unsigned_internal_rc"
    assert manifest["signing_status"] == "unsigned_internal_rc"
    assert manifest["notarization_status"] == "not_notarized"
    assert manifest["external_acceptance"] == "pending_user_credentials_and_actions"
    assert manifest["app"] == {"build": "1", "version": "0.7.0"}
    assert manifest["core_helper"]["version"] == "0.7.0"
    assert manifest["tunnel_compatibility_manifest_version"] == 1
    assert manifest["supported_tunnel_client_versions"] == ["0.0.10"]
    assert manifest["target_architecture"] == "arm64"
    assert len(manifest["git_head_sha"]) == 40
    assert manifest["ci_run_url"].startswith("https://github.com/")
    assert {entry["name"] for entry in manifest["artifacts"]} == {
        "Project-Brain-RC1-arm64.dmg",
        "Project-Brain-RC1-arm64.zip",
    }
    for entry in manifest["artifacts"]:
        name = entry["name"]
        assert name == Path(name).name
        artifact = (directory / name).resolve(strict=True)
        assert artifact.parent == directory
        assert sha256(artifact) == entry["sha256"]
    rendered = manifest_path.read_text(encoding="utf-8").lower()
    for forbidden in ("runtime_api_key", "challenge_plaintext", "tunnel_id"):
        assert forbidden not in rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    verify(arguments.directory)
    print("RC1 artifact manifest and SHA-256 verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
