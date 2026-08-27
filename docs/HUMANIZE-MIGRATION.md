# Humanize Adoption Status and Migration Path

## Honest status

LDA-HM is a faithful reimplementation of the Humanize control loop, not an
adoption of the Humanize harness. The numeric contract matches upstream
exactly (max 42 rounds, full alignment every 5, drift recovery at 2 stalls,
hard stop at 3, persistent Builder + fresh Reviewer, deterministic gate
boundary before semantic review, per-round BitLesson delta). What we own that
Humanize does not provide: E2B-only execution, the ABI/FFI/behavior/lifecycle
/security/equivalence fences, paired in-sandbox benchmarks with holdout and
certification, the task-card contract, and the Supervisor layer.

The standing instruction is "use humanize, do not maintain our own flow
harness". The gap and the concrete path are recorded here so the switch is a
bounded task, not a research project.

## Why not switched yet

- humanize2 (`hmz`) requires Python >= 3.12; dev1 currently runs 3.9.
  (Fixable with `uv python install 3.12` in user space.)
- `hmz` drives agent CLIs on the orchestrator host. LDA runs the CLIs inside
  E2B with credentials injected at sandbox start. Bridging that is the real
  migration work, and it has two supported seams (below).
- The fences, benchmarks, certification, and supervision in this repo are
  LDA-specific content either way; they survive the migration unchanged as
  flow content.

## Migration path (from reading humanize2 source and docs)

`hmz`'s extension model: a flow is a plain Python function marked `@flow`
taking `(agents, task)`; agents are typed in the signature; a git repo with a
`flows/` directory is a flowverse. No plugins, no YAML.

Two seams for E2B:

1. Seam A - keep CLIs on the host, land the work in E2B via hmz's anchor
   (seccomp/ptrace syscall replay). Implement an `E2BConfig(MachineConfig)`
   per `src/hmz/machines/SPEC.md` whose `start()` boots the sandbox with the
   e2b SDK and returns an `AnchorConfig` (~100-200 lines). Credentials then
   never enter the sandbox. Constraint: host must be Linux x86-64; one writer
   per workspace; whole-file sync.
2. Seam B - keep CLIs inside E2B (current LDA topology). Write an
   `E2BClaudeAgent` driver: subclass `CommandSessionBase` (or `SessionBase`)
   whose `_turn(prompt)` execs `claude -p --output-format stream-json
   --resume <id>` through the e2b SDK; `tests/stubs.py` in humanize2 shows a
   complete working backend in ~15 lines, a solid driver with resume and
   usage accounting is ~200-500 lines. Our `lda-agent-harness.sh` already
   implements exactly this turn contract, so the driver mostly wraps
   `CommandAgent`/`CommandSession` from this repo.

Then the LDA flow itself is ~100-150 lines of `@flow` code: persistent
builder session, fresh reviewer per round, our FenceSuite/benchmark verdicts
between turns, `@flow(resumable=True)` for round/budget state. `official/rlar`
and `official/humanize1:rlcr` are the reference shapes.

## Decision

Adopt Seam B when migrating (it preserves the E2B-resident credential and
execution model this repo's fences assume). Until then, this repo's engine
stays the production driver; anything added here should be written as flow
content (cards, fences, benchmarks, supervision) rather than engine features,
so it ports unchanged.
