from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lda_hm.hmz_relay import _persist_role_traces
from lda_hm.sandbox import SandboxResult


class TraceSandbox:
    def __init__(self) -> None:
        self.contents = {
            "drafter-a1.jsonl": '{"type":"turn.completed"}\n',
            "analyst-b2.jsonl": '{"type":"item.completed"}\n',
        }

    def run(self, command, *, timeout_seconds=900):
        if command[0] == "find":
            stdout = "\n".join((*self.contents, "../outside.jsonl")) + "\n"
        else:
            stdout = self.contents.get(Path(command[-1]).name, "")
        return SandboxResult(tuple(command), 0, stdout, "", 0.0, "fake-e2b")


class RelayTracePersistenceTest(unittest.TestCase):
    def test_persists_all_safe_role_traces_without_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sandbox = TraceSandbox()
            _persist_role_traces(sandbox, root, "run-001", "drafter-a1")
            traces = root / "runs/run-001/raw-traces"
            self.assertEqual(
                (traces / "drafter-a1.jsonl").read_text(),
                sandbox.contents["drafter-a1.jsonl"],
            )
            self.assertEqual(
                (traces / "analyst-b2.jsonl").read_text(),
                sandbox.contents["analyst-b2.jsonl"],
            )
            self.assertFalse((root / "runs/run-001/outside.jsonl").exists())

    def test_rejects_unsafe_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _persist_role_traces(TraceSandbox(), root, "../outside", "drafter-a1")
            self.assertFalse((root / "outside").exists())


if __name__ == "__main__":
    unittest.main()
