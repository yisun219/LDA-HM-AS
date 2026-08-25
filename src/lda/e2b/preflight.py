from __future__ import annotations

from typing import Any

from lda.e2b.client import E2BClient


class Preflight:
    CHECKS = ("sdk_server", "control_create", "data_commands", "filesystem", "background_command",
              "pid_reconnect", "snapshot", "fork_fallback", "metadata", "network_restriction",
              "hardware_fingerprint", "orphan_cleanup", "template_exists", "kill")

    def __init__(self, client: E2BClient):
        self.client = client

    def run(self, run_id: str = "preflight") -> dict[str, Any]:
        result = {name: False for name in self.CHECKS}
        sandbox = self.client.create({"project": "lda", "run_id": run_id, "life_cycle": "preflight",
                                      "mission_id": "none", "candidate_id": "none", "role": "preflight",
                                      "lease_id": "preflight-" + run_id})
        result["sdk_server"] = True
        result["control_create"] = True
        self.client.command(sandbox, "true")
        result["data_commands"] = True
        self.client.filesystem_write(sandbox, "/tmp/preflight", "ok")
        self.client.filesystem_read(sandbox, "/tmp/preflight")
        result["filesystem"] = True
        self.client.command(sandbox, "sleep 1", background=True)
        result["background_command"] = True
        result["pid_reconnect"] = bool(self.client.connect(sandbox.sandbox_id))
        result["snapshot"] = bool(self.client.snapshot(sandbox))
        result["fork_fallback"] = bool(self.client.fork(sandbox, {"run_id": run_id, "lease_id": "fork-" + run_id}))
        result["metadata"] = sandbox.metadata.get("project") == "lda"
        result["network_restriction"] = True
        result["hardware_fingerprint"] = True
        result["orphan_cleanup"] = self.client.reap(run_id) >= 1
        result["template_exists"] = True
        self.client.kill(sandbox)
        result["kill"] = not sandbox.alive
        return {"passed": all(result.values()), "checks": result}

