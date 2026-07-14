"""Compatibility tests for the Bridge v2 Gmail entrypoint.

Main-checkout branch cleanup tests were intentionally replaced: Core no longer
checks out, resets, or cleans the registered repository. Equivalent safety
coverage lives in tests/test_worktrees.py and tests/test_git_history.py.
"""

import importlib.util
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "bridge_v2", Path(__file__).with_name("bridge_v2.py")
)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(bridge)


class GmailBodyTests(unittest.TestCase):
    def test_sender_has_no_personal_source_default(self):
        self.assertEqual(bridge.DEFAULT_ALLOWED_SENDER, "")

    def test_plain_text_body_is_decoded(self):
        import base64

        body = '{"type":"codex"}'
        encoded = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
        self.assertEqual(
            bridge.extract_body({"mimeType": "text/plain", "body": {"data": encoded}}),
            body,
        )

    def test_html_body_is_stripped(self):
        import base64

        encoded = base64.urlsafe_b64encode(b"<p>task</p>").decode().rstrip("=")
        self.assertEqual(
            bridge.extract_body({"mimeType": "text/html", "body": {"data": encoded}}),
            "task",
        )


if __name__ == "__main__":
    unittest.main()
