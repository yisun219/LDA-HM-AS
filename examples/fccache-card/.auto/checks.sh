#!/usr/bin/env bash
# 防作弊基线:每个 PASS 必须挂真实、非空、含作业号/产物路径线索的证据文件。
# 按卡具体化后,先对一条伪造的 PASS 行验证本脚本会报错,再启用。
# 【开卡必改】门号映射是卡级配置:逐门核对本卡真实的门,别沿用别的卡的编号
# (实测教训:拷来的映射检了不存在的门、漏掉了真实的检查项,一整轮没被发现)。
# 【收尾必跑】收尾时运行本脚本并把退出码写进证据;无调度作业的门第⑤要素标 NO-JOB。
set -euo pipefail
cd "$(dirname "$0")"
# R7 机械强制:开卡时逐门核对下方检查与 GATES.tsv 的双向映射后,把 no 改为 yes;
# 不改,本脚本拒绝给出任何 PASS 结论(实测教训:拷来的映射一整轮没人发现检错了门)。
GATE_MAP_VERIFIED=yes   # 示例卡开卡时已逐门核对(G0-G6)
[ "$GATE_MAP_VERIFIED" = "yes" ] || { echo "R7-FAIL: 门号映射未核对(开卡必改 GATE_MAP_VERIFIED)"; exit 1; }
fail=0
while IFS=$'\t' read -r gid status ev note; do
  # R10:状态只准四态词表(PASS/FAIL/INCONCLUSIVE/TODO/不适用|N/A);不适用必须带理由
  # (实测:状态改成词表外值+清空理由,旧检查零反应)
  case "$status" in
    PASS|FAIL|INCONCLUSIVE|TODO|不适用|N/A) : ;;
    *) echo "R10-FAIL $gid: 状态在四态词表外: $status"; fail=1 ;;
  esac
  if [ "$status" = "不适用" ] || [ "$status" = "N/A" ]; then
    if [ -z "$note" ] || [ "$note" = "-" ]; then echo "R10-FAIL $gid: 不适用/N-A 必须带理由"; fail=1; fi
  fi
  [ "$status" = "PASS" ] || continue
  if [ ! -s "../$ev" ] && [ ! -s "$ev" ]; then
    echo "FAKE-PASS $gid: 证据文件缺失或为空: $ev"; fail=1; continue
  fi
  # R8:门证据文件本身必须在 evidence/HASHES.tsv 登记 sha256 指纹
  # (只登 raw 不登门证据 = 多个门的证据可被整体掉包而零反应,实测漏网过)
  if ! awk -v p="$ev" -F'\t' '$2==p{f=1} END{exit f?0:1}' ../evidence/HASHES.tsv 2>/dev/null; then
    echo "R8-FAIL $gid: 门证据文件未登记指纹(evidence/HASHES.tsv): $ev"; fail=1
  fi
  # R11:证据正文引用的 evidence/ 内文件必须真实存在(引用不存在的文件/伪造作业记录=多卡连环漏网;
  # 作业号本身的 sacct 存在性核验是卡级收尾义务,机械检查管不到调度器,要把核验输出写进证据)
  for ref in $(grep -oE 'evidence/[A-Za-z0-9._/-]+' "../$ev" 2>/dev/null | sed 's/[.,]$//' | sort -u | head -80); do
    [ -e "../$ref" ] || { echo "R11-FAIL $gid: 证据引用了不存在的文件: $ref"; fail=1; }
  done
done < <(tail -n +2 state/GATES.tsv)
# R8 反向:evidence/ 下每个文件都必须已登记(塞未登记新文件/换靶洗白=多卡实测漏网)
if [ -d ../evidence ]; then
  while IFS= read -r ef; do
    rel="evidence/${ef#../evidence/}"
    [ "$rel" = "evidence/HASHES.tsv" ] && continue
    case "$rel" in */.gitkeep) continue ;; esac
    if ! awk -v p="$rel" -F'\t' '$2==p{f=1} END{exit f?0:1}' ../evidence/HASHES.tsv 2>/dev/null; then
      echo "R8-REV-FAIL: evidence/ 下存在未登记文件: $rel"; fail=1
    fi
  done < <(find ../evidence -type f)
fi
if [ "$fail" -eq 0 ]; then echo "checks: OK"; fi
exit "$fail"
