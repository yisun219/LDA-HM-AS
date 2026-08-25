# LDA-HM

LDA-HM is an independent, Humanize-inspired flow for long-running agent work.
It is not derived from the repository's `main` branch and does not vendor the
Humanize or Flowverse source trees.

The initial implementation establishes the control plane that later revisions
can specialize for autoresearch:

- three explicit stages: idea, plan, and RLCR execution;
- persistent writer sessions and fresh reader/reviewer sessions;
- immutable plan and git anchors;
- resumable JSON state and per-round artifacts;
- a deterministic 15-gate boundary before semantic review;
- regular review, full alignment, drift recovery, code review, finalize, and
  methodology-analysis phases;
- runtime-neutral protocols for plugging in a concrete agent backend later.

No agent loop starts automatically. The package only provides orchestration
and state primitives until `lda run` is invoked with an E2B template and an
agent harness command. Production execution refuses host-shell fallback.

## Executable LDA run

Build `lda-base` through the E2B gateway:

```bash
export E2B_API_URL=https://e2b.fact-lab.work
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_API_KEY="..."
python sandbox/build_template.py
```

Install and validate a package card, then run the complete flow. The command
creates an E2B sandbox, overlays the checked-in harness and skills, prepares a
Ubuntu 26.04 source workspace, captures a baseline, and then runs the full
Builder -> Fence -> Fresh Reviewer loop:

```bash
python -m lda_hm.cli init-card ./work examples/libpng-card.json
export LDA_AGENT_COMMAND="/opt/lda/harness/lda-agent-harness.sh"
# Source a private Agent gateway environment when the run does not use a
# credential-file login. Never place this file in the repository or template.
# set -a; source ~/.config/lda/factlab-claude.env; set +a
python -m lda_hm.cli run ./work \
  --run-id libpng-production-001 \
  --results-root /fact_data/yisun/Linux-Development-Agent-Runs \
  --task "Optimize libpng for Ubuntu 26.04" \
  --contract "Advance the highest-priority unmet acceptance criterion"
```

The harness accepts `--prompt-file`, `--role`, and `--session`, and returns one
response on stdout. Every build, test, benchmark, upload, and agent turn is
executed in E2B. The flow will not silently run on the host. The default Agent
backend selection and model behavior are described below.

Resume an interrupted run by invoking the same command with the same
`--run-id`. A fresh Sandbox reconstructs the deterministic Snapshot baseline,
reapplies the durable candidate patch, restores the Builder trace, and resumes
pending deterministic review without repeating the completed Builder turn.
Changing the task card or baseline digest requires a new run ID.

Production run state and compact evidence belong in a separate result
repository. Set `--results-root` (or `LDA_RESULTS_ROOT`) to that repository.
Large immutable artifacts stay outside Git; their SHA256 and storage location
are recorded with the run.

The harness selects an environment-backed Claude endpoint first, then Codex,
then Pi. It can also be pinned with `LDA_AGENT_BACKEND=claude|codex|pi`.
The validated Claude default is `claude-opus-4-8`; override it with
`LDA_AGENT_MODEL` when another gateway exposes a different model set.
Claude, Codex, and Pi sessions all run inside E2B; private credentials are
injected only when the Sandbox starts.

The libpng card uses the production `iso_snapshot` contract anchored to Ubuntu
26.04 Desktop build `20260423.1`, Snapshot source version `1.6.57-1`, and an
immutable E2B template ID; see docs/BASELINE.md.

## Development

```bash
python -m unittest discover -s tests -v
```

## Repository layout

```text
src/lda_hm/
  artifacts.py   durable run artifacts and atomic writes
  flow.py        state machine and transition rules
  gates.py       deterministic gate model
  prompts.py     backend-neutral stage prompt contracts
  runtime.py     Agent and Session protocols
  stages.py      Gen-Idea, Gen-Plan, and RLCR stage entry points
  types.py       configuration, state, and review schemas
docs/FLOW.md     architecture and invariants
tests/           state-machine and persistence tests
```
