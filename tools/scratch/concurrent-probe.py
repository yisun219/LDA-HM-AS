#!/usr/bin/env python3
import sys, threading, time
from pathlib import Path
sys.path.insert(0, "/fact_data/yisun/LDA-HM/src")
from lda_hm.sandbox import E2BSandbox
from lda_hm.cli import _card
card = _card(Path("/fact_data/yisun/LDA-HM/examples/libcairo2-card.json"))
sandbox = E2BSandbox.connect(template=card.baseline.template, timeout=900)
print("sandbox:", sandbox.sandbox_id, flush=True)
results = {}
def slow():
    t0=time.time(); r = sandbox.run(("sh","-c","sleep 6; echo slow-done")); results["slow"]=(r.exit_code, r.stdout.strip(), round(time.time()-t0,1))
def fast():
    time.sleep(1); t0=time.time(); r = sandbox.run(("echo","fast-done")); results["fast"]=(r.exit_code, r.stdout.strip(), round(time.time()-t0,1))
a=threading.Thread(target=slow); b=threading.Thread(target=fast)
a.start(); b.start(); a.join(); b.join()
print("slow:", results["slow"])
print("fast:", results["fast"])
verdict = "CONCURRENT-OK" if results["fast"][2] < 4 and results["fast"][0]==0 and results["slow"][0]==0 else "SERIALIZED-OR-BROKEN"
print(verdict)
sandbox.close()
