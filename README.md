# LDA Argus + Humanize Autoresearch Flow

This repository contains an executable two-level flow for Ubuntu library/package optimization:

```text
Argus life cycle (observe -> decide -> policy -> learn -> converge)
        |
        v
Humanize mission (baseline -> profile -> hypothesis -> build -> verify -> review -> judge)
        |
        v
Deterministic clean Judge (ABI/API/FFI fence + benchmark + anti-cheat)
```

Argus actions are restricted by `schemas/manager_action.json`. The Manager cannot change a Fence,
accept a candidate, alter benchmark data, publish a package, or decide convergence. State transitions
are appended to `.lda/events.jsonl` with a hash chain and `.lda/world.json` is an atomic recovery
snapshot. Model hidden reasoning is never persisted.

## Run

Production requires the injected E2B key and refuses to execute package builds on the controller host:

```bash
export E2B_API_URL="https://e2b.fact-lab.work"
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_ACCESS_TOKEN="dummy"
export E2B_API_KEY="..."
./lda e2b preflight
./lda template build --all
./lda research ingest research/
./lda run --flow argus-humanize \
  --campaign-input "/path/to/Ubuntu ISO 解析结果及包优化推荐.md"
```

For a real gateway smoke while the dedicated aliases are being registered, use the explicitly
selected existing template (this is a diagnostic fallback, not the production isolation layout):

```bash
./lda e2b preflight --e2b-template base
./lda run --flow argus-humanize --e2b-template base --package zlib
```

For deterministic local tests use the explicit fake E2B data plane:

```bash
./lda --root /tmp/lda-run run --flow argus-humanize --fake-e2b --package zlib --package sqlite3
./lda --root /tmp/lda-run status --run-id RUN_ID
./lda --root /tmp/lda-run argus missions --run-id RUN_ID
./lda --root /tmp/lda-run logs --run-id RUN_ID
./lda --root /tmp/lda-run resume --run-id RUN_ID
```

Other commands are `lda argus world`, `lda argus capabilities`, `lda report`, `lda cancel`, and
`lda e2b reap`.

## Implemented boundaries

- Shared E2B gateway preserves SDK headers and adds `X-API-KEY` only for a shared gateway.
- Preflight covers control/data plane, foreground/background commands, filesystem, PID reconnect,
  snapshot/fork fallback, metadata, network/hardware checks, orphan cleanup, template, and kill.
- AgentFactory creates scoped E2B runtime sandboxes and enforces independent session policies.
- Mission contracts are immutable; every candidate starts from one official baseline reference.
- ABI/API/FFI compatibility is a hard reject for SONAME, symbols, versions, headers, layouts,
  calling convention, package metadata, prebuilt binaries, and FFI checks.
- Micro benchmarks retain raw samples and confidence bounds; portfolio E2E is the system reward.
- Capability activation requires isolated testing, adversarial review, and Capability Judge approval.
- Secrets are scoped to controller/Codex processes and redacted from event payloads and child sandboxes.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The real E2B smoke test is opt-in when `E2B_API_KEY` is injected. Without it, production preflight
fails closed; the fake smoke path is not presented as a real E2B replacement.

The target gateway currently exposes the tested `e2b==2.10.2` SDK (the requested `2.45.0` wheel is
not published in its package index); this version is pinned in `requirements.txt`. The five Dockerfiles
under `e2b_templates/` are the build inputs for registering the required aliases with the gateway.

Formal campaign startup always performs: report SHA-256 and artifact copy, E2B controller upload,
Top 10 Qualification in the fixed Ubuntu 26.04 base, and only then Mission creation. If source
snapshot, unresolved-edge, hotspot, benchmark, `.deb` replacement, or rollback evidence is missing,
`lda run` stops after Qualification and writes `.lda/artifacts/qualification.json`; it does not modify
package source. Canary release is restricted to `libcairo2` and `libsoup-3.0-0` until both pass all
deterministic gates.

Agent Runtime uses the Codex CLI, not a controller-side SDK call. Its provider is configured inside
the Agent Sandbox with `OPENAI_BASE_URL`/the explicit `fact` model provider; `OPENAI_API_KEY` is
passed only to that process. The E2B API key is never passed to Agent, Workspace, or Judge sandboxes.
