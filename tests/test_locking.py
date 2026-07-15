from __future__ import annotations

import multiprocessing
import unittest

from project_brain.errors import AlreadyRunningError
from project_brain.locking import RuntimeLock

from tests.helpers import CoreFixture


class RuntimeLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CoreFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_second_lock_holder_is_rejected(self) -> None:
        first = RuntimeLock(self.fixture.runtime.lock_file).acquire()
        try:
            with self.assertRaises(AlreadyRunningError):
                RuntimeLock(self.fixture.runtime.lock_file).acquire()
            self.assertFalse(RuntimeLock.is_available(self.fixture.runtime.lock_file))
        finally:
            first.release()
        self.assertTrue(RuntimeLock.is_available(self.fixture.runtime.lock_file))

    def test_lock_file_is_metadata_not_liveness_proof(self) -> None:
        with RuntimeLock(self.fixture.runtime.lock_file):
            self.assertEqual(
                RuntimeLock(self.fixture.runtime.lock_file).metadata()["status"], "running"
            )
        metadata = RuntimeLock(self.fixture.runtime.lock_file).metadata()
        self.assertEqual(metadata["status"], "released")
        self.assertTrue(RuntimeLock.is_available(self.fixture.runtime.lock_file))


if __name__ == "__main__":
    unittest.main()
