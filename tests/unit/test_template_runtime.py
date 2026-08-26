from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lda.agents.factory import AgentFactory
from lda.cli.main import _run
from lda.config.templates import TemplateAliases
from lda.controller.protocol import ControllerProtocol
from lda.e2b.client import E2BClient
from lda.e2b.preflight import Preflight
from lda.judge.canary import CleanCanaryJudge
from lda.research.qualification import QualificationRunner
from lda.templates import TEMPLATES, build_templates


CUSTOM = TemplateAliases(
    controller="private-controller-v1",
    agent_runtime="private-agent-v2",
    base="private-base-v3",
    judge="private-judge-v4",
    e2e="private-e2e-v5",
)


class RecordingClient(E2BClient):
    def __init__(self):
        super().__init__(fake=True)
        self.created: list[dict[str, str]] = []

    def create(self, metadata):
        self.created.append(dict(metadata))
        return super().create(metadata)


class TemplateRuntimeTest(unittest.TestCase):
    def test_private_yaml_resolves_only_template_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "lda.yaml"
            config.write_text(
                "e2b:\n  api_key: super-secret\n"
                "templates:\n"
                "  controller: private-controller-v1\n"
                "  agent_runtime: 'private-agent-v2'\n"
                "  base: private-base-v3\n"
                "  judge: private-judge-v4\n"
                "  e2e: private-e2e-v5\n"
                "benchmark:\n  samples: 30\n",
                encoding="utf-8",
            )
            aliases = TemplateAliases.from_file(config)
        self.assertEqual(aliases, CUSTOM)
        self.assertNotIn("secret", repr(aliases.as_dict()).lower())
        self.assertEqual(TemplateAliases.from_file("/missing/config.yaml"), TemplateAliases())

    def test_aliases_reach_controller_agents_qualification_and_judge(self):
        client = RecordingClient()
        factory = AgentFactory(client, templates=CUSTOM)
        spec = factory.spec(run_id="r", role="Builder")
        self.assertEqual(spec.runtime_template, CUSTOM.agent_runtime)
        self.assertEqual(QualificationRunner(client, templates=CUSTOM).base_template, CUSTOM.base)
        self.assertEqual(CleanCanaryJudge(client, templates=CUSTOM).templates.judge, CUSTOM.judge)
        with tempfile.TemporaryDirectory() as tmp:
            protocol = ControllerProtocol(tmp, client, repository_root=tmp, template_aliases=CUSTOM)
            controller = protocol._create_controller("r")
        self.assertEqual(controller.metadata["template"], CUSTOM.controller)

    def test_build_manifests_use_all_configured_aliases(self):
        observed = {}

        def publish(path, manifest):
            observed[manifest["name"]] = dict(manifest)
            return "built"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = Path(__file__).resolve().parents[2] / "e2b_templates"
            for name in TEMPLATES:
                target = root / "e2b_templates" / name
                target.mkdir(parents=True)
                (target / "Dockerfile").write_bytes((source / name / "Dockerfile").read_bytes())
            build_templates(root, publisher=publish, aliases=CUSTOM)

        self.assertEqual(set(observed), set(TEMPLATES))
        for name, manifest in observed.items():
            self.assertEqual(manifest["alias"], CUSTOM.alias_for(name))
            self.assertEqual(len(manifest["spec_hash"]), 64)

    def test_preflight_validates_all_five_template_manifests_offline(self):
        client = RecordingClient()
        result = Preflight(client, CUSTOM).run("template-preflight")
        self.assertTrue(result["passed"], result)
        details = result["details"]["template_manifests"]
        self.assertEqual(set(details), set(TEMPLATES))
        self.assertTrue(all(item["valid"] for item in details.values()))
        checked = {item["mission_id"]: item["template"] for item in client.created
                   if item.get("role") == "template-check"}
        self.assertEqual(checked, {name: CUSTOM.alias_for(name) for name in TEMPLATES})

    @patch("lda.cli.main.ControllerProtocol")
    @patch("lda.cli.main.prepare_campaign")
    @patch("lda.cli.main.Preflight.run")
    @patch("lda.cli.main.build_templates")
    @patch("lda.cli.main._template_aliases", return_value=CUSTOM)
    @patch("lda.cli.main._client")
    def test_run_builds_or_reuses_templates_before_preflight(
            self, client_factory, _aliases, build, preflight, prepare, protocol_type):
        order = []
        client_factory.return_value = SimpleNamespace(fake=False)
        build.side_effect = lambda *args, **kwargs: order.append("build") or list(TEMPLATES)
        preflight.side_effect = lambda *args, **kwargs: order.append("preflight") or {
            "passed": True, "checks": {}}
        prepare.return_value = SimpleNamespace(dump=lambda: {"filename": "campaign.md"})
        protocol_type.return_value.start.return_value = {"run_id": "r"}
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "campaign.md"
            campaign.write_text("evidence", encoding="utf-8")
            result = _run(SimpleNamespace(
                root=tmp, run_id="r", campaign_input=str(campaign), fake_e2b=False,
                e2b_template=None, allow_agent_stub=False,
            ))
        self.assertEqual(order, ["build", "preflight"])
        self.assertEqual(result["templates"], list(TEMPLATES))
        self.assertIs(protocol_type.call_args.kwargs["template_aliases"], CUSTOM)

    def test_agent_runtime_uses_pinned_standalone_codex_and_intel_skills(self):
        dockerfile = (Path(__file__).resolve().parents[2] /
                      "e2b_templates/lda-agent-runtime/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ARG CODEX_RELEASE=0.149.1", dockerfile)
        self.assertIn("https://chatgpt.com/codex/install.sh", dockerfile)
        self.assertIn("codex --version", dockerfile)
        self.assertNotIn("npm install", dockerfile)
        self.assertIn("e9d0b6410fb1ad7a50fb81e0868fd23ae886882c", dockerfile)
        self.assertIn("agent-runtime-versions.json", dockerfile)


if __name__ == "__main__":
    unittest.main()
