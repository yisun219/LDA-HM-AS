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
and state primitives.

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
