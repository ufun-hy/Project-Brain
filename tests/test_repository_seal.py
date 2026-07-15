from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from project_brain.engine import TaskEngine
from project_brain.errors import TaskHistoryError
from project_brain.models import TaskStatus
from project_brain.repository import RepositorySeal, actual_origin, normalize_remote
from project_brain.worktrees import WorktreeManager

from tests.helpers import CoreFixture, create_remote_clone, git


class RepositorySealTests(unittest.TestCase):
    def test_verification_git_mutations_block_publication_and_preserve_main(self) -> None:
        for mutation in (
            "file",
            "commit",
            "branch",
            "origin",
            "default_ref",
        ):
            with self.subTest(mutation=mutation):
                fixture = CoreFixture()
                try:
                    repo, remote = create_remote_clone(fixture.root, f"seal-{mutation}")
                    if mutation == "file":
                        code = "from pathlib import Path; Path('mutation.txt').write_text('bad')"
                    elif mutation == "commit":
                        code = (
                            "from pathlib import Path; import subprocess; "
                            "Path('mutation.txt').write_text('bad'); "
                            "subprocess.run(['git','add','.'],check=True); "
                            "subprocess.run(['git','commit','-m','verification mutation'],check=True)"
                        )
                    elif mutation == "branch":
                        code = (
                            "import subprocess; "
                            "subprocess.run(['git','checkout','-b','verification-mutant'],check=True)"
                        )
                    elif mutation == "origin":
                        changed_remote = fixture.root / "untrusted.git"
                        code = (
                            "import subprocess; "
                            f"subprocess.run(['git','remote','set-url','origin',{str(changed_remote)!r}],check=True)"
                        )
                    else:
                        code = (
                            "import subprocess; "
                            "subprocess.run(['git','update-ref','refs/remotes/origin/main','HEAD'],check=True)"
                        )
                    fixture.add_project(
                        repo_path=str(repo),
                        remote_url=str(remote),
                        verification_commands=[
                            {
                                "id": f"mutate-{mutation}",
                                "text": f"Attempt {mutation} mutation",
                                "command": [sys.executable, "-c", code],
                                "always_run": True,
                            }
                        ],
                        auto_push=True,
                        auto_pr=False,
                    )
                    human = repo / "human.txt"
                    human.write_text("unchanged\n", encoding="utf-8")
                    main_head = git(repo, "rev-parse", "HEAD").stdout.strip()
                    main_status = git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout
                    fixture.add_task(
                        f"seal-{mutation}",
                        task_type="write_files",
                        payload={
                            "files": [{"path": "result.txt", "content": "canonical\n"}],
                            "commit_message": "canonical",
                        },
                    )
                    publisher = Mock()
                    publisher.publish.return_value = {"pushed": True, "pr_url": None}
                    result = TaskEngine(
                        fixture.store,
                        fixture.runtime,
                        github=publisher,
                    ).apply_once()
                    self.assertEqual(result["status"], TaskStatus.FAILED.value)
                    self.assertIn("publication blocked", result["task"]["last_error"])
                    publisher.publish.assert_not_called()
                    self.assertEqual(git(repo, "rev-parse", "HEAD").stdout.strip(), main_head)
                    self.assertEqual(
                        git(repo, "rev-parse", "refs/heads/main").stdout.strip(),
                        main_head,
                    )
                    self.assertEqual(
                        git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout,
                        main_status,
                    )
                    self.assertEqual(human.read_text(encoding="utf-8"), "unchanged\n")
                    self.assertEqual(
                        normalize_remote(actual_origin(repo)), normalize_remote(str(remote))
                    )
                    self.assertEqual(fixture.store.get_worktree(f"seal-{mutation}")["status"], "active")
                finally:
                    fixture.close()

    def test_local_default_branch_advance_blocks_publication_without_rewind(self) -> None:
        fixture = CoreFixture()
        try:
            repo, remote = create_remote_clone(fixture.root, "seal-concurrent-main")
            project = fixture.add_project(
                repo_path=str(repo),
                remote_url=str(remote),
                auto_push=True,
                auto_pr=False,
            )
            fixture.add_task("seal-concurrent-main")
            task = fixture.store.claim_next()
            record = WorktreeManager(fixture.store, fixture.runtime).create(task, project)
            worktree = Path(record["path"])
            captured = git(worktree, "rev-parse", "HEAD").stdout.strip()
            seal = RepositorySeal.capture(
                worktree,
                project=project,
                expected_branch=record["branch"],
                expected_head=captured,
            )

            (repo / "human.txt").write_text("legitimate concurrent change\n", encoding="utf-8")
            git(repo, "add", "human.txt")
            git(repo, "commit", "-m", "human advances main")
            human_tip = git(repo, "rev-parse", "refs/heads/main").stdout.strip()
            self.assertNotEqual(human_tip, captured)

            with self.assertRaisesRegex(TaskHistoryError, "local default branch ref changed"):
                seal.verify(worktree, project=project)

            self.assertEqual(
                git(repo, "rev-parse", "refs/heads/main").stdout.strip(), human_tip
            )
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
