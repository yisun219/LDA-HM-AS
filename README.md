# LDA-HM: Linux Development Agent Flow

LDA-HM is an original workflow system that lets long-running AI agents
optimize Ubuntu packages under hard compatibility guarantees. It is built on
the Humanize methodology (persistent-builder / fresh-reviewer RLCR loop,
deterministic gates before semantic review, BitLesson knowledge base) and
extends it with layers designed for this problem: E2B-native execution,
ABI/FFI "surgical replacement" fences, statistically certified paired
benchmarking on noisy multi-tenant hosts, and an Argus-informed dynamic
supervision layer.

**Proven result**: run `libpng-2604-production-008` produced a drop-in
`libpng16-16t64` replacement for stock Ubuntu 26.04 measuring **+6.8% micro
decode** (held on a hidden holdout) and **+12.4% on the cairo desktop-stack
end-to-end path**, certified independently in two additional fresh sandboxes,
with SONAME/symbols/type-level ABI/Depends unchanged and byte-identical
decoded output.

Core capabilities:

- Humanize control loop implemented natively: idea, plan (with independent
  analyst convergence), RLCR execution; persistent Builder session, fresh
  Reviewer per judgement; drift recovery, full alignment, code review,
  finalize, methodology post-mortem; 42/5/2/3 numeric contract;
- a deterministic 15-gate boundary plus a 10-check fence suite (baseline and
  dependency tests, ABI/FFI/behavior/lifecycle/security/result-equivalence,
  evidence integrity, Builder trace audit) that must all pass before any LLM
  reviewer is consulted;
- BitLesson: a per-run lessons knowledge base with mechanically validated
  deltas, so rounds stop rediscovering the same failures;
- the Supervisor command node (指挥): per-round auditable decisions -
  continue / retarget / restart builder / add analyst / grace / abort -
  driven by run evidence (verdicts, benchmark trend, trace statistics,
  sandbox resources, spend) under fixed authority human > rules > LLM, plus
  a live Builder-turn watchdog with trace mirroring;
- statistically certified paired benchmarks: in-sandbox nonce-tagged timing,
  order-alternated pairing, Student-t CI certification, CPU-steal and
  pathological-spread environment gates, hidden holdout, and fresh-sandbox
  A/B/A' certification replications at finalize;
- integrity pinning of harness/baseline/fixtures with a host-side digest
  manifest re-checked before every fence and benchmark.

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
  --results-root ~/lda-runs \
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
`LDA_AGENT_MODEL` when another gateway exposes a different model set. A role
can be pinned independently with `LDA_AGENT_MODEL_DRAFTER`, `_PLANNER`,
`_ANALYST`, `_BUILDER`, `_REVIEWER`, or `_SUPERVISOR`, and a role's backend
with `LDA_AGENT_BACKEND_<ROLE>` (cross-vendor review: Claude builds, Codex
reviews). Claude, Codex, and Pi sessions all run inside E2B; private
credentials are injected only when the Sandbox starts.

Run-control knobs: `LDA_SUPERVISOR_LLM=0` disables LLM counsel (rules still
run), `LDA_BUDGET_USD` sets a hard spend ceiling, `LDA_CERT_REPLICATIONS`
sets fresh-sandbox certification replications (default 2, `0` disables), and
`<results-root>/runs/<run-id>/control.json` is the human command channel
(`{"action": "abort"}`, `{"contract": "..."}`, `{"action":
"restart_builder"}`), read at every round boundary.

Ranked optimization candidates for Ubuntu 26.04 live in
`data/candidates-ubuntu-2604.json` (top-30 by dependency-graph score, two
directions); libpng is the pipeline pilot.

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
