# Pure Humanize Flow

```mermaid
flowchart TD
  CLI[Bootstrap CLI] --> C[lda-controller E2B]
  C --> RS[Frozen Research Snapshot]
  RS --> PP[Portfolio Planner Agent]
  PP --> MQ[Frozen Mission Queue]
  MQ --> M1[LDA Mission 1]
  MQ --> M2[LDA Mission 2]
  M1 --> PE[Portfolio E2E]
  M2 --> PE
  C --> AF[AgentFactory]
  AF --> A[Agent Runtime E2B]
  A -->|Capability Token| TG[Scoped Tool Gateway]
  TG --> W[Candidate Workspace E2B]
  W --> J[Fresh deterministic Judge E2B]
  J --> CR[Candidate Repository]
  PE --> RR[Default Release Repository]
```

The Bootstrap creates the Controller and its persistent E2B Volume. It is not an
execution fallback. After bootstrap, only the Controller holds E2B credentials.
All source operations are performed in Workspace Sandboxes through scoped Tool
Gateway calls. All acceptance checks run from scratch in Judge Sandboxes.

## Mission state

```mermaid
stateDiagram-v2
  [*] --> BASELINE
  BASELINE --> PROFILE
  PROFILE --> NOT_HOT: no measured hot path
  PROFILE --> HYPOTHESIS
  HYPOTHESIS --> CANDIDATES
  CANDIDATES --> BUILD
  BUILD --> LOCAL_VERIFY
  LOCAL_VERIFY --> BUILD: repair allowed
  LOCAL_VERIFY --> ADVERSARIAL_REVIEW
  ADVERSARIAL_REVIEW --> BUILD: advisory finding
  ADVERSARIAL_REVIEW --> REJECTED: cheating evidence
  ADVERSARIAL_REVIEW --> CLEAN_JUDGE
  CLEAN_JUDGE --> BUILD: deterministic repairable failure
  CLEAN_JUDGE --> INVALID: environment or trace invalid
  CLEAN_JUDGE --> REJECTED: fence or performance failure
  CLEAN_JUDGE --> LOCAL_WIN
  CLEAN_JUDGE --> SYSTEM_WIN
```

The Builder maintains one Codex thread for a Candidate. Each Reviewer and Trace
Auditor is a new thread and cannot access Builder conversation. Agent messages
never grant completion. Candidate acceptance is a `JudgeResult` derived from
fixed commands and benchmark policy.

## Persistent artifacts

- Research Snapshot and Mission Queue are frozen content-addressed objects.
- Mission Contract seals official source/deb hashes, paths, manifests, hardware,
  tests, workloads, budget, and acceptance policy before Builder access.
- SQLite stores the recoverable state snapshot.
- JSONL stores the append-only event history.
- E2B Volume stores state across Controller replacement.
- Candidate patches, traces, test results, benchmark samples, and Judge results
  are immutable objects referenced by SHA-256.

## Compatibility order

Judge executes SONAME, exported symbol, symbol version, `abidiff`,
`abi-dumper`/`abi-compliance-checker`, header compilation, public layout,
calling convention, pkg-config, CMake metadata, install paths, precompiled
binary, ctypes, cffi, Rust FFI, dlopen/dlsym, C/C++ source compatibility, and
Debian dependency relationship checks. Any failure ends performance evaluation.

## Benchmark policy

Micro and E2E commands must emit the `BenchmarkSeries` schema. The Controller
rejects fewer than ten warmups or thirty paired samples, nonpositive samples,
unpaired sequences, excessive coefficient of variation, insufficient micro
speedup, insufficient CI lower bound, and E2E regression. Portfolio release
requires at least two improved E2E workloads and a 1.01 geometric mean speedup.
