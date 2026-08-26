# Linux Development Agent Architecture

This document describes the implemented LDA control model, execution boundaries, persisted state, and the gap between the target deployment and the current repository state.

## Design Invariants

1. ABI, API, FFI, package identity, and installation compatibility are immutable Fences.
2. Agents are advisory and generative. Deterministic code owns authorization, Judge decisions, benchmark interpretation, release, and convergence.
3. Package build, test, profiling, and Judge commands run in E2B sandboxes. Production fails closed if E2B is unavailable.
4. A model cannot accept its own output. Reviewer histories are independent from Builder histories, and Judge uses no model.
5. Research input is evidence, not truth. Package facts must be revalidated against the fixed Ubuntu snapshot.
6. World State contains structured facts and artifact references, never hidden model reasoning.
7. Microbenchmark speedups are local evidence. Only measured end-to-end portfolio results represent system reward.

## Two-level Control Flow

```text
BOOTSTRAP
  |
  v
OBSERVE -> SUMMARIZE -> MANAGER_DECISION -> POLICY_VALIDATE
                                              |
                               rejected <-----+-----> accepted
                                                         |
                                                         v
                                                  EXECUTE_ACTION
                                                         |
                               +-------------------------+------------------+
                               |                                            |
                               v                                            v
                     fixed package Mission                         non-package action
                               |                                  (research, mission,
                               v                                   capability, E2E)
                         deterministic Judge
                               |
                               v
                     CLASSIFY_OUTCOME -> UPDATE_MEMORY
                               |
                               v
                    CAPABILITY / PORTFOLIO CHECK
                               |
                               v
                    deterministic convergence
```

The Argus outer loop observes the complete persisted state every life cycle and selects one allowed action. `PolicyEngine` validates the action against shape, target, evidence, concurrency, and budget constraints before any side effect occurs.

The Manager may request:

- mission creation, reprioritization, pause, resume, stop, or candidate continuation;
- a new versioned research snapshot;
- capability proposal or capability mission start;
- portfolio E2E execution;
- a stop proposal.

It cannot modify a Fence, accept a candidate, change the official baseline, alter measured evidence, publish a package, or stop the run directly.

## Fixed LDA Mission

Every package candidate follows the same ordered mission contract:

```text
OFFICIAL_BASELINE
-> ABI/API/FFI_MANIFEST
-> MICROBENCH_GENERATION
-> E2E_MAPPING
-> PROFILE
-> HYPOTHESIS
-> PLAN
-> FORK_CANDIDATES
-> BUILD
-> LOCAL_VERIFY
-> ADVERSARIAL_REVIEW
-> TRACE_AUDIT
-> CLEAN_JUDGE
-> OUTCOME
```

The current implementation creates an immutable mission contract hash, a candidate record, a disposable work sandbox, advisory planning/build/review sessions, deterministic build evidence, benchmark artifacts, and an independent Judge sandbox.

For the two canaries, builds use the pinned source bundle and must emit both the runtime and development `.deb`. A missing target package, development package, extraction, benchmark, or Judge artifact is a failed attempt. Generic packages use the Debian source builder but remain fail closed at acceptance until a package-specific immutable Judge adapter exists.

## World State

`WorldState` is the recovery boundary for a run:

