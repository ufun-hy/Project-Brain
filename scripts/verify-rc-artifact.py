#!/usr/bin/env python3
"""Verify the Build 10 unsigned personal artifact without trusting manifest paths."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


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
    assert manifest["schema_version"] == 5
    assert manifest["artifact_classification"] == "unsigned_personal_build"
    assert manifest["distribution_eligible"] is False
    assert manifest["usage_scope"] == "personal_internal_only"
    assert manifest["signing_status"] == "unsigned_personal_build"
    assert manifest["notarization_status"] == "deferred_personal_use"
    assert manifest["external_acceptance"] == "pending_user_credentials_and_actions"
    assert manifest["app"]["build"] == "10"
    assert manifest["app"]["version"] == "0.8.0"
    assert len(manifest["app"]["executable_sha256"]) == 64
    assert manifest["core_helper"]["version"] == "0.8.0"
    assert len(manifest["core_helper"]["sha256"]) == 64
    assert manifest["core_cli_contract"]["schema_version"] == 1
    assert manifest["core_cli_contract"]["contract_version"] == "1.2.0"
    assert manifest["core_cli_contract"]["core_version"] == "0.8.0"
    assert len(manifest["core_cli_contract"]["document_sha256"]) == 64
    assert manifest["local_task_contract"] == {
        "task_request_schema_version": 1,
        "confirmation_schema_version": 1,
        "result_schema_version": 1,
        "database_schema_version": 11,
        "transport": "stdin_json",
        "plan_token_prefix": "local-v2:",
        "plan_token_storage": "sha256_only",
        "confirm_fields": ["expected_plan_hash", "plan_token"],
    }
    assert manifest["tunnel_compatibility_manifest_version"] == 1
    assert manifest["supported_tunnel_client_versions"] == ["0.0.10"]
    assert manifest["release_gate"] == {
        "developer_id_signature": "deferred_personal_use",
        "hardened_runtime_build_setting": "enabled",
        "apple_notarization": "deferred_personal_use",
        "app_ticket_stapled": "deferred_personal_use",
        "dmg_ticket_stapled": "deferred_personal_use",
        "fresh_mac_public_distribution_acceptance": "deferred_personal_use",
        "personal_gatekeeper_authorization": "required_manual_per_artifact",
    }
    assert manifest["target_architecture"] == "arm64"
    assert len(manifest["git_head_sha"]) == 40
    assert manifest["ci_run_url"].startswith("https://github.com/")
    assert {entry["name"] for entry in manifest["artifacts"]} == {
        "Project-Brain-Build10-Personal-Unsigned-arm64.dmg",
        "Project-Brain-Build10-Personal-Unsigned-arm64.zip",
    }
    for entry in manifest["artifacts"]:
        name = entry["name"]
        assert name == Path(name).name
        artifact = (directory / name).resolve(strict=True)
        assert artifact.parent == directory
        assert sha256(artifact) == entry["sha256"]

    checksum_lines = (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    checksums = {}
    for line in checksum_lines:
        checksum, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        assert name == Path(name).name
        assert name not in checksums
        checksums[name] = checksum
    assert set(checksums) == {
        "Project-Brain-Build10-Personal-Unsigned-arm64.dmg",
        "Project-Brain-Build10-Personal-Unsigned-arm64.zip",
        "build-manifest.json",
    }
    for name, checksum in checksums.items():
        assert sha256(directory / name) == checksum

    archive = directory / "Project-Brain-Build10-Personal-Unsigned-arm64.zip"
    with zipfile.ZipFile(archive) as app_zip:
        app_prefix = "Project Brain.app/Contents/"
        executable = app_zip.read(app_prefix + "MacOS/Project Brain")
        helper = app_zip.read(app_prefix + "Resources/project-brain")
        contract_bytes = app_zip.read(
            app_prefix + "Resources/project-brain-cli-contract.json"
        )
    assert hashlib.sha256(executable).hexdigest() == manifest["app"]["executable_sha256"]
    assert hashlib.sha256(helper).hexdigest() == manifest["core_helper"]["sha256"]
    assert (
        hashlib.sha256(contract_bytes).hexdigest()
        == manifest["core_cli_contract"]["document_sha256"]
    )
    contract = json.loads(contract_bytes)
    assert contract["schema_version"] == manifest["core_cli_contract"]["schema_version"]
    assert contract["contract_version"] == manifest["core_cli_contract"]["contract_version"]
    assert contract["core_version"] == manifest["core_cli_contract"]["core_version"]
    rendered = manifest_path.read_text(encoding="utf-8").lower()
    for forbidden in ("runtime_api_key", "challenge_plaintext", "tunnel_id"):
        assert forbidden not in rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    verify(arguments.directory)
    print("Build 10 unsigned personal manifest and SHA-256 verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
