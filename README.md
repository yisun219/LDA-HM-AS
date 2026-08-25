# LDA Pure Humanize

This branch implements the E2B-native production flow used to research Ubuntu
26.04 package optimizations. It preserves the older `lda_hm` package only for
artifact compatibility; the production command is `lda`, backed by `src/lda`.

```text
Pure Humanize
= multi-Mission Humanize harness
+ LDA Mission flow
+ frozen Research Snapshot
+ frozen Mission Queue
+ independent deterministic Judge
+ E2B-only execution
```

ABI, API, and FFI compatibility are hard fences. A candidate that changes a
SONAME, exported symbol, symbol version, public type layout, calling convention,
metadata, install path, precompiled consumer behavior, or Debian relationship is
rejected before performance is considered.

## Prerequisites

- Python 3.12
- `uv`
- E2B SDK `2.45.0`
- a private Codex login at `~/.codex/auth.json`, mode `0600`
- E2B credentials in the environment or the private file below

The E2B key may be stored outside Git at `~/.config/lda-hm/e2b.yaml`:

```yaml
e2b_api_key: "..."
```

The file must be mode `0600`. The key is injected only into the Controller.
Agent Runtime receives Codex authentication; Workspace, Judge, and E2E
Sandboxes receive neither model nor E2B credentials.

Install the locked environment:

```bash
uv sync --extra test
source .venv/bin/activate
```

## Build and verify E2B

```bash
lda template build --all
lda e2b preflight
```

Preflight creates a real Sandbox, runs OS/CPU checks, tests files and foreground
and background commands, reconnects by Sandbox ID and PID, creates and restores
a Snapshot, tests fork when supported, validates metadata, and reaps every
Sandbox carrying its `preflight_id`. It never falls back to Docker or the host.

## Start a Pure Humanize run

Research input can be JSON/YAML with structured hints or plain text. Structured
hints should name the exact Ubuntu binary package used by the inventory.

```bash
lda research ingest research/
lda portfolio plan \
  --research-snapshot RESEARCH_SNAPSHOT_ID \
  --inventory configs/package-inventory.yaml \
  --limit 5

lda run \
  --flow pure-humanize \
  --research-snapshot RESEARCH_SNAPSHOT_ID \
  --inventory configs/package-inventory.yaml \
  --missions configs/missions \
  --queue-limit 5
```

`lda run` verifies/builds missing Templates, creates an E2B Volume, launches
`lda-controller` inside E2B, injects the E2B key and a generated capability
signing key only into that Controller, injects Codex authentication only into
Agent Runtime Sandboxes, returns the Run ID, and starts the frozen Mission Queue.

Run operations:

```bash
lda status --run-id RUN_ID
lda logs --run-id RUN_ID
lda resume --run-id RUN_ID
lda cancel --run-id RUN_ID
lda e2b reap --run-id RUN_ID
lda report --run-id RUN_ID
```

State is transactionally stored in SQLite, mirrored as readable run JSON, and
audited in append-only JSONL on the Run's E2B Volume. Candidate source patches,
Agent output, traces, tests, and benchmark samples are content-addressed.

## Execution model

Each run follows this state sequence:

```text
RUN_CREATED -> E2B_PREFLIGHT -> RESEARCH_FROZEN -> PORTFOLIO_PLANNED
-> MISSION_QUEUE_FROZEN -> MISSION_BASELINE -> PROFILE -> HYPOTHESIS
-> CANDIDATE_FORK -> BUILD -> LOCAL_VERIFY -> ADVERSARIAL_REVIEW
-> CLEAN_JUDGE -> NEXT_MISSION -> PORTFOLIO_E2E
-> RELEASE_READY | COMPLETED_WITHOUT_RELEASE
```

Research Curator, Portfolio Planner, Mission Planner, Profiler, Builder,
Reviewer, and Trace Auditor are independent AgentFactory products. Builder keeps
one thread per Candidate. Reviewer and Trace Auditor always receive new threads,
cannot see Builder conversation, cannot modify source, and cannot accept a
Candidate. Only the deterministic Judge changes acceptance state.

The scoped Tool Gateway signs short-lived HMAC capabilities bound to run,
mission, candidate, role, workspace, tools, and expiration. Builder can access
only its Workspace tools. Reviewer can read only sealed artifacts. No Agent can
call acceptance, baseline/test mutation, unscoped Sandbox creation, secret read,
or release publication operations.

Judge order is fixed:

```text
Level 0 upstream self tests
Level 1 ABI/API/FFI
Level 2 original binary with candidate library
Level 3 reverse dependency build/test
Level 4 application install/launch/smoke
Level 5 E2E guardrail
```

Micro benchmarks use ten warmups, thirty paired randomized samples, fixed seed,
CPU affinity, raw sample retention, geometric paired ratios, and bootstrap 95%
confidence intervals. Micro wins are local rewards. Default release requires
Portfolio E2E and never adds independent micro speedups together.

## Templates

- `lda-controller`: scheduler, state, gateway, artifacts, E2B SDK
- `lda-agent-runtime`: Python 3.12, Codex CLI `0.149.1`, schemas, prompts, Intel skills
- `lda-base`: Ubuntu 26.04 compilers, Debian tooling, perf and ABI/FFI tools
- `lda-judge`: immutable deterministic fences derived from `lda-base`, no Codex
- `lda-e2e`: clean Ubuntu 26.04, Chromium, Playwright, web and GUI fixtures

Intel Performance Skills are pinned to commit
`e9d0b6410fb1ad7a50fb81e0868fd23ae886882c`. Public packages may use baseline
ISA plus runtime dispatch, IFUNC, AVX2, or AVX-512 paths with a compatible
fallback. Global `-march=native` is rejected by trace audit.

## Tests

```bash
uv run pytest -q
```

Tests cover FakeE2B, FakeCodex, shared gateway headers, Sandbox leases and
reaping, Agent resume and independence, frozen queues, ABI/FFI rejection,
benchmark statistics, anti-cheat, convergence, crash recovery, secret
redaction, concurrency limits, and state-machine transition guards. Real E2B
tests live under `tests/e2b` and are never replaced by mocks.
