#!/usr/bin/env python3
"""End-to-end smoke of the hmz E2B backend: one real claude turn in a sandbox."""
import json, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card

card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=1800)
print("sandbox:", sandbox.sandbox_id, flush=True)
sandbox.bootstrap_assets(Path("/fact_data/yisun/LDA-HM/sandbox/lda-base"))
sandbox.bootstrap_credentials()

workspace = Path(tempfile.mkdtemp(prefix="hmz-smoke-"))
(workspace / ".lda-hm").mkdir()
from lda_hm.broker import SandboxBroker
broker = SandboxBroker(sandbox, workspace / ".lda-hm" / "broker.sock")
broker.start()
(workspace / ".lda-hm" / "live-sandbox.json").write_text(
    json.dumps({"sandbox_id": sandbox.sandbox_id, "broker": str(workspace / ".lda-hm" / "broker.sock"), "epoch": time.time()}) + "\n"
)

from hmz.agents import AgentConfig
from lda_hm.hmz_backend import E2BHarnessAgent

agent = E2BHarnessAgent(AgentConfig(model="claude-opus-4-8", effort="low"), name="reviewer")
clone = agent.clone(name="analyst")
session = clone.new(workspace)
print("box session:", session.box_session, flush=True)
answer = session("Reply with exactly the word: ok")
print("ANSWER:", repr(str(answer))[:200], flush=True)
again = session("Now reply with exactly the word: again")
print("ANSWER2:", repr(str(again))[:200], flush=True)
sandbox.close()
print("SMOKE-PASS" if "ok" in str(answer).lower() and "again" in str(again).lower() else "SMOKE-UNCLEAR")
