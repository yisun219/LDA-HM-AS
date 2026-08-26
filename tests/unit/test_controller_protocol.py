from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lda.cli.main import _run, main
from lda.artifacts.store import ArtifactStore
from lda.controller.protocol import (CONFIG_PATH, REQUEST_PATH, RESPONSE_PATH,
                                     ControllerProtocol, ControllerProxyClient,
                                     ControllerRecord)
from lda.controller.runtime import run_controller
from lda.e2b.client import E2BClient
from lda.models import WorldState
from lda.state.store import EventStore


class ControllerProtocolTest(unittest.TestCase):
    def _repository(self, root: Path) -> Path:
        repository = root / "repo"
        module = repository / "src" / "lda"
        module.mkdir(parents=True)
        (module / "__init__.py").write_text("", encoding="utf-8")
        snapshot = repository / "source_snapshot" / "v1"
        snapshot.mkdir(parents=True)
        payload = b"pinned source"
        (snapshot / "source.dsc").write_bytes(payload)
        (snapshot / "SHA256SUMS").write_text(
            hashlib.sha256(payload).hexdigest() + "  source.dsc\n", encoding="utf-8")
        return repository

    def _protocol(self, root: str | Path, client: E2BClient, run_id: str = "r") -> ControllerProtocol:
        protocol = ControllerProtocol(root, client, repository_root=root)
        protocol._save_record(ControllerRecord(
            protocol_version=ControllerProtocol.VERSION,
            run_id=run_id,
            sandbox_id="controller-" + run_id,
            metadata={"project": "lda", "run_id": run_id, "role": "controller"},
        ))
        return protocol

    @staticmethod
    def _metadata(*, run_id: str = "r", role: str = "candidate-work",
                  template: str = "lda-base", lease_id: str = "lease-1") -> dict:
        return {
            "project": "lda", "run_id": run_id, "life_cycle": "1",
            "mission_id": "mission-1", "candidate_id": "candidate-1",
            "role": role, "template": template, "lease_id": lease_id,
        }

    def test_bridge_rejects_foreign_run_and_role_template_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            protocol = self._protocol(tmp, E2BClient(fake=True))
            with self.assertRaisesRegex(RuntimeError, "run_id"):
                protocol._dispatch({"op": "create", "args": {
                    "metadata": self._metadata(run_id="other")}})
            with self.assertRaisesRegex(RuntimeError, "role/template mismatch"):
                protocol._dispatch({"op": "create", "args": {
                    "metadata": self._metadata(role="Builder", template="lda-base")}})
            with self.assertRaisesRegex(RuntimeError, "role is not allowed"):
                protocol._dispatch({"op": "create", "args": {
                    "metadata": self._metadata(role="controller", template="lda-controller")}})
            incomplete = self._metadata()
            incomplete.pop("mission_id")
            with self.assertRaisesRegex(RuntimeError, "metadata is missing: mission_id"):
                protocol._dispatch({"op": "create", "args": {"metadata": incomplete}})

    def test_bridge_rejects_operations_on_unowned_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = E2BClient(fake=True)
            protocol = self._protocol(tmp, client)
            intruder = client.create(self._metadata(lease_id="unregistered"))
            requests = [
                {"op": "connect", "args": {"sandbox_id": intruder.sandbox_id}},
                {"op": "command", "args": {"sandbox_id": intruder.sandbox_id,
                                               "command": "true"}},
                {"op": "filesystem_read", "args": {"sandbox_id": intruder.sandbox_id,
                                                       "path": "/workspace/file"}},
                {"op": "filesystem_write", "args": {"sandbox_id": intruder.sandbox_id,
                                                        "path": "/workspace/file",
                                                        "content_base64": base64.b64encode(b"x").decode()}},
                {"op": "snapshot", "args": {"sandbox_id": intruder.sandbox_id}},
                {"op": "fork", "args": {"sandbox_id": intruder.sandbox_id,
                                            "metadata": self._metadata(lease_id="fork")}},
                {"op": "kill", "args": {"sandbox_id": intruder.sandbox_id}},
            ]
            for request in requests:
                with self.subTest(op=request["op"]), \
                        self.assertRaisesRegex(RuntimeError, "not owned"):
                    protocol._dispatch(request)

    def test_agent_runtime_rejects_env_probe_and_out_of_scope_filesystem(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = E2BClient(fake=True)
            protocol = self._protocol(tmp, client)
            metadata = self._metadata(role="Builder", template="lda-agent-runtime")
            created = protocol._dispatch({"op": "create", "args": {"metadata": metadata}})
            sandbox_id = created["sandbox_id"]
            with self.assertRaisesRegex(RuntimeError, "only codex exec"):
                protocol._dispatch({"op": "command", "args": {
                    "sandbox_id": sandbox_id, "metadata": metadata,
                    "command": "env"}})
            with self.assertRaisesRegex(RuntimeError, "limited to /workspace/lda/schemas"):
                protocol._dispatch({"op": "filesystem_read", "args": {
                    "sandbox_id": sandbox_id, "metadata": metadata,
                    "path": "/workspace/secret"}})
            written = protocol._dispatch({"op": "filesystem_write", "args": {
                "sandbox_id": sandbox_id, "metadata": metadata,
                "path": "/workspace/lda/schemas/builder.json",
                "content_base64": base64.b64encode(b"{}").decode()}})
            self.assertEqual(written["written"], 2)
            with patch.object(client, "agent_process_env", return_value={"OPENAI_API_KEY": "test"}):
                allowed = protocol._dispatch({"op": "command", "args": {
                    "sandbox_id": sandbox_id, "metadata": metadata,
                    "command": "codex exec --json work"}})
            self.assertEqual(allowed["exit_code"], 0)
            with self.assertRaisesRegex(RuntimeError, "forbidden execution mode"):
                protocol._dispatch({"op": "command", "args": {
                    "sandbox_id": sandbox_id, "metadata": metadata,
                    "command": "codex exec --yolo work"}})

    def test_persisted_lease_replay_returns_same_sandbox(self):
        class PersistentClient(E2BClient):
            remote = {}
            create_calls = 0

            def __init__(self):
                super().__init__(fake=True)

            def create(self, metadata):
                type(self).create_calls += 1
                sandbox = super().create(metadata)
                type(self).remote[sandbox.sandbox_id] = sandbox
                return sandbox

            def connect(self, sandbox_id):
                sandbox = type(self).remote.get(sandbox_id)
                if sandbox is None or not sandbox.alive:
                    raise RuntimeError("unknown sandbox")
                return sandbox

        with tempfile.TemporaryDirectory() as tmp:
            client = PersistentClient()
            metadata = self._metadata()
            first_protocol = self._protocol(tmp, client)
            first = first_protocol._dispatch({"op": "create", "args": {"metadata": metadata}})
            second_protocol = ControllerProtocol(tmp, PersistentClient(), repository_root=tmp)
            second = second_protocol._dispatch({"op": "create", "args": {"metadata": metadata}})
            self.assertEqual(first["sandbox_id"], second["sandbox_id"])
            self.assertEqual(PersistentClient.create_calls, 1)
            registry = json.loads(second_protocol.registry_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["leases"][metadata["lease_id"]], first["sandbox_id"])
            changed = dict(metadata, mission_id="different")
            with self.assertRaisesRegex(RuntimeError, "replay metadata does not match"):
                second_protocol._dispatch({"op": "create", "args": {"metadata": changed}})

    def test_reap_is_limited_to_active_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            protocol = self._protocol(tmp, E2BClient(fake=True))
            with self.assertRaisesRegex(RuntimeError, "only the active run"):
                protocol._dispatch({"op": "reap", "args": {"run_id": "other"}})

    def test_prepare_creates_secret_free_controller_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = E2BClient(fake=True)
            protocol = ControllerProtocol(root / "run", client, repository_root=self._repository(root))
            content = b"campaign evidence"
            campaign = {"filename": "campaign.md", "sha256": hashlib.sha256(content).hexdigest()}
            with patch.dict(os.environ, {"E2B_API_KEY": "controller-secret",
                                         "OPENAI_API_KEY": "model-secret"}, clear=False):
                controller = protocol.prepare(run_id="r", campaign=campaign, campaign_content=content)
            config = client.filesystem_read(controller, CONFIG_PATH)
            record = protocol.record_path.read_text(encoding="utf-8")
            registry = protocol.registry_path.read_text(encoding="utf-8")
            serialized = config + record + registry + json.dumps(controller.metadata)
            self.assertEqual(controller.metadata["role"], "controller")
            self.assertNotIn("controller-secret", serialized)
            self.assertNotIn("model-secret", serialized)
            self.assertNotIn("api_key", serialized.lower())
            artifact = client.filesystem_read_bytes(
                controller,
                "/workspace/lda-controller/run/.lda/artifacts/campaign-input/campaign.md")
            self.assertEqual(artifact, content)

    def test_prepare_fails_closed_when_remote_source_manifest_does_not_verify(self):
        class ManifestFailureClient(E2BClient):
            def command(self, sandbox, command, **kwargs):
                if "/source_snapshot/" in command and "sha256sum -c" in command:
                    return {"exit_code": 1, "stdout": "", "stderr": "mismatch"}
                return super().command(sandbox, command, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = ManifestFailureClient(fake=True)
            protocol = ControllerProtocol(root / "run", client, repository_root=self._repository(root))
            content = b"campaign evidence"
            campaign = {"filename": "campaign.md", "sha256": hashlib.sha256(content).hexdigest()}
            with self.assertRaisesRegex(RuntimeError, "source snapshot hash verification failed"):
                protocol.prepare(run_id="r", campaign=campaign, campaign_content=content)

    def test_bridge_codex_request_never_returns_model_secret(self):
        client = E2BClient(fake=True)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {"OPENAI_API_KEY": "model-secret",
                             "OPENAI_BASE_URL": "https://provider.invalid"}, clear=False):
            protocol = ControllerProtocol(tmp, client, repository_root=tmp)
            result = protocol._dispatch({"op": "codex_command", "args": {
                "prompt": "work", "model": "gpt-5", "reasoning_effort": "high"}})
        self.assertIn("OPENAI_API_KEY", result["command"])
        self.assertNotIn("model-secret", result["command"])
        self.assertIn("shell_environment_policy.exclude", result["command"])

    def test_proxy_serializes_only_structured_secret_free_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            response = Path(tmp) / "response.json"
            proxy = ControllerProxyClient(str(request), str(response), timeout_seconds=2)
            observed = {}

            def invoke():
                observed["command"] = proxy.codex_command("bounded task")

            thread = threading.Thread(target=invoke)
            thread.start()
            deadline = time.monotonic() + 1
            while not request.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            payload = json.loads(request.read_text(encoding="utf-8"))
            self.assertEqual(payload["op"], "codex_command")
            self.assertNotIn("api_key", json.dumps(payload).lower())
            response.write_text(json.dumps({"request_id": payload["request_id"], "ok": True,
                                            "result": {"command": "codex exec task"}}), encoding="utf-8")
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(observed["command"], "codex exec task")

    def test_reconnect_does_not_replay_a_request_with_matching_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = E2BClient(fake=True)
            controller = client.create({"project": "lda", "run_id": "r", "role": "controller",
                                        "lease_id": "controller-r"})
            protocol = ControllerProtocol(tmp, client, repository_root=tmp)
            protocol.controller = controller
            request = {"protocol_version": 1, "request_id": "op-1", "op": "reap",
                       "args": {"run_id": "r"}}
            response = {"protocol_version": 1, "request_id": "op-1", "ok": True,
                        "result": {"reaped": 0}}
            client.filesystem_write(controller, REQUEST_PATH, json.dumps(request))
            client.filesystem_write(controller, RESPONSE_PATH, json.dumps(response))
            with patch.object(protocol, "_dispatch") as dispatch:
                self.assertFalse(protocol.serve_once())
            dispatch.assert_not_called()

    @patch("lda.cli.main.ControllerProtocol")
    @patch("lda.cli.main.Preflight.run")
    def test_cli_run_delegates_supervisor_execution_to_controller(self, preflight, protocol_type):
        preflight.return_value = {"passed": True, "checks": {}}
        instance = protocol_type.return_value
        instance.start.return_value = {"run_id": "r", "controller_execution": "e2b-sandbox"}
        with tempfile.TemporaryDirectory() as tmp:
            campaign = Path(tmp) / "campaign.md"
            campaign.write_text("campaign", encoding="utf-8")
            args = SimpleNamespace(root=tmp, run_id="r", campaign_input=str(campaign),
                                   fake_e2b=True, e2b_template=None, allow_agent_stub=False)
            result = _run(args)
        instance.prepare.assert_called_once()
        instance.start.assert_called_once_with()
        self.assertEqual(result["controller_execution"], "e2b-sandbox")

    @patch("lda.cli.main.ControllerProtocol")
    def test_cli_resume_uses_controller_record_not_local_supervisor(self, protocol_type):
        protocol_type.return_value.resume.return_value = {"run_id": "r", "resumed": True}
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--root", tmp, "resume", "--run-id", "r", "--fake-e2b"])
        self.assertEqual(code, 0)
        protocol_type.return_value.resume.assert_called_once_with()

    def test_resume_fails_closed_without_controller_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "recovery record"):
                ControllerProtocol(tmp, E2BClient(fake=True)).resume()

    def test_state_sync_copies_content_addressed_controller_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = E2BClient(fake=True)
            controller = client.create({"project": "lda", "run_id": "r", "role": "controller",
                                        "lease_id": "controller-r"})
            protocol = ControllerProtocol(root, client, repository_root=root)
            protocol.controller = controller
            payload = b"candidate package"
            digest = hashlib.sha256(payload).hexdigest()
            ref = "sha256:" + digest
            remote_artifact = f"/workspace/lda-controller/run/.lda/artifacts/sha256/{digest[:2]}/{digest}"
            world = WorldState("r", candidates=[]).dump()
            world["portfolio_e2e"] = [{"evidence_refs": [ref]}]
            client.filesystem_write(controller, remote_artifact, payload)
            client.filesystem_write(
                controller, "/workspace/lda-controller/run/.lda/world.json",
                json.dumps(world))
            protocol._sync_state()
            self.assertEqual(ArtifactStore(root).get(ref), payload)

    def test_resume_restarts_dead_controller_process_in_same_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = E2BClient(fake=True)
            metadata = {"project": "lda", "run_id": "r", "role": "controller",
                        "lease_id": "controller-r"}
            controller = client.create(metadata)
            protocol = ControllerProtocol(tmp, client, repository_root=tmp)
            protocol._save_record(ControllerRecord(
                protocol_version=ControllerProtocol.VERSION,
                run_id="r",
                sandbox_id=controller.sandbox_id,
                metadata=metadata,
                controller_pid=123,
            ))
            original_command = client.command

            def command(sandbox, value, **kwargs):
                if value == "test -d /proc/123":
                    return {"exit_code": 1, "stdout": "", "stderr": ""}
                return original_command(sandbox, value, **kwargs)

            with patch.object(client, "command", side_effect=command), \
                    patch.object(protocol, "_launch") as launch, \
                    patch.object(protocol, "drive", return_value={"run_id": "r"}) as drive:
                result = protocol.resume()
            launch.assert_called_once_with(controller)
            drive.assert_called_once_with()
            self.assertEqual(result["run_id"], "r")

    @patch("lda.controller.runtime.ArgusSupervisor")
    def test_sandbox_runtime_recovers_existing_world_state(self, supervisor_type):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            world = WorldState("r", active=False)
            EventStore(root).save_world(world)
            supervisor = supervisor_type.return_value
            supervisor.world = world
            supervisor.run.return_value = []
            config = {"protocol_version": 1, "run_id": "r", "run_root": str(root),
                      "source_snapshot_root": str(Path(tmp) / "snapshot"),
                      "request_path": str(Path(tmp) / "request.json"),
                      "response_path": str(Path(tmp) / "response.json"), "campaign": {}}
            result = run_controller(config)
        supervisor_type.assert_called_once()
        self.assertEqual(result["controller_execution"], "e2b-sandbox")
        self.assertTrue(result["converged"])


if __name__ == "__main__":
    unittest.main()
