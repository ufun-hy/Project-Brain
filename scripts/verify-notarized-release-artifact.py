#!/usr/bin/env python3
"""Verify Build 10 notarized release-candidate files and manifest bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid
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
    assert (
        manifest["artifact_classification"]
        == "developer_id_notarized_release_candidate"
    )
    assert manifest["distribution_eligible"] is False
    assert manifest["app"]["version"] == "0.8.0"
    assert manifest["app"]["build"] == "10"
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["git_head_sha"])
    assert manifest["target_architecture"] == "arm64"
    assert manifest["core_helper"]["version"] == "0.8.0"
    assert manifest["core_cli_contract"] == {
        "schema_version": 1,
        "contract_version": "1.2.0",
        "core_version": "0.8.0",
        "document_sha256": manifest["core_cli_contract"]["document_sha256"],
    }
    assert len(manifest["core_cli_contract"]["document_sha256"]) == 64
    assert manifest["signing"]["status"] == "developer_id_application_verified"
    assert manifest["signing"]["identity"].startswith("Developer ID Application:")
    assert re.fullmatch(r"[A-Z0-9]{10}", manifest["signing"]["team_id"])
    assert manifest["signing"]["identity"].endswith(
        f" ({manifest['signing']['team_id']})"
    )
    assert manifest["signing"]["hardened_runtime"] == "enabled"
    assert manifest["signing"]["secure_timestamp"] == "verified"
    assert manifest["signing"]["get_task_allow"] == "absent"
    assert manifest["notarization"]["status"] == "accepted"
    uuid.UUID(manifest["notarization"]["app_submission_id"])
    uuid.UUID(manifest["notarization"]["dmg_submission_id"])
    assert manifest["notarization"]["app_ticket"] == "stapled_and_validated"
    assert manifest["notarization"]["dmg_ticket"] == "stapled_and_validated"
    assert manifest["release_gate"] == {
        "developer_id_signature": "passed",
        "hardened_runtime": "passed",
        "secure_timestamp": "passed",
        "apple_notarization": "passed",
        "app_ticket_stapled": "passed",
        "dmg_ticket_stapled": "passed",
        "gatekeeper_assessment": "passed_ci",
        "fresh_mac_quarantine_acceptance": "pending_manual",
    }
    assert manifest["external_acceptance"] == "pending_user_credentials_and_actions"
    assert manifest["ci_run_url"].startswith(
        "https://github.com/ufun-hy/Project-Brain/actions/runs/"
    )

    expected_names = {
        "Project-Brain-Build10-arm64.dmg",
        "Project-Brain-Build10-arm64.zip",
        "app-notarization.json",
        "dmg-notarization.json",
    }
    assert {entry["name"] for entry in manifest["artifacts"]} == expected_names
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
    assert set(checksums) == expected_names | {"build-manifest.json"}
    for name, checksum in checksums.items():
        assert sha256(directory / name) == checksum

    for receipt_name, target, submission_key in (
        ("app-notarization.json", "app", "app_submission_id"),
        ("dmg-notarization.json", "dmg", "dmg_submission_id"),
    ):
        receipt = json.loads((directory / receipt_name).read_text(encoding="utf-8"))
        assert receipt == {
            "schema_version": 1,
            "status": "Accepted",
            "submission_id": manifest["notarization"][submission_key],
            "target": target,
        }

    archive = directory / "Project-Brain-Build10-arm64.zip"
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
    for forbidden in (
        "private_key",
        "p12_password",
        "notary_key",
        "runtime_api_key",
        "challenge_plaintext",
        "tunnel_id",
    ):
        assert forbidden not in rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    verify(arguments.directory)
    print("Build 10 notarized release-candidate manifest verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
