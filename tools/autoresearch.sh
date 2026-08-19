#!/usr/bin/env bash
# autoresearch 循环驱动器:在一张任务卡上逐轮调用引擎,直到全部检查点到终态或达轮数上限。
#
# 用法:
#   bash tools/autoresearch.sh <卡目录> [最大轮数]
#   最大轮数缺省时读卡内 .auto/config.json 的 maxIterations,再缺省为 5。
#
# 引擎命令用环境变量 ENGINE_CMD 覆盖(必须接受"提示词"作为最后一个参数):
#   默认 = 订阅版 Claude Code(无需 API key):
#     ENGINE_CMD='claude -p --model opus --effort max --dangerously-skip-permissions'
#   也可以指向任何能自主用工具干活的 agent CLI(Pi、Codex CLI 等)——换引擎不换协议。
#
# 纪律(与 FLOW.md 一致):
#   一卡一线:卡级互斥锁,第二个实例启动即拒绝;
#   撞用量限额自动进哨兵模式(每 15 分钟探测,恢复后同一轮续跑,不计轮数);
#   运行产物(锁/日志)只放卡内 work/.loop/,不污染证据区。
set -uo pipefail

CARD=${1:?用法: autoresearch.sh <卡目录> [最大轮数]}
CARD=$(cd "$CARD" && pwd)
[ -f "$CARD/.auto/prompt.md" ] || { echo "不是任务卡:缺 $CARD/.auto/prompt.md"; exit 1; }
MAXIT=${2:-$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("maxIterations",5))' "$CARD/.auto/config.json" 2>/dev/null || echo 5)}
ENGINE_CMD=${ENGINE_CMD:-'claude -p --model opus --effort max --dangerously-skip-permissions'}

# 运行产物放卡根 .lda-run/(驱动器专区,已 gitignore)——不放 work/:work/ 属于 Engineer 且收尾必须清零,
# 放那里会被清场误删(拉库实测踩过:Engineer 清 work/ 把在跑循环的锁和日志一起删了)
RUN="$CARD/.lda-run"; mkdir -p "$RUN"
LOG="$RUN/loop.log"; LOCK="$RUN/lock"; OUT="$RUN/iter.out"

if ! mkdir "$LOCK" 2>/dev/null; then
  OWNER=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [ -n "$OWNER" ] && kill -0 "$OWNER" 2>/dev/null; then
    echo "REFUSE: 该卡已有循环在跑(pid $OWNER)——一卡一线" | tee -a "$LOG"; exit 2
  fi
  rm -rf "$LOCK"; mkdir "$LOCK" 2>/dev/null || { echo "REFUSE: 锁竞争失败"; exit 2; }
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"; rm -f "$OUT"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

engine_probe() {  # 限额哨兵:每 15 分钟一发最小探针,恢复即返回
  echo "=== [$$] 撞用量限额,进入哨兵模式 $(date +%F-%H:%M) ===" | tee -a "$LOG"
  while :; do
    sleep 900
    R=$($ENGINE_CMD "只回复:ok" 2>&1 | tail -1)
    echo "[$$][sentinel $(date +%F-%H:%M)] ${R:0:120}" >> "$LOG"
    case "$R" in *ok*|*OK*|*Ok*) echo "=== [$$] 引擎恢复 ===" | tee -a "$LOG"; return;; esac
  done
}

for i in $(seq 1 "$MAXIT"); do
  while :; do
    STATE="$(cat "$CARD/.auto/prompt.md"; echo; echo '== GATES 当前 =='; cat "$CARD/.auto/state/GATES.tsv"; echo; echo '== 最近提交 =='; git -C "$CARD" log --oneline -5 2>/dev/null || echo '(本卡尚未 git init)')"
    echo "=== [$$] iter $i start $(date +%F-%H:%M) ===" >> "$LOG"
    # 角色提示词从 prompts/engineer.md 读取(可按需修改);缺失时用内置精简版
    ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    if [ -f "$ROOT_DIR/prompts/engineer.md" ]; then
      HEAD=$(sed -e "s|{{ITER}}|$i|g" -e "s|{{CARD_DIR}}|$CARD|g" "$ROOT_DIR/prompts/engineer.md")
    else
      HEAD="你是本任务卡 autoresearch 循环的第 $i 轮 Engineer。工作目录:$CARD
先读卡内任务书与仓库根 FLOW.md;推进未通过的检查点;产数脚本先提交再运行;每步 git 提交;
临时只放 work/;证据五要素入 evidence/(无作业标 NO-JOB)并更新 GATES.tsv;阻塞写 NOTES.md。"
    fi
    $ENGINE_CMD "$HEAD

$STATE" > "$OUT" 2>&1
    RC=$?
    cat "$OUT" >> "$LOG"
    if [ $RC -ne 0 ] && grep -qiE 'usage limit|session limit|limit reached|hit your.*limit|rate.?limit|too many requests|· resets' "$OUT"; then
      engine_probe; continue          # 限额=环境性中断:同一轮重跑,不计轮数
    fi
    if [ $RC -ne 0 ] && grep -qiE "can't reach|ENOTFOUND|connection lost|ECONNREFUSED|fetch failed|ETIMEDOUT" "$OUT"; then
      echo "[$$] iter $i 网络性失败(rc=$RC),120s 后同轮重试" | tee -a "$LOG"; sleep 120; continue
    fi
    break
  done
  M=$(cd "$CARD" && bash .auto/measure.sh 2>/dev/null | tail -1)
  T=$(sed 1d "$CARD/.auto/state/GATES.tsv" | awk -F'\t' '$2=="TODO"' | wc -l | tr -d ' ')
  echo "[$$][iter $i done] ${M:-METRIC ?} remaining_TODO=${T:-?}" | tee -a "$LOG"
  [ "${T:-1}" = "0" ] && { echo "ALL-GATES-TERMINAL after iter $i" | tee -a "$LOG"; break; }
done
echo "=== [$$] loop end $(date +%F-%H:%M) === 日志:$LOG"
