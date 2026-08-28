#!/usr/bin/env python3
import json, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card

card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=1200)
print("sandbox:", sandbox.sandbox_id, flush=True)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
sandbox.bootstrap_credentials()
workspace = Path(tempfile.mkdtemp(prefix="relay-direct-"))
(workspace / ".lda-hm").mkdir()
(workspace / ".lda-hm" / "live-sandbox.json").write_text(
    json.dumps({"sandbox_id": sandbox.sandbox_id, "epoch": time.time()}) + "\n")

# Probe attach primitives directly first
attached = E2BSandbox.attach(sandbox.sandbox_id)
r = attached.run(("echo", "attach-run-ok"))
print("attach run:", r.exit_code, r.stdout.strip(), r.stderr[-200:], flush=True)
local = Path(tempfile.mkstemp()[1]); local.write_text("hello-put")
try:
    attached.put(local, "/tmp/attach-put-test")
    r2 = attached.run(("cat", "/tmp/attach-put-test"))
    print("attach put+cat:", r2.exit_code, r2.stdout.strip(), flush=True)
except Exception as error:
    import traceback; traceback.print_exc()

proc = subprocess.run(
    [str(Path.home() / ".venvs/ldahm/bin/python"), "-m", "lda_hm.hmz_relay",
     "--cwd", str(workspace), "--role", "analyst", "--session", "analyst-direct",
     "--model", "claude-opus-4-8", "--effort", "low"],
    input="Reply with exactly the word: ok",
    capture_output=True, text=True, timeout=900,
    env={**__import__("os").environ, "PYTHONPATH": "/fact_data/yisun/LDA-HM/src"},
)
print("relay exit:", proc.returncode)
print("relay stdout:", proc.stdout[-500:])
print("relay stderr:", proc.stderr[-2500:])
sandbox.close()
