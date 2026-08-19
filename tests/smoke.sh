#!/usr/bin/env bash
# 机械冒烟:不调用任何真实引擎(用假引擎验证驱动器/卡协议/防作弊脚本的全部机械路径)。
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n lda tools/autoresearch.sh
bash -n templates/task-card/.auto/checks.sh
bash -n examples/fccache-card/.auto/checks.sh
( cd examples/fccache-card/.auto && bash measure.sh | grep -q 'METRIC gates_passed=0' && bash checks.sh )
OUT=$(ENGINE_CMD='echo [ci-fake-engine]' bash tools/autoresearch.sh examples/fccache-card 1)
grep -q 'iter 1 done' <<<"$OUT"
test ! -e examples/fccache-card/.lda-run/lock   # 锁必须自清
rm -rf examples/fccache-card/.lda-run
./lda help | grep -q fleet
ST=$(./lda status examples/fccache-card)
grep -q 'remaining_TODO=7' <<<"$ST"
echo "smoke: OK"
