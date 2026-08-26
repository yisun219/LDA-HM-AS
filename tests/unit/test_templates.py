import json
import tempfile
import unittest
from pathlib import Path

from lda.templates import TEMPLATES, build_templates


class TemplateBuildTest(unittest.TestCase):
    def test_all_templates_are_versioned_and_published(self):
        calls = []

        def publish(path, manifest):
            self.assertTrue((path / "Dockerfile").is_file())
            calls.append((path.name, manifest))
            return "built"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = Path(__file__).resolve().parents[2] / "e2b_templates"
            for name in TEMPLATES:
                target = root / "e2b_templates" / name
                target.mkdir(parents=True)
                (target / "Dockerfile").write_bytes((source / name / "Dockerfile").read_bytes())
            built = build_templates(root, publisher=publish)

        self.assertEqual(built, list(TEMPLATES))
        self.assertEqual([name for name, _ in calls], list(TEMPLATES))
        for name, manifest in calls:
            self.assertEqual(manifest["version"], "2" if name == "lda-e2e" else "1")
            self.assertEqual(len(manifest["spec_hash"]), 64)

    def test_unknown_template_fails_before_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unknown template"):
                build_templates(tmp, ["unknown"], publisher=lambda *_: "built")
