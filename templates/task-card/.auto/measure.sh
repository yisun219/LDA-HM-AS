#!/usr/bin/env bash
# 唯一指标。注意:不要写 grep -c ... || echo 0(失败时会双行输出,已翻过车)。
set -euo pipefail
cd "$(dirname "$0")"
n=$(awk -F'\t' 'NR>1 && $2=="PASS"' state/GATES.tsv | wc -l | tr -d ' ')
echo "METRIC gates_passed=${n:-0}"
