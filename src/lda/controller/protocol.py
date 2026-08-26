"""Bootstrap-to-Controller execution protocol.

The LDA supervisor runs inside the Controller sandbox.  It has no E2B or model
credential; instead it issues serialized tool requests to the bootstrap
process.  Bootstrap owns the SDK client and injects secrets only into their
authorized child sandboxes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from lda.artifacts.store import ArtifactStore
from lda.config.templates import TemplateAliases
from lda.e2b.client import E2BClient, Sandbox


CONTROLLER_ROOT = "/workspace/lda-controller"
REQUEST_PATH = CONTROLLER_ROOT + "/request.json"
RESPONSE_PATH = CONTROLLER_ROOT + "/response.json"
EXIT_PATH = CONTROLLER_ROOT + "/exit-code"
LOG_PATH = CONTROLLER_ROOT + "/controller.log"
CONFIG_PATH = CONTROLLER_ROOT + "/campaign.json"
RUNTIME_ROOT = CONTROLLER_ROOT + "/runtime"
RUN_ROOT = CONTROLLER_ROOT + "/run"
AGENT_SCHEMA_ROOT = PurePosixPath("/workspace/lda/schemas")

AGENT_ROLES = frozenset({
    "Argus Manager", "World State Summarizer", "Research Curator", "Mission Planner",
    "Profiler", "Builder", "Reviewer", "Trace Auditor", "Outcome Classifier",
    "Capability Planner", "Capability Builder",
})
REQUIRED_SANDBOX_METADATA = frozenset({
    "project", "run_id", "life_cycle", "mission_id", "candidate_id", "role",
    "template", "lease_id",
})
OPTIONAL_SANDBOX_METADATA = frozenset({"capability_id", "timeout", "snapshot_id"})


@dataclass(frozen=True)
class ControllerRecord:
    protocol_version: int
    run_id: str
    sandbox_id: str
    metadata: dict[str, str]
    request_path: str = REQUEST_PATH
    response_path: str = RESPONSE_PATH
    exit_path: str = EXIT_PATH
    log_path: str = LOG_PATH
    config_path: str = CONFIG_PATH
    run_root: str = RUN_ROOT
    controller_pid: int | None = None


class ControllerProtocol:
    """Host-side bridge for a sandbox-resident Supervisor."""

    VERSION = 1

    def __init__(self, root: str | Path, client: E2BClient, *, repository_root: str | Path | None = None,
                 template_aliases: TemplateAliases | None = None):
        self.root = Path(root).resolve()
        self.client = client
        self.repository_root = Path(repository_root or Path(__file__).resolve().parents[3]).resolve()
        self.templates = template_aliases or TemplateAliases()
        self.record_path = self.root / ".lda" / "controller.json"
        self.registry_path = self.root / ".lda" / "controller-sandboxes.json"
        self.controller: Sandbox | None = None
        self.record: ControllerRecord | None = None
        self._last_request_id: str | None = None

    def _save_record(self, record: ControllerRecord) -> None:
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.record_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(record), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.record_path)
        self.record = record

    def load(self) -> ControllerRecord:
        if not self.record_path.is_file():
            raise RuntimeError("controller recovery record is missing; refusing local Supervisor fallback")
        raw = json.loads(self.record_path.read_text(encoding="utf-8"))
        if raw.get("protocol_version") != self.VERSION:
            raise RuntimeError("unsupported controller protocol version")
        self.record = ControllerRecord(**raw)
        return self.record

    def _create_controller(self, run_id: str) -> Sandbox:
        metadata = {
            "project": "lda", "run_id": run_id, "life_cycle": "bootstrap",
            "mission_id": "controller", "candidate_id": "none", "role": "controller",
            "template": self.templates.controller, "lease_id": "controller-" + run_id,
            "timeout": "86400",
        }
        controller = self.client.create(metadata)
        record = ControllerRecord(self.VERSION, run_id, controller.sandbox_id, dict(metadata))
        self.controller = controller
        self._save_record(record)
        self._save_registry({"version": self.VERSION, "run_id": run_id,
                             "sandboxes": {}, "leases": {}})
        return controller

    def _run_id(self) -> str:
        return (self.record or self.load()).run_id

    def _save_registry(self, registry: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.registry_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.registry_path)

    def _load_registry(self) -> dict[str, Any]:
        run_id = self._run_id()
        if not self.registry_path.is_file():
            registry = {"version": self.VERSION, "run_id": run_id,
                        "sandboxes": {}, "leases": {}}
            self._save_registry(registry)
            return registry
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if registry.get("version") != self.VERSION or registry.get("run_id") != run_id:
            raise RuntimeError("Controller sandbox registry does not belong to the active run")
        if not isinstance(registry.get("sandboxes"), dict) or not isinstance(registry.get("leases"), dict):
            raise RuntimeError("Controller sandbox registry is invalid")
        return registry

    def _expected_template(self, role: str) -> str:
        if role in AGENT_ROLES:
            return self.templates.agent_runtime
        role_templates = {
            "qualification": self.templates.base,
            "candidate-work": self.templates.base,
            "capability-work": self.templates.base,
            # The current capability judge executes the isolated offline test in
            # the base environment. It receives neither network nor credentials.
            "capability-judge": self.templates.base,
            "judge": self.templates.judge,
            "e2e": self.templates.e2e,
        }
        expected = role_templates.get(role)
        if expected is None:
            raise RuntimeError(f"Controller sandbox role is not allowed: {role}")
        return expected

    def _validate_metadata(self, metadata: Any) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            raise RuntimeError("Controller sandbox metadata must be an object")
        missing = REQUIRED_SANDBOX_METADATA - set(metadata)
        unknown = set(metadata) - REQUIRED_SANDBOX_METADATA - OPTIONAL_SANDBOX_METADATA
        if missing:
            raise RuntimeError("Controller sandbox metadata is missing: " + ", ".join(sorted(missing)))
        if unknown:
            raise RuntimeError("Controller sandbox metadata contains unsupported keys: "
                               + ", ".join(sorted(unknown)))
        normalized = dict(metadata)
        for key in REQUIRED_SANDBOX_METADATA:
            if not isinstance(normalized[key], str) or not normalized[key].strip():
                raise RuntimeError(f"Controller sandbox metadata {key} must be a non-empty string")
        if normalized["project"] != "lda":
            raise RuntimeError("Controller sandbox project must be lda")
        if normalized["run_id"] != self._run_id():
            raise RuntimeError("Controller sandbox run_id does not match the active run")
        expected = self._expected_template(normalized["role"])
        if normalized["template"] != expected:
            raise RuntimeError(
                f"Controller sandbox role/template mismatch: {normalized['role']} requires {expected}"
            )
        timeout = normalized.get("timeout")
        if timeout is not None:
            try:
                timeout_value = int(timeout)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Controller sandbox timeout must be an integer") from exc
            if timeout_value <= 0 or timeout_value > 86400:
                raise RuntimeError("Controller sandbox timeout is outside the allowed range")
        return normalized

    @staticmethod
    def _metadata_identity(metadata: dict[str, Any]) -> dict[str, Any]:
        return {key: metadata.get(key) for key in sorted(REQUIRED_SANDBOX_METADATA | {"capability_id"})}

    def _register_sandbox(self, sandbox: Sandbox, metadata: dict[str, Any]) -> None:
        registry = self._load_registry()
        sandbox_id = sandbox.sandbox_id
        lease_id = str(metadata["lease_id"])
        owned = registry["sandboxes"].get(sandbox_id)
        lease_owner = registry["leases"].get(lease_id)
        if owned is not None:
            owned_metadata = owned.get("metadata") if isinstance(owned, dict) else None
            if not isinstance(owned_metadata, dict):
                raise RuntimeError("Controller sandbox registry metadata is invalid")
            if self._metadata_identity(owned_metadata) != self._metadata_identity(metadata):
                raise RuntimeError("Controller sandbox ID is already registered with different metadata")
        if lease_owner is not None and lease_owner != sandbox_id:
            raise RuntimeError("Controller sandbox lease is already owned by another sandbox")
        registry["sandboxes"][sandbox_id] = {
            "lease_id": lease_id, "metadata": metadata, "alive": True,
        }
        registry["leases"][lease_id] = sandbox_id
        self._save_registry(registry)

    def _owned_by_lease(self, metadata: dict[str, Any]) -> Sandbox | None:
        registry = self._load_registry()
        sandbox_id = registry["leases"].get(metadata["lease_id"])
        if sandbox_id is None:
            return None
        owned = registry["sandboxes"].get(sandbox_id)
        if not isinstance(owned, dict):
            raise RuntimeError("Controller sandbox lease registry is inconsistent")
        if self._metadata_identity(owned.get("metadata", {})) != self._metadata_identity(metadata):
            raise RuntimeError("Controller sandbox lease replay metadata does not match")
        if owned.get("alive") is not True:
            raise RuntimeError("Controller sandbox lease belongs to a terminated sandbox")
        return self._sandbox(str(sandbox_id))

    def _create_owned(self, metadata: Any, *, parent: Sandbox | None = None) -> Sandbox:
        normalized = self._validate_metadata(metadata)
        existing = self._owned_by_lease(normalized)
        if existing is not None:
            return existing
        sandbox = self.client.fork(parent, normalized) if parent is not None else self.client.create(normalized)
        self._register_sandbox(sandbox, normalized)
        return sandbox

    def reconnect(self) -> Sandbox:
        record = self.record or self.load()
        controller = self.client.connect(record.sandbox_id)
        controller.metadata.update(record.metadata)
        self.controller = controller
        return controller

    def _mkdirs(self, controller: Sandbox, paths: list[str]) -> None:
        quoted = " ".join(shlex.quote(path) for path in sorted(set(paths)))
        result = self.client.command(controller, "mkdir -p " + quoted, timeout=120)
        if result.get("exit_code") != 0:
            raise RuntimeError("failed to create Controller runtime directories")

    def _upload_python_runtime(self, controller: Sandbox) -> None:
        source_root = self.repository_root / "src"
        files = sorted((source_root / "lda").rglob("*.py"))
        if not files:
            raise RuntimeError("LDA Python runtime is missing")
        directories = [str(Path(RUNTIME_ROOT) / "src" / path.relative_to(source_root).parent) for path in files]
        self._mkdirs(controller, directories + [CONTROLLER_ROOT, RUN_ROOT])
        manifest_lines = []
        for source in files:
            target = str(Path(RUNTIME_ROOT) / "src" / source.relative_to(source_root))
            payload = source.read_bytes()
            self.client.filesystem_write(controller, target, payload)
            manifest_lines.append(f"{hashlib.sha256(payload).hexdigest()}  {target}")
        manifest_path = RUNTIME_ROOT + "/SHA256SUMS"
        self.client.filesystem_write(controller, manifest_path, "\n".join(manifest_lines) + "\n")
        verified = self.client.command(controller, f"sha256sum -c {shlex.quote(manifest_path)}", timeout=300)
        if verified.get("exit_code") != 0:
            raise RuntimeError("Controller Python runtime hash verification failed")

    def _upload_source_snapshot(self, controller: Sandbox) -> str:
        snapshot_root = self.repository_root / "source_snapshot"
        manifest_files = list(snapshot_root.glob("*/SHA256SUMS"))
        if not manifest_files:
            raise RuntimeError("fixed source snapshot is missing")
        files = sorted(path for path in snapshot_root.rglob("*") if path.is_file())
        remote_root = CONTROLLER_ROOT + "/source_snapshot"
        directories = [str(Path(remote_root) / path.relative_to(snapshot_root).parent) for path in files]
        self._mkdirs(controller, directories)
        for source in files:
            target = str(Path(remote_root) / source.relative_to(snapshot_root))
            self.client.filesystem_write(controller, target, source.read_bytes())
        for manifest in sorted(manifest_files):
            remote_manifest = Path(remote_root) / manifest.relative_to(snapshot_root)
            verified = self.client.command(
                controller,
                f"cd {shlex.quote(str(remote_manifest.parent))} && "
                f"sha256sum -c {shlex.quote(remote_manifest.name)}",
                timeout=1800,
            )
            if verified.get("exit_code") != 0:
                raise RuntimeError(
                    f"Controller source snapshot hash verification failed: "
                    f"{manifest.relative_to(snapshot_root)}"
                )
        return remote_root

    def prepare(self, *, run_id: str, campaign: dict[str, Any], campaign_content: bytes) -> Sandbox:
        controller = self._create_controller(run_id)
        self._upload_python_runtime(controller)
        source_snapshot_root = self._upload_source_snapshot(controller)
        campaign_path = CONTROLLER_ROOT + "/campaign-input/" + Path(campaign["filename"]).name
        self._mkdirs(controller, [str(Path(campaign_path).parent)])
        self.client.filesystem_write(controller, campaign_path, campaign_content)
        if hashlib.sha256(self.client.filesystem_read_bytes(controller, campaign_path)).hexdigest() != campaign["sha256"]:
            raise RuntimeError("Controller campaign input hash mismatch after upload")
        controller_campaign = dict(campaign)
        controller_campaign["source_path"] = campaign_path
        controller_campaign["e2b_path"] = campaign_path
        campaign_artifact = (RUN_ROOT + "/.lda/artifacts/campaign-input/"
                             + Path(campaign["filename"]).name)
        campaign_manifest = RUN_ROOT + "/.lda/artifacts/campaign-input/manifest.json"
        self._mkdirs(controller, [str(Path(campaign_artifact).parent)])
        self.client.filesystem_write(controller, campaign_artifact, campaign_content)
        controller_campaign["original_artifact"] = str(
            Path(".lda/artifacts/campaign-input") / Path(campaign["filename"]).name)
        self.client.filesystem_write(
            controller, campaign_manifest,
            json.dumps(controller_campaign, indent=2, sort_keys=True) + "\n")
        if hashlib.sha256(self.client.filesystem_read_bytes(controller, campaign_artifact)).hexdigest() != campaign["sha256"]:
            raise RuntimeError("Controller campaign Artifact hash mismatch after upload")
        config = {
            "protocol_version": self.VERSION,
            "run_id": run_id,
            "run_root": RUN_ROOT,
            "source_snapshot_root": source_snapshot_root,
            "campaign": controller_campaign,
            "templates": self.templates.as_dict(),
            "request_path": REQUEST_PATH,
            "response_path": RESPONSE_PATH,
        }
        self.client.filesystem_write(controller, CONFIG_PATH, json.dumps(config, sort_keys=True) + "\n")
        return controller

    @staticmethod
    def _runtime_command() -> str:
        return (
            "sh -lc " + shlex.quote(
                f"PYTHONPATH={RUNTIME_ROOT}/src python3 -m lda.controller.runtime --config {CONFIG_PATH} "
                f"> {LOG_PATH} 2>&1; code=$?; printf '%s\\n' \"$code\" > {EXIT_PATH}; exit $code"
            )
        )

    def _launch(self, controller: Sandbox) -> None:
        started = self.client.command(controller, self._runtime_command(), background=True)
        pid = started.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            raise RuntimeError("Controller runtime did not return a background PID")
        record = self.record or self.load()
        self._save_record(replace(record, controller_pid=pid))

    def start(self) -> dict[str, Any]:
        controller = self.controller or self.reconnect()
        self._launch(controller)
        return self.drive()

    def resume(self) -> dict[str, Any]:
        controller = self.reconnect()
        exit_code = self._read_optional(controller, EXIT_PATH)
        record = self.record or self.load()
        process_alive = False
        if record.controller_pid:
            check = self.client.command(controller, f"test -d /proc/{record.controller_pid}", timeout=30)
            process_alive = check.get("exit_code") == 0
        if exit_code is None and process_alive:
            return self.drive()
        if exit_code is None or exit_code.strip() != "0":
            # Restart only the sandbox Controller process. Its Qualification
            # checkpoint and World State remain inside the same sandbox.
            self.client.command(
                controller,
                "python3 -c " + shlex.quote(
                    "from pathlib import Path; "
                    f"[Path(p).unlink(missing_ok=True) for p in {([EXIT_PATH, REQUEST_PATH, RESPONSE_PATH])!r}]"
                ),
                timeout=30,
            )
            self._launch(controller)
        return self.drive()

    def _read_optional(self, sandbox: Sandbox, path: str) -> str | None:
        try:
            return self.client.filesystem_read(sandbox, path)
        except Exception:
            return None

    def _sandbox(self, sandbox_id: str, metadata: dict[str, Any] | None = None) -> Sandbox:
        registry = self._load_registry()
        owned = registry["sandboxes"].get(sandbox_id)
        if not isinstance(owned, dict) or owned.get("alive") is not True:
            raise RuntimeError("Controller sandbox is not owned by the active run")
        stored_metadata = owned.get("metadata")
        if not isinstance(stored_metadata, dict):
            raise RuntimeError("Controller sandbox registry metadata is invalid")
        self._validate_metadata(stored_metadata)
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise RuntimeError("Controller sandbox request metadata must be an object")
            if self._metadata_identity(metadata) != self._metadata_identity(stored_metadata):
                raise RuntimeError("Controller sandbox request metadata does not match the registry")
        for sandbox in self.client.sandboxes.values():
            if sandbox.sandbox_id == sandbox_id and sandbox.alive:
                sandbox.metadata.clear()
                sandbox.metadata.update(stored_metadata)
                return sandbox
        sandbox = self.client.connect(sandbox_id)
        sandbox.metadata.update(stored_metadata)
        return sandbox

    @staticmethod
    def _agent_command_tokens(command: str) -> list[str]:
        if "\n" in command or "\r" in command:
            raise RuntimeError("Agent Runtime command contains a line break")
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError as exc:
            raise RuntimeError("Agent Runtime command is not valid shell syntax") from exc
        if any(token and set(token) <= set(";&|<>") for token in tokens):
            raise RuntimeError("Agent Runtime command contains shell control operators")
        return tokens

    def _validate_command(self, sandbox: Sandbox, command: str, *, background: bool = False) -> None:
        if sandbox.metadata.get("role") not in AGENT_ROLES:
            return
        tokens = self._agent_command_tokens(command)
        if len(tokens) < 2 or tokens[:2] != ["codex", "exec"]:
            raise RuntimeError("Agent Runtime may execute only codex exec")
        forbidden = {"--yolo", "--dangerously-bypass-approvals-and-sandbox"}
        if forbidden.intersection(tokens):
            raise RuntimeError("Agent Runtime codex exec requested a forbidden execution mode")
        if background:
            raise RuntimeError("Agent Runtime codex exec must run in the foreground")

    @staticmethod
    def _validate_agent_path(sandbox: Sandbox, path: str) -> None:
        if sandbox.metadata.get("role") not in AGENT_ROLES:
            return
        candidate = PurePosixPath(path)
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeError("Agent Runtime filesystem path is invalid")
        try:
            relative = candidate.relative_to(AGENT_SCHEMA_ROOT)
        except ValueError as exc:
            raise RuntimeError("Agent Runtime filesystem is limited to /workspace/lda/schemas") from exc
        if not relative.parts:
            raise RuntimeError("Agent Runtime filesystem operation requires a schema file path")

    def _mark_terminated(self, sandbox_id: str) -> None:
        registry = self._load_registry()
        owned = registry["sandboxes"].get(sandbox_id)
        if not isinstance(owned, dict):
            raise RuntimeError("Controller sandbox is not owned by the active run")
        owned["alive"] = False
        self._save_registry(registry)

    def _dispatch(self, request: dict[str, Any]) -> Any:
        op = request.get("op")
        args = request.get("args") if isinstance(request.get("args"), dict) else {}
        if op == "create":
            sandbox = self._create_owned(args.get("metadata"))
            return {"sandbox_id": sandbox.sandbox_id, "metadata": sandbox.metadata}
        if op == "connect":
            sandbox = self._sandbox(str(args["sandbox_id"]))
            return {"sandbox_id": sandbox.sandbox_id, "metadata": sandbox.metadata}
        if op == "command":
            sandbox = self._sandbox(str(args["sandbox_id"]), args.get("metadata"))
            command = str(args["command"])
            background = bool(args.get("background", False))
            self._validate_command(sandbox, command, background=background)
            process_env = self.client.agent_process_env() if sandbox.metadata.get("role") in AGENT_ROLES else None
            return self.client.command(sandbox, command,
                                       background=background,
                                       timeout=args.get("timeout"), envs=process_env)
        if op == "command_checkpointed":
            sandbox = self._sandbox(str(args["sandbox_id"]), args.get("metadata"))
            command = str(args["command"])
            self._validate_command(sandbox, command)
            return self.client.command_checkpointed(
                sandbox, command, timeout=float(args["timeout"]),
                poll_seconds=float(args.get("poll_seconds", 5.0)))
        if op == "filesystem_write":
            sandbox = self._sandbox(str(args["sandbox_id"]), args.get("metadata"))
            path = str(args["path"])
            self._validate_agent_path(sandbox, path)
            payload = base64.b64decode(args["content_base64"], validate=True)
            self.client.filesystem_write(sandbox, path, payload)
            return {"written": len(payload)}
        if op == "filesystem_read":
            sandbox = self._sandbox(str(args["sandbox_id"]), args.get("metadata"))
            path = str(args["path"])
            self._validate_agent_path(sandbox, path)
            payload = self.client.filesystem_read_bytes(sandbox, path)
            return {"content_base64": base64.b64encode(payload).decode(), "bytes": len(payload)}
        if op == "snapshot":
            return self.client.snapshot(self._sandbox(str(args["sandbox_id"]), args.get("metadata")))
        if op == "fork":
            parent = self._sandbox(str(args["sandbox_id"]), args.get("parent_metadata"))
            child = self._create_owned(args.get("metadata"), parent=parent)
            return {"sandbox_id": child.sandbox_id, "metadata": child.metadata}
        if op == "kill":
            sandbox = self._sandbox(str(args["sandbox_id"]), args.get("metadata"))
            self.client.kill(sandbox)
            self._mark_terminated(sandbox.sandbox_id)
            return {"killed": True}
        if op == "reap":
            run_id = str(args["run_id"])
            if run_id != self._run_id():
                raise RuntimeError("Controller may reap only the active run")
            reaped = self.client.reap(run_id)
            registry = self._load_registry()
            for owned in registry["sandboxes"].values():
                owned["alive"] = False
            self._save_registry(registry)
            return {"reaped": reaped}
        if op == "codex_command":
            output_schema_path = args.get("output_schema_path")
            if output_schema_path is not None:
                schema_box = Sandbox("schema-policy", {"role": "Builder"})
                self._validate_agent_path(schema_box, str(output_schema_path))
            return {"command": self.client.codex_command(
                str(args["prompt"]), session_id=args.get("session_id"),
                model=str(args.get("model", "gpt-5")),
                reasoning_effort=str(args.get("reasoning_effort", "high")),
                output_schema_path=output_schema_path)}
        raise RuntimeError(f"unsupported Controller operation: {op}")

    def serve_once(self) -> bool:
        controller = self.controller or self.reconnect()
        raw = self._read_optional(controller, REQUEST_PATH)
        if not raw:
            return False
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            return False
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or request_id == self._last_request_id:
            return False
        existing_raw = self._read_optional(controller, RESPONSE_PATH)
        if existing_raw:
            try:
                existing = json.loads(existing_raw)
            except json.JSONDecodeError:
                existing = {}
            if existing.get("request_id") == request_id:
                self._last_request_id = request_id
                return False
        try:
            result = self._dispatch(request)
            response = {"protocol_version": self.VERSION, "request_id": request_id,
                        "ok": True, "result": result}
        except Exception as exc:
            response = {"protocol_version": self.VERSION, "request_id": request_id,
                        "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.client.filesystem_write(controller, RESPONSE_PATH, json.dumps(response, sort_keys=True) + "\n")
        self._last_request_id = request_id
        return True

    def _sync_state(self) -> None:
        controller = self.controller or self.reconnect()
        mappings = {
            RUN_ROOT + "/.lda/world.json": self.root / ".lda" / "world.json",
            RUN_ROOT + "/.lda/events.jsonl": self.root / ".lda" / "events.jsonl",
            RUN_ROOT + "/.lda/artifacts/qualification.json": self.root / ".lda" / "artifacts" / "qualification.json",
            LOG_PATH: self.root / ".lda" / "controller.log",
        }
        for remote, local in mappings.items():
            payload = self._read_optional(controller, remote)
            if payload is None:
                continue
            local.parent.mkdir(parents=True, exist_ok=True)
            temporary = local.with_suffix(local.suffix + ".tmp")
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, local)
        world_path = self.root / ".lda" / "world.json"
        if world_path.is_file():
            self._sync_artifacts(controller, json.loads(world_path.read_text(encoding="utf-8")))

    @staticmethod
    def _artifact_refs(value: Any) -> set[str]:
        if isinstance(value, str):
            return {value} if value.startswith(ArtifactStore.PREFIX) else set()
        if isinstance(value, dict):
            refs: set[str] = set()
            for item in value.values():
                refs.update(ControllerProtocol._artifact_refs(item))
            return refs
        if isinstance(value, list):
            refs = set()
            for item in value:
                refs.update(ControllerProtocol._artifact_refs(item))
            return refs
        return set()

    def _sync_artifacts(self, controller: Sandbox, world: dict[str, Any]) -> None:
        store = ArtifactStore(self.root)
        for ref in sorted(self._artifact_refs(world)):
            digest = ref[len(ArtifactStore.PREFIX):]
            remote = f"{RUN_ROOT}/.lda/artifacts/sha256/{digest[:2]}/{digest}"
            payload = self.client.filesystem_read_bytes(controller, remote)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError(f"Controller artifact hash mismatch during sync: {ref}")
            if store.put("controller-artifact", payload) != ref:
                raise RuntimeError(f"Controller artifact identity mismatch during sync: {ref}")

    def drive(self, *, timeout_seconds: float | None = None, poll_seconds: float = 0.5) -> dict[str, Any]:
        controller = self.controller or self.reconnect()
        deadline = time.monotonic() + (timeout_seconds or float(os.environ.get("LDA_CONTROLLER_TIMEOUT", "604800")))
        next_sync = 0.0
        while time.monotonic() < deadline:
            self.serve_once()
            now = time.monotonic()
            if now >= next_sync:
                self._sync_state()
                next_sync = now + 5.0
            exit_raw = self._read_optional(controller, EXIT_PATH)
            if exit_raw is not None and exit_raw.strip():
                try:
                    exit_code = int(exit_raw.strip())
                except ValueError as exc:
                    raise RuntimeError("invalid Controller exit status") from exc
                self._sync_state()
                result_raw = self._read_optional(controller, RUN_ROOT + "/.lda/controller-result.json")
                result = json.loads(result_raw) if result_raw else {}
                if exit_code != 0:
                    log = self._read_optional(controller, LOG_PATH) or ""
                    raise RuntimeError(f"Controller sandbox failed with exit code {exit_code}: {log[-4000:]}")
                return result
            time.sleep(poll_seconds)
        raise RuntimeError("Controller protocol timed out; sandbox remains recoverable")


class ControllerProxyClient:
    """Sandbox-side E2B client facade backed by ControllerProtocol requests."""

    def __init__(self, request_path: str = REQUEST_PATH, response_path: str = RESPONSE_PATH,
                 *, timeout_seconds: float = 7200):
        self.request_path = Path(request_path)
        self.response_path = Path(response_path)
        self.timeout_seconds = timeout_seconds
        self.sandboxes: dict[str, Sandbox] = {}
        self.allow_agent_stub = False
        self.template_fallback = None

    def _call(self, op: str, **args: Any) -> Any:
        request_id = uuid.uuid4().hex
        request = {"protocol_version": ControllerProtocol.VERSION, "request_id": request_id,
                   "op": op, "args": args}
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.request_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.request_path)
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            try:
                response = json.loads(self.response_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
            if response.get("request_id") != request_id:
                time.sleep(0.1)
                continue
            if response.get("ok") is not True:
                raise RuntimeError(response.get("error", "Controller bridge operation failed"))
            return response.get("result")
        raise RuntimeError(f"Controller bridge timeout for operation {op}")

    def create(self, metadata: dict[str, str]) -> Sandbox:
        result = self._call("create", metadata=metadata)
        sandbox = Sandbox(result["sandbox_id"], dict(result.get("metadata", metadata)))
        self.sandboxes[sandbox.sandbox_id] = sandbox
        return sandbox

    def connect(self, sandbox_id: str) -> Sandbox:
        result = self._call("connect", sandbox_id=sandbox_id)
        sandbox = Sandbox(result["sandbox_id"], dict(result.get("metadata", {})))
        self.sandboxes[sandbox.sandbox_id] = sandbox
        return sandbox

    def command(self, sandbox: Sandbox, command: str, *, background: bool = False,
                timeout: float | None = None) -> dict[str, Any]:
        return self._call("command", sandbox_id=sandbox.sandbox_id, metadata=sandbox.metadata,
                          command=command, background=background, timeout=timeout)

    def command_checkpointed(self, sandbox: Sandbox, command: str, *, timeout: float,
                             poll_seconds: float = 5.0) -> dict[str, Any]:
        return self._call("command_checkpointed", sandbox_id=sandbox.sandbox_id,
                          metadata=sandbox.metadata, command=command,
                          timeout=timeout, poll_seconds=poll_seconds)

    def filesystem_write(self, sandbox: Sandbox, path: str, content: str | bytes) -> None:
        payload = content.encode() if isinstance(content, str) else bytes(content)
        self._call("filesystem_write", sandbox_id=sandbox.sandbox_id, metadata=sandbox.metadata,
                   path=path, content_base64=base64.b64encode(payload).decode())

    def filesystem_read_bytes(self, sandbox: Sandbox, path: str) -> bytes:
        result = self._call("filesystem_read", sandbox_id=sandbox.sandbox_id,
                            metadata=sandbox.metadata, path=path)
        return base64.b64decode(result["content_base64"])

    def filesystem_read(self, sandbox: Sandbox, path: str) -> str:
        return self.filesystem_read_bytes(sandbox, path).decode()

    def snapshot(self, sandbox: Sandbox) -> dict[str, Any]:
        return self._call("snapshot", sandbox_id=sandbox.sandbox_id, metadata=sandbox.metadata)

    def fork(self, sandbox: Sandbox, metadata: dict[str, str]) -> Sandbox:
        result = self._call("fork", sandbox_id=sandbox.sandbox_id,
                            parent_metadata=sandbox.metadata, metadata=metadata)
        child = Sandbox(result["sandbox_id"], dict(result.get("metadata", metadata)))
        self.sandboxes[child.sandbox_id] = child
        return child

    def kill(self, sandbox: Sandbox) -> None:
        self._call("kill", sandbox_id=sandbox.sandbox_id, metadata=sandbox.metadata)
        sandbox.alive = False

    def reap(self, run_id: str) -> int:
        return int(self._call("reap", run_id=run_id)["reaped"])

    def codex_command(self, prompt: str, *, session_id: str | None = None,
                      model: str = "gpt-5", reasoning_effort: str = "high",
                      output_schema_path: str | None = None) -> str:
        result = self._call("codex_command", prompt=prompt, session_id=session_id,
                            model=model, reasoning_effort=reasoning_effort,
                            output_schema_path=output_schema_path)
        return str(result["command"])
