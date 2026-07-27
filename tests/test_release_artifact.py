from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NotarizedReleaseArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        verifier_path = root / "scripts/verify-notarized-release-artifact.py"
        spec = importlib.util.spec_from_file_location(
            "verify_notarized_release_artifact",
            verifier_path,
        )
        assert spec is not None and spec.loader is not None
        cls.verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.verifier)

    def create_fixture(self, directory: Path) -> None:
        executable = b"signed-app-executable"
        helper = b"signed-core-helper"
        contract = {
            "schema_version": 1,
            "contract_version": "1.2.0",
            "core_version": "0.8.0",
        }
        contract_bytes = json.dumps(contract, sort_keys=True).encode()
        archive = directory / "Project-Brain-Build10-arm64.zip"
        with zipfile.ZipFile(archive, "w") as app_zip:
            prefix = "Project Brain.app/Contents/"
            app_zip.writestr(prefix + "MacOS/Project Brain", executable)
            app_zip.writestr(prefix + "Resources/project-brain", helper)
            app_zip.writestr(
                prefix + "Resources/project-brain-cli-contract.json",
                contract_bytes,
            )
        (directory / "Project-Brain-Build10-arm64.dmg").write_bytes(
            b"signed-and-stapled-dmg"
        )

        app_submission = "11111111-1111-1111-1111-111111111111"
        dmg_submission = "22222222-2222-2222-2222-222222222222"
        for name, target, submission in (
            ("app-notarization.json", "app", app_submission),
            ("dmg-notarization.json", "dmg", dmg_submission),
        ):
            (directory / name).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "Accepted",
                        "submission_id": submission,
                        "target": target,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

        artifact_names = (
            "Project-Brain-Build10-arm64.dmg",
            "Project-Brain-Build10-arm64.zip",
            "app-notarization.json",
            "dmg-notarization.json",
        )
        manifest = {
            "schema_version": 5,
            "artifact_classification": "developer_id_notarized_release_candidate",
            "distribution_eligible": False,
            "app": {
                "version": "0.8.0",
                "build": "10",
                "executable_sha256": hashlib.sha256(executable).hexdigest(),
            },
            "git_head_sha": "a" * 40,
            "core_helper": {
                "version": "0.8.0",
                "sha256": hashlib.sha256(helper).hexdigest(),
            },
            "core_cli_contract": {
                "schema_version": 1,
                "contract_version": "1.2.0",
                "core_version": "0.8.0",
                "document_sha256": hashlib.sha256(contract_bytes).hexdigest(),
            },
            "target_architecture": "arm64",
            "signing": {
                "status": "developer_id_application_verified",
                "identity": "Developer ID Application: Example (EXAMPL1234)",
                "team_id": "EXAMPL1234",
                "hardened_runtime": "enabled",
                "secure_timestamp": "verified",
                "get_task_allow": "absent",
            },
            "notarization": {
                "status": "accepted",
                "app_submission_id": app_submission,
                "dmg_submission_id": dmg_submission,
                "app_ticket": "stapled_and_validated",
                "dmg_ticket": "stapled_and_validated",
            },
            "release_gate": {
                "developer_id_signature": "passed",
                "hardened_runtime": "passed",
                "secure_timestamp": "passed",
                "apple_notarization": "passed",
                "app_ticket_stapled": "passed",
                "dmg_ticket_stapled": "passed",
                "gatekeeper_assessment": "passed_ci",
                "fresh_mac_quarantine_acceptance": "pending_manual",
            },
            "ci_run_url": "https://github.com/ufun-hy/Project-Brain/actions/runs/1",
            "external_acceptance": "pending_user_credentials_and_actions",
            "artifacts": [
                {"name": name, "sha256": sha256(directory / name)}
                for name in artifact_names
            ],
        }
        manifest_path = directory / "build-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        checksum_names = artifact_names + ("build-manifest.json",)
        (directory / "SHA256SUMS").write_text(
            "".join(f"{sha256(directory / name)}  {name}\n" for name in checksum_names),
            encoding="utf-8",
        )

    def test_exact_manifest_receipts_zip_and_sums_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_fixture(directory)
            self.verifier.verify(directory)

    def test_tampered_final_dmg_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.create_fixture(directory)
            (directory / "Project-Brain-Build10-arm64.dmg").write_bytes(b"tampered")
            with self.assertRaises(AssertionError):
                self.verifier.verify(directory)


if __name__ == "__main__":
    unittest.main()
