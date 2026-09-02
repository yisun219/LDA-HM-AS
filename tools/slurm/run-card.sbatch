#!/usr/bin/env bash
#SBATCH --job-name=lda-card
#SBATCH --partition=cpu-scavenger
#SBATCH --exclude=deep-space,quantum,natural-selection
#SBATCH --cpus-per-task=2
#SBATCH --mem=6G
#SBATCH --time=1-00:00:00
#SBATCH --output=/fact_data/yisun/Linux-Development-Agent-Runs/slurm/%x-%j.out
#SBATCH --requeue

# Submit one card run through Slurm instead of running it on a shared login or
# dev node. The host side of a run is only an orchestrator - every build, test
# and benchmark executes inside an E2B sandbox - so it asks for little local CPU
# and memory. It is preemption-safe on a scavenger partition because the flow is
# resumable: a requeued job re-executes the same command and the run continues
# from hmz kept state rather than restarting.
#
#   sbatch --export=ALL,PKG=libcairo2,WORKSPACE=/path/to/ws,RUN_ID=cairo-001 \
#          [,LDA_TASK_FILE=/path/to/task.txt] tools/slurm/run-card.sbatch
#
# Agent backend: LDA_AGENT_BACKEND=claude (default) or codex. Each backend reads
# its gateway credentials from a private file under ~/.config; nothing here.
set -uo pipefail

PKG="${PKG:?PKG required}"
WORKSPACE="${WORKSPACE:?WORKSPACE required}"
RUN_ID="${RUN_ID:?RUN_ID required}"
REPO="${LDA_REPO:-/fact_data/yisun/LDA-HM}"

# Evidence lives outside the flow source, on redundant storage. Caches go to
# scratch; nothing large is written to /tmp (a ramdisk on these nodes).
export LDA_RESULTS_ROOT="${LDA_RESULTS_ROOT:-/fact_data/yisun/Linux-Development-Agent-Runs}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/scratch/$USER/cache}"
export TMPDIR="${TMPDIR:-/scratch/$USER/lda-hm/$RUN_ID}"
export PATH="$HOME/.venvs/ldahm/bin:$PATH"
# Full GTK and LibreOffice package builds legitimately exceed the library-pilot
# one-hour setup default. Keep the sandbox alive across the remaining setup
# commands as well; both ceilings are still below the Slurm job limit.
export LDA_SETUP_TIMEOUT="${LDA_SETUP_TIMEOUT:-10800}"
export LDA_SANDBOX_TIMEOUT="${LDA_SANDBOX_TIMEOUT:-21600}"
export LDA_FENCE_TIMEOUT="${LDA_FENCE_TIMEOUT:-5400}"
export LDA_BUDGET_USD="${LDA_BUDGET_USD:-250}"
export LDA_STALL_LIMIT="${LDA_STALL_LIMIT:-5}"
export PYTHONUNBUFFERED=1
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR" "$LDA_RESULTS_ROOT"

set -a
. "$HOME/.config/lda-hm/e2b.env"
set +a

backend="${LDA_AGENT_BACKEND:-claude}"
case "$backend" in
  claude)
    set -a; . "$HOME/.config/lda/factlab-claude.env"; set +a
    export LDA_AGENT_MODEL="${LDA_AGENT_MODEL:-claude-opus-4-8}"
    ;;
  codex)
    set -a; . "$HOME/.config/lda/codex.env"; set +a
    export LDA_AGENT_MODEL="${LDA_AGENT_MODEL:-gpt-5.6-sol}"
    ;;
  *) echo "unsupported LDA_AGENT_BACKEND=$backend" >&2; exit 64 ;;
esac
export LDA_AGENT_BACKEND="$backend"
export LDA_AGENT_THINKING="${LDA_AGENT_THINKING:-high}"

extra=()
if [ -n "${LDA_TASK_FILE:-}" ]; then
  extra+=(--task "$(cat "$LDA_TASK_FILE")")
fi

echo "$(date -Is) slurm job ${SLURM_JOB_ID:-none} on $(hostname): $PKG run $RUN_ID backend=$backend model=$LDA_AGENT_MODEL"
cd "$REPO" || exit 1
exec bin/lda-hmz-drive "$WORKSPACE" "$RUN_ID" "${extra[@]}"
