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
python -m lda_hm.cli run ./work \
  --task "Optimize libpng for Ubuntu 26.04" \
  --idea "$(cat idea.txt)" \
  --plan ./plan.txt \
  --goal-tracker ./goal-tracker.txt \
  --contract ./round-contract.txt
```

The harness accepts `--prompt-file`, `--role`, and `--session`, and returns one
response on stdout. Every build, test, benchmark, upload, and agent turn is
executed in E2B. The flow will not silently run on the host. Set
`LDA_AGENT_PROVIDER`/`LDA_AGENT_MODEL` and the corresponding provider
credential in the E2B environment before running.

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