```text
WorldState
|- run_id / life_cycle / active
|- RunBudget
|- HardwareProfile
|- research_snapshots
|- package_inventory
|- missions / candidates
|- benchmark_ledger / outcome_ledger
|- capabilities
|- fence_versions
|- portfolio_e2e
|- convergence_signals
|- campaign_input / qualification
`- agent_sessions
```

The controller writes `.lda/world.json` through an atomic temporary-file replacement. `.lda/events.jsonl` is append-only. Each event contains identity, run/cycle, actor, type, input/output references, timestamp, previous hash, redacted payload, and its own stable hash.

Recovery loads `world.json`, restores persistent agent session references, and requeues retryable invalid-evidence missions. It does not depend on an agent remembering earlier turns.

## AgentFactory

`AgentFactory` converts immutable `AgentSpec` values into scoped E2B runtime sandboxes and structured Codex CLI calls. Every sandbox carries project, run, cycle, mission, candidate, capability, role, template, timeout, and unique lease metadata.

| Role | Thread policy | Independence boundary |
| --- | --- | --- |
| Argus Manager | new each life cycle | manager cycle |
| World State Summarizer | new each cycle | summary cycle |
| Mission Planner | new each mission | mission |
| Builder | persistent | candidate |
| Reviewer | fresh each round | reviewer round |
| Outcome Classifier | new each result | mission outcome |
| Capability Builder | persistent | capability |

Persistent Builder sessions store both E2B sandbox and observed Codex thread identifiers in World State. Reviewers use a different session key and cannot inherit Builder history. Agent outputs are parsed against role-specific JSON schemas; malformed output does not become a policy decision.

## E2B Trust Boundaries

The target production topology is:

```text
Controller Sandbox
|- Manager and Summarizer Agent Runtime Sandboxes
|- Planner / Builder / Reviewer Agent Runtime Sandboxes
|- Candidate Work Sandboxes
|- Capability Work Sandboxes
|- Judge Sandboxes
`- Portfolio E2E Sandboxes
```

| Boundary | Network | Secrets | Model | Responsibilities |
| --- | --- | --- | --- | --- |
| Bootstrap/controller process | gateway access | E2B controller credential | no acceptance authority | create/reconnect/reap sandboxes, persist state |
| Agent runtime | enabled for configured provider | model credential only | Codex CLI | structured planning, building, reviewing, classification |
| Candidate work | enabled for pinned package mirror | none | none | source, build, local verify, profiling, benchmark |
| Judge | disabled | none | none | deterministic compatibility, FFI, install and rollback checks |
| E2E | workload-dependent | none | none | system workload measurement |

`E2BClient` injects model credentials only for recognized agent roles. Candidate, Qualification, E2E, and Judge sandboxes receive no model credential. Judge is excluded from internet-enabled roles. Event payloads pass through the secret redactor.

The shared gateway adapter preserves SDK sandbox and access headers and adds the shared-gateway API header idempotently when the control and sandbox URLs are the same.

## Preflight

Production `lda run` invokes preflight first. The implemented checks cover:

- tested SDK version and gateway connection;
- control-plane create and data-plane command execution;
- filesystem read/write;
- background PID and reconnect;
- artifact snapshot and fork fallback;
- metadata propagation;
- network restriction probe;
- hardware feature fingerprint;
- orphan reaping;
- template manifest and kill.

Any failed check blocks the run. The artifact snapshot fallback currently captures an explicit file set and is not equivalent to a native full-filesystem snapshot.

## Campaign And Qualification

Campaign preparation copies the research input into `.lda/artifacts/campaign-input/`, records byte count, line count and SHA-256, parses candidate records, and writes a manifest. The same bytes and manifest are uploaded into the Controller and Qualification sandboxes and rehashed after upload.

The initial package set is:

```text
libgtk-4-1
libgtk-3-0t64
gnome-shell
libreoffice-core
sssd-common
libcairo2
gnome-settings-daemon
gstreamer1.0-plugins-good
ibus
libsoup-3.0-0
```

Qualification validates report claims against the fixed Ubuntu 26.04 snapshot. It records binary metadata, source mapping, dependency metadata, build tools, source index evidence, uploaded source hashes, source unpack evidence, clean rebuild output, and blockers. Checkpoints allow completed package rows to survive a controller restart.

Only `libcairo2` and `libsoup-3.0-0` are initially eligible. Canary mission authorization requires referenced evidence for package/source metadata, the fixed snapshot, source unpack, and clean source rebuild. Performance and replacement evidence are produced later by the mission and Judge.

The remaining packages enter the Mission Graph only after both canaries have `SUCCESS_SYSTEM`, valid accepted benchmark evidence, the configured portfolio geomean threshold, and enough improved workloads.

