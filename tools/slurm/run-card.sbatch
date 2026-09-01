#!/usr/bin/env bash
#SBATCH --job-name=lda-card
#SBATCH --partition=cpu-scavenger
#SBATCH --cpus-per-task=2
#SBATCH --mem=6G
#SBATCH --time=1-00:00:00
#SBATCH --output=%x-%j.out
#SBATCH --requeue

# Submit one card run through Slurm instead of running it on a shared login or
# dev node. The host side of a run is only an orchestrator - every build, test
# and benchmark executes inside an E2B sandbox - so it asks for little local CPU
# and memory. It is preemption-safe on a scavenger partition because the flow is
# resumable: a requeued job re-executes the same command and the run continues
# from hmz kept state rather than restarting.
#
#   sbatch --export=ALL,PKG=libcairo2,WORKSPACE=/path/to/ws,RUN_ID=cairo-001 \
#          tools/slurm/run-card.sbatch
set -uo pipefail

PKG="${PKG:?PKG required}"
WORKSPACE="${WORKSPACE:?WORKSPACE required}"
RUN_ID="${RUN_ID:?RUN_ID required}"
REPO="${LDA_REPO:-/fact_data/yisun/LDA-HM}"

# Evidence lives outside the flow source, on redundant storage. Caches go to
# scratch; nothing large is written to /tmp (a ramdisk on these nodes).
export LDA_RESULTS_ROOT="${LDA_RESULTS_ROOT:-/fact_data/yisun/Linux-Development-Agent-Runs}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/scratch/$USER/cache}"
export PATH="$HOME/.venvs/ldahm/bin:$PATH"
export PYTHONUNBUFFERED=1
mkdir -p "$XDG_CACHE_HOME" "$LDA_RESULTS_ROOT"

set -a
. "$HOME/.config/lda-hm/e2b.env"
# The Claude group of the lab gateway (Anthropic dialect). The subscription
# OAuth env files carry no base URL, so they reach api.anthropic.com and are
# refused from inside the cluster; this file is what makes the CLI usable.
. "$HOME/.config/lda/factlab-claude.env"
set +a
export LDA_AGENT_BACKEND=claude
export LDA_AGENT_MODEL="${LDA_AGENT_MODEL:-claude-opus-4-8}"

echo "$(date -Is) slurm job ${SLURM_JOB_ID:-none} on $(hostname): $PKG run $RUN_ID"
cd "$REPO" || exit 1
exec bin/lda-hmz-drive "$WORKSPACE" "$RUN_ID"
