# Linux Development Agent (LDA)

Linux Development Agent is an evidence-driven system for researching and optimizing Linux distribution packages. Its current campaign targets performance-sensitive Ubuntu 26.04 libraries while preserving drop-in package compatibility.

LDA combines a dynamic portfolio manager, a fixed per-package engineering mission, deterministic compatibility and benchmark gates, isolated E2B execution, and append-only recovery state. An agent may propose work and produce candidates, but it cannot alter compatibility fences, accept its own candidate, rewrite benchmark evidence, publish a package, or decide that a run has converged.

See [docs/architecture.md](docs/architecture.md) for component and trust-boundary details.

## Goals

- Optimize selected Ubuntu packages and produce installable `.deb` candidates.
- Preserve package name, version contract, architecture, installation paths, SONAME, exported symbols, symbol versions, dynamic dependencies, headers, pkg-config metadata, ABI, API, and FFI behavior.
- Measure candidate performance from raw samples on the intended CPU profile.
- Use portfolio workloads, rather than summed microbenchmark gains, as the system-level reward.
- Make every decision recoverable and auditable from structured state, events, hashes, and artifact references.
- Fail closed when E2B, source, build, Judge, benchmark, hardware, or rollback evidence is absent.

## Non-goals

- Replacing official interfaces with a new API or requiring application source changes.
- Allowing an LLM to waive a Fence or Judge failure.
- Building packages on the controller host or silently falling back to Docker or the local machine.
- Treating a research ranking as verified package metadata.
- Treating a local microbenchmark win as a releasable system optimization.
- Claiming that the current Top-10 campaign has completed or produced an accepted speedup.

## Flow

```text
Argus Life Loop
  observe -> summarize -> manager decision -> policy validation
  -> execute -> classify -> learn -> capability check -> convergence
                         |
                         v
Fixed LDA Mission
  official baseline -> manifest -> profile -> hypothesis -> plan
  -> candidate build -> local verify -> independent review -> trace audit
                         |
                         v
Deterministic clean Judge
  package/ABI/API/FFI -> anti-cheat -> benchmark evidence -> install/rollback
```

The outer loop can create, reprioritize, pause, resume, and stop missions. The inner mission is fixed: package optimization cannot skip directly from an agent proposal to acceptance. Convergence is evaluated by deterministic budget, progress, mission, cycle, and portfolio rules.

## Quick Start

Python and the tested E2B SDK version are listed in `pyproject.toml` and `requirements.txt`. Production execution requires credentials supplied through the process environment or an ignored operator-only configuration file. Never commit credentials or place them in prompts, artifacts, templates, snapshots, or event logs.

```bash
export E2B_API_URL="https://e2b.fact-lab.work"
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_ACCESS_TOKEN="dummy"
export E2B_API_KEY="<injected by the runtime>"

./lda e2b preflight
./lda template build --all
./lda research ingest research/
./lda run --flow argus-humanize \
  --run-id ubuntu-2604-campaign \
  --campaign-input "/absolute/path/to/research-input.md"
```

`lda run` performs preflight, campaign ingestion, Controller sandbox creation, input upload and hash verification, Qualification, canary authorization, the Argus loop, fixed missions, Judge execution, outcome classification, and deterministic convergence. It exits nonzero when a mandatory gate is unavailable.