## Deterministic Judge

The canary Judge transfers four opaque package files into a fresh offline Judge sandbox:

```text
official runtime .deb
official development .deb
candidate runtime .deb
candidate development .deb
```

The Judge compares package/version/architecture, payload paths, control declarations, SONAME, exported dynamic symbols, symbol versions, `NEEDED`, headers, and pkg-config metadata. It installs official then candidate packages, runs a template-built C `dlopen`/`dlsym` probe and Python `ctypes`, reinstalls the official packages, and confirms rollback.

The evidence includes hashes for all package files, Judge script and precompiled probe, command output hashes, environment facts, and anti-cheat findings. The controller independently compares reported package and script hashes with the bytes it transferred. Any absent or false required check rejects the candidate.

## Benchmark And Outcome

Microbenchmark configuration defaults to ten warmups and thirty samples. Evidence retains raw official/candidate samples and computes speedup plus a lower confidence bound. Invalid, insufficient, or nonpositive samples are rejected.

The canary harness records hardware metadata and checks exposed CPUID capabilities. Virtualized matching features establish architectural compatibility, not physical hardware identity. A hardware identity blocker prevents benchmark acceptance.

Portfolio results are a mapping of workload names to measured speedup ratios. LDA computes their geometric mean and improved-workload count. It does not add microbenchmark improvements.

Outcome classification distinguishes compatibility failure, invalid benchmark, regression, local success, system success, capability gap, and no optimization space. Numeric speedup alone cannot produce `SUCCESS_SYSTEM`; benchmark `accepted` must be explicitly true and Judge must be valid.

## Capability Lifecycle

Capabilities are versioned and content hashed. Their deterministic lifecycle is:

```text
PROPOSED
-> POLICY_APPROVED
-> BUILDING
-> ISOLATED_TEST
-> ADVERSARIAL_REVIEW
-> CAPABILITY_JUDGE
-> ACTIVE
```

The registry forbids skipped and repeated transitions. Passing isolated tests must be recorded at `ISOLATED_TEST`. Later stages require that evidence, and activation requires a passing Capability Judge decision. `ACTIVE` and `REJECTED` cannot transition further.

The state machine and policy hooks are implemented. A complete E2B Capability Builder/Test/Review/Judge executor is not yet wired through the full outer loop.

## Convergence

Only `ConvergenceEvaluator` ends a run. Current deterministic stop conditions include:

- maximum life cycles;
- exhausted run budget;
- three quiet cycles;
- all high-priority missions terminated;
- portfolio geomean and improved-workload target reached.

A Manager stop proposal is recorded as a signal and has no direct stop authority.

## Artifacts

```text
RUN_ROOT/.lda/
|- world.json                  atomic recovery snapshot
|- events.jsonl               append-only hash-chained events
`- artifacts/
   |- campaign-input/
   |  |- manifest.json
   |  `- original research input
   |- qualification.json      checkpoint and release blockers
   `- <sha256>-<name>         content-addressed artifacts
```

Sandbox evidence paths are stored as references in Judge, benchmark, outcome, and event records. Secret values must never be artifact content or event input/output references.

## Current Deployment Gaps

The repository implements the control and evidence boundaries above, but the full target deployment is not complete:

- The launching process still executes the Python supervisor after creating the E2B Controller sandbox. Moving the supervisor process and persistent stores wholly into the Controller sandbox remains required.
- The checked-in E2E template has no executable portfolio harness at `run-portfolio-e2e`; current production Portfolio E2E therefore fails closed.
- The checked-in agent-runtime image is not the registered runtime used by the successful real Codex CLI smoke.
- A formal canary Qualification attempt reached an E2B streaming deadline during build-dependency installation before any package mission began. Long operations now use sandbox-side checkpoint files and short polling RPCs, pending real validation after gateway recovery.
- No Top-10 run, accepted canary speedup, or releasable optimized Ubuntu package is currently claimed.
- Generic package Judge adapters, reverse-dependency suites, and application-level workloads remain package-specific work.
