from __future__ import annotations

import importlib.metadata
import json
from typing import Any

from lda.benchmarks.canary import architecture_compatibility
from lda.e2b.client import E2BClient, TESTED_E2B_SDK_VERSION


class Preflight:
    CHECKS = ("sdk_server", "control_create", "data_commands", "filesystem", "background_command",
              "pid_reconnect", "snapshot", "fork_fallback", "metadata", "network_restriction",
              "hardware_fingerprint", "orphan_cleanup", "template_exists", "kill")

    def __init__(self, client: E2BClient):
        self.client = client

    def run(self, run_id: str = "preflight") -> dict[str, Any]:
        result = {name: False for name in self.CHECKS}
        details: dict[str, Any] = {}
        sdk_version = importlib.metadata.version("e2b")
        result["sdk_server"] = sdk_version == TESTED_E2B_SDK_VERSION
        details["sdk_version"] = sdk_version
        details["required_sdk_version"] = TESTED_E2B_SDK_VERSION
        sandbox = self.client.create({"project": "lda", "run_id": run_id, "life_cycle": "preflight",
                                      "mission_id": "none", "candidate_id": "none", "role": "preflight",
                                      "lease_id": "preflight-" + run_id})
        result["control_create"] = True
        command = self.client.command(sandbox, "printf lda-preflight")
        result["data_commands"] = command.get("exit_code") == 0 and command.get("stdout") == "lda-preflight"
        self.client.filesystem_write(sandbox, "/tmp/preflight", "ok")
        result["filesystem"] = self.client.filesystem_read(sandbox, "/tmp/preflight") == "ok"
        background = self.client.command(sandbox, "sleep 300", background=True)
        pid = background.get("pid")
        result["background_command"] = isinstance(pid, int) and pid > 0
        remote_client = self.client if self.client.fake else E2BClient(
            self.client.gateway, template_fallback=self.client.template_fallback
        )
        reconnected = remote_client.connect(sandbox.sandbox_id)
        pid_check = remote_client.command(reconnected, f"test -d /proc/{pid}") if pid else {"exit_code": 1}
        result["pid_reconnect"] = pid_check.get("exit_code") == 0
        snapshot = self.client.snapshot(sandbox)
        result["snapshot"] = snapshot.get("mode") == "artifact_fallback" and "/tmp/preflight" in snapshot.get("files", [])
        child = self.client.fork(sandbox, {"project": "lda", "run_id": run_id + "-fork",
            "life_cycle": "preflight", "mission_id": "none", "candidate_id": "none",
            "role": "preflight", "lease_id": "fork-" + run_id})
        result["fork_fallback"] = self.client.filesystem_read(child, "/tmp/preflight") == "ok"
        if sandbox.native is not None:
            info = sandbox.native.get_info()
            server_metadata = getattr(info, "metadata", {}) or {}
            result["metadata"] = server_metadata.get("project") == "lda" and server_metadata.get("run_id") == run_id
            details["server_metadata"] = server_metadata
        else:
            result["metadata"] = sandbox.metadata.get("project") == "lda"
        network = self.client.command(sandbox, "python3 - <<'PY'\nimport socket\ntry:\n socket.create_connection(('1.1.1.1', 443), 3)\nexcept OSError:\n raise SystemExit(0)\nraise SystemExit(1)\nPY", timeout=10)
        result["network_restriction"] = network.get("exit_code") == 0
        hardware_cmd = self.client.command(sandbox, "python3 - <<'PY'\nimport json\nf={}\nfor line in open('/proc/cpuinfo').read().split('\\n\\n',1)[0].splitlines():\n if ':' in line:\n  k,v=line.split(':',1); f[k.strip()]=v.strip()\nprint(json.dumps({'cpu_model':f.get('model name',''),'vendor_id':f.get('vendor_id',''),'family':int(f.get('cpu family','-1')),'model':int(f.get('model','-1')),'stepping':int(f.get('stepping','-1')),'microcode':f.get('microcode',''),'flags':f.get('flags','').split(),'hypervisor':'kvm' if 'hypervisor' in f.get('flags','').split() else ''}))\nPY")
        try:
            hardware = json.loads(hardware_cmd.get("stdout", ""))
            compatibility = architecture_compatibility(hardware)
            result["hardware_fingerprint"] = compatibility["compatible"]
            details["hardware"] = hardware
            details["hardware_compatibility"] = compatibility
        except (TypeError, ValueError, json.JSONDecodeError):
            result["hardware_fingerprint"] = False
        orphan = self.client.create({"project": "lda", "run_id": run_id + "-orphan", "life_cycle": "preflight",
            "mission_id": "none", "candidate_id": "none", "role": "preflight", "lease_id": "orphan-" + run_id})
        result["orphan_cleanup"] = self.client.reap(run_id + "-orphan") == 1 and not orphan.alive
        manifest = self.client.command(sandbox, "test -f /opt/lda/template-manifest.json || test -d /workspace")
        result["template_exists"] = manifest.get("exit_code") == 0
        self.client.kill(child)
        self.client.kill(sandbox)
        reconnected.alive = False
        result["kill"] = not sandbox.alive
        return {"passed": all(result.values()), "checks": result, "details": details}