For tests only, the fake data plane is explicit:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
```

The fake client is not a production fallback and cannot establish E2B, hardware, build, or performance validity.

## CLI

```text
lda e2b preflight
lda e2b reap --run-id RUN_ID
lda template build --all
lda research ingest PATH...
lda run --flow FLOW_ID --run-id RUN_ID --campaign-input PATH
lda argus world --run-id RUN_ID
lda argus missions --run-id RUN_ID
lda argus capabilities --run-id RUN_ID
lda status --run-id RUN_ID
lda logs --run-id RUN_ID
lda resume --run-id RUN_ID
lda cancel --run-id RUN_ID
lda report --run-id RUN_ID
```

Commands read state beneath the root selected by the hidden test/development `--root` option. Production campaigns normally use a dedicated run directory as their root.

## Campaign Qualification

The campaign report is evidence for candidate selection, not an authoritative package database. LDA copies the original input into artifacts, records its SHA-256, uploads the same bytes to E2B, and verifies the uploaded hash.

The current campaign encodes ten initial candidates and restricts first execution to two canaries: `libcairo2` and `libsoup-3.0-0`. Qualification independently checks binary metadata, source mapping, dependency metadata, a fixed Ubuntu source snapshot, source unpacking, and a clean source rebuild. Only then may canary missions start.

The remaining eight packages are not released into the Mission Graph until both canaries have deterministic Judge success and accepted measured system evidence. Missing references or boolean claims without evidence remain blockers.

## Judge And Fence

The Judge is not an agent and contains no LLM. The canary Judge receives official and candidate runtime/development `.deb` files in a separate no-secret, no-network sandbox and compares:

- package, version, architecture, paths, and control declarations;
- SONAME, dynamic exports, symbol versions, and `NEEDED` entries;
- installed headers and pkg-config metadata;
- candidate installation and official rollback;
- a precompiled C `dlopen`/`dlsym` probe and Python `ctypes` loading;
- package, probe, and Judge script SHA-256 values;
- secret exposure, `LD_PRELOAD`, control changes, and untracked binaries.

Any missing check fails closed. Generic non-canary packages remain blocked until a package-specific immutable manifest and Judge adapter exist.

## Benchmark Reward

Canary microbenchmarks use fixed warmups, repeated raw samples, deterministic inputs, and confidence bounds. A candidate must satisfy the configured micro threshold and hardware checks. End-to-end workloads are guardrails and portfolio geomean is the outer-loop reward.

LDA never adds library speedups together. A `LOCAL_WIN` is not a release. Top-10 expansion requires both canaries to record `SUCCESS_SYSTEM`, accepted benchmark evidence, at least the configured portfolio geomean, and the configured count of improved workloads.

## Recovery And Artifacts

Each run uses this layout:

```text
RUN_ROOT/
  .lda/
    world.json
    events.jsonl
    artifacts/
      campaign-input/
        manifest.json
        <original input>
      qualification.json
      <content-addressed artifacts>
```

`world.json` is an atomic structured snapshot. `events.jsonl` is append-only and hash chained; event payloads pass through the secret redactor. Agent sessions, mission attempts, ledgers, capability state, budgets, and convergence signals live in World State. A restarted supervisor loads this state instead of relying on model memory.

Builder and Capability Builder sessions can resume. Manager, summarizer, planner, reviewer, and outcome roles use fresh threads at their defined independence boundaries.

## Capability Lifecycle

Capabilities are versioned, hashed, scoped additions such as profiler adapters, build adapters, benchmark generators, dependency tests, FFI checkers, workloads, or dispatch helpers.

```text
PROPOSED -> POLICY_APPROVED -> BUILDING -> ISOLATED_TEST
-> ADVERSARIAL_REVIEW -> CAPABILITY_JUDGE -> ACTIVE
```

Transitions cannot be skipped. Isolated tests must pass before review, and only a passing Capability Judge decision can activate a capability. `ACTIVE` and `REJECTED` are terminal.

## Current Status

Implemented and covered by the local test suite:

- structured Argus actions and deterministic policy validation;
- fixed mission contracts and candidate attempt handling;
- E2B client, shared gateway adapter, metadata, leases, reconnect, reap, and preflight checks;
- AgentFactory thread independence and persistent Builder session recovery;
- campaign hashing, fixed source bundle checks, Qualification checkpoints, and canary release gates;
- deterministic canary benchmark parsing and clean runtime/development package Judge;
- World State snapshots, append-only events, recovery, convergence, and capability activation gates.

Known limitations as of 2026-08-26:

- The real Top-10 campaign has not completed and no accepted Ubuntu 26.04 speedup is claimed.
- The latest formal campaign attempt stopped during canary Qualification because an E2B streaming command reached its gateway deadline while installing build dependencies. Long package operations now use sandbox-side checkpoint files and short Controller polls; this mitigation still needs validation after the gateway recovers.
- The CLI creates a Controller sandbox and uploads campaign state to it, but the Python supervisor loop is still driven by the launching process. Full self-hosted Controller execution inside E2B remains unfinished.
- The checked-in `lda-e2e` template does not yet install a `run-portfolio-e2e` harness, so Portfolio E2E cannot currently produce valid production evidence from that template.
- The dedicated agent-runtime template input is minimal; real agent smoke has used a separately registered Ubuntu 26.04 runtime template containing Codex CLI.
- Snapshot/fork behavior uses an artifact fallback for the files explicitly captured by the client; it is not a general filesystem snapshot implementation.
- The tested gateway SDK is pinned to the available compatible version rather than the originally requested newer version.
- Hardware compatibility checks can validate exposed CPUID features, but a virtualized CPUID is not physical CPU attestation.

## Acknowledgements And References

The fixed LDA Mission structure is informed by ideas from Humanize-style iterative engineering flows. The currently accepted compatibility CLI flow identifier is `argus-humanize`; set `LDA_FLOW_ID=argus-humanize` when invoking the present CLI. Argus-inspired observe/decide/review patterns inform the outer manager, while all acceptance authority remains deterministic LDA policy and Judge code.
