# LDA: Linux Development Agent

[中文版](README.md)

LDA is an agent workflow that develops real performance optimizations for
Ubuntu 26.04 packages — under the constraint that the result must install on a
stock system as a drop-in replacement, with every existing binary and program
still working unmodified.

The agent harness is [Humanize 2](https://github.com/humanfia/humanize2)
(`hmz`): its runner owns the loop, the agent sessions, retries, resumable
state, and trace lineage. This repository is a Humanize *flowverse* — it
contributes everything LDA-specific on top of that harness: the hard
compatibility fences, the two-layer certified benchmarks, the task cards, the
package priority list, and the supervision rules. Every build, test,
benchmark, and agent turn executes inside an E2B sandbox created from one
pinned template; nothing runs on a bare host.

- **Quick start** → [jump](#quick-start)
- **What makes an optimization acceptable** → [the surgical-replacement boundary](#the-surgical-replacement-boundary-abiffi)
- **How the workflow is built on Humanize** → [jump](#how-this-workflow-is-built-on-humanize-2)
- **Measured speedups** → [certified results, at the bottom](#certified-results)

---

## The surgical-replacement boundary (ABI/FFI)

This is the hardest fence in LDA and the reason the project is shaped the way
it is. An optimized package must be installable on a stock Ubuntu 26.04 system
with `dpkg -i`, and every existing binary, program, and development workflow
must keep working **without being rebuilt or modified**. Users of Ubuntu
should be able to install our library and get the speedup — not migrate to a
different distribution or recompile their applications.

Because that promise is easy to state and easy to break, it is enforced
mechanically per candidate, before any reviewer is consulted:

| Fence | What is required |
|---|---|
| Shipped library set | the candidate debs ship exactly the baseline's shared libraries — same names, no additions, no removals |
| SONAME & ELF identity | class, endianness, OS/ABI, machine and type equal; SONAME never changes |
| Dynamic symbol table | exported symbols and their versions equal to stock, entry for entry |
| Type-level ABI | `abidiff` with debug info (dbgsym) reports no difference |
| NEEDED set | the candidate links against the same libraries the baseline did |
| Package relationships | Package, Version, Architecture, Depends, Pre-Depends, Provides, Breaks, Conflicts byte-equal, so `apt` treats the replacement exactly as it treats stock |
| FFI proof | a consumer binary compiled **once against the baseline** runs unmodified against the candidate, with identical output |
| Behavior | every fixture decodes / renders / parses to byte-identical results through baseline and candidate |
| Package lifecycle | the candidate installs over stock on a live system, a compiled consumer still runs, and stock rolls back cleanly |
| Security hardening | RELRO, non-executable stack, no TEXTREL/RPATH, Build IDs survive |
| Upstream tests | the package's own suite runs during the candidate rebuild and the build log must prove it (a packaging that visibly disables its tests is recorded as not-applicable, never assumed to have passed) |
| autopkgtest | the package's `debian/tests` run against the installed candidate; every test that passed on baseline must pass again |
| Trace audit | the Builder's own recorded actions are audited for evidence tampering (see [supervision](#supervision-the-command-layer)) |

**A speedup never compensates for a fence failure.** This is what keeps the
optimizations honest: the only way to make the numbers move is to make the
code faster, because every route that would fake it is closed by a fence.

Practical consequences for how the agent is allowed to optimize:

- Architecture-specific code is fine, but it must be reached by **runtime
  dispatch** (one-time CPUID / `target_clones`) with the generic path kept, so
  the same deb stays correct on any x86-64 host.
- New fast paths must keep symbols **hidden**; adding an exported symbol
  breaks the symbol-table fence.
- Compiler-flag work (LTO, unrolling) is allowed only where it does not change
  the exported ABI — and is measured, not assumed (see the cairo row in the
  results table: re-enabling LTO measured real but sub-threshold).

## Two-layer benchmarks

Every performance claim is measured at two layers, because a library
micro-benchmark alone does not prove a user-visible win:

- **Micro** — workloads that exercise the optimized library's own code
  directly. This is the Builder's local reward signal. The inputs the Builder
  can see are the *train* set.
- **End-to-end** — a real consumer path that goes *through* the library, to
  check the micro win survives in an application. The e2e workloads in this
  repository are the real consumers of each target: cairo PNG-surface loading
  and gdk-pixbuf decoding for libpng, the cairo rendering stack for libcairo2,
  GObject-introspection churn for GTK, an HTTP round trip for libsoup, and
  `getent` through NSS for sssd.

Certification additionally requires the declared margin on a **hidden
holdout** generated from a host-held seed the Builder has never seen, and a
replay in **fresh sandboxes**. See
[benchmarks on a noisy multi-tenant host](#benchmarks-on-a-noisy-multi-tenant-host)
for the noise policy, which is the part that took the most iteration.

## How this workflow is built on Humanize 2

`hmz` is the brick; LDA is the building. The generic agent machinery is never
re-engineered here, which is why extending the flow to a new package family is
a workbench script plus a card profile, and swapping the model or agent
backend is a flag rather than a rewrite.

**What Humanize owns**

- the **runner**: drives the flow, restarts it, and keeps it resumable
- **agents and sessions**: `clone` / `new` / turn execution, and the failure
  semantics of a turn
- **kept state**: a per-workspace-cycle `state` dict handed back on resume
- **trace lineage** per agent turn (`hmz trace collect` sees the whole run)

**What LDA contributes**

| Seam | File | What it does |
|---|---|---|
| Flow declaration | `flows/lda/__init__.py` | a `@flow(resumable=True)` that receives two hmz agents (`builder`, `reviewer`) plus hmz's kept `state`, and runs one task card |
| Role fan-out | `src/lda_hm/hmz_glue.py` | clones the two handed agents into the **six** LDA roles and wraps them in the engine's Agent/Session protocol |
| Agent backend | `src/lda_hm/hmz_backend.py` | an `AgentBase` / `CommandSessionBase` whose every turn is relayed **into the card's E2B sandbox** |
| Relay | `src/lda_hm/hmz_relay.py` | one host-side process per turn: pushes the prompt in, runs the in-sandbox agent CLI, prints the reply |
| Sandbox broker | `src/lda_hm/broker.py` | the flow process lends its live sandbox connection to relay processes over a unix socket, so one sandbox serves every role |
| Run engine | `src/lda_hm/driver.py` | the LDA loop itself: setup, rounds, fences, benchmarks, finalize |

Because the backend is an ordinary hmz agent backend, an in-sandbox LDA turn
looks to hmz like any other agent turn — so model credentials stay
sandbox-resident (the relay carries none), the role an agent plays is just its
hmz name (`clone(name="builder")`), and the whole run remains visible to hmz's
tracing. `hmz_glue.py` deliberately never imports hmz: it talks to the agents
through their public surface only, so the engine tests can drive the same code
with stubs.

```mermaid
flowchart TD
  subgraph HMZ[Humanize 2 - the bricks]
    RUN[runner: drives the flow,<br/>restarts it, keeps it resumable]
    AG[agents and sessions:<br/>clone / new / turn]
    ST[kept state, handed back on resume]
    TR[trace lineage per agent turn]
  end
  subgraph LDA[LDA - this repository]
    FLOW[flows/lda: clones 2 hmz agents<br/>into 6 roles, runs one card]
    BK[E2BHarnessAgent backend:<br/>each turn relayed INTO the sandbox]
    DRV[lda_hm.driver - one run engine]
    FEN[surgical-replacement fences<br/>+ paired benchmark verdicts]
    SUP[Supervisor command node<br/>+ live Builder watchdog]
    CARD[task cards, priority list,<br/>exploration probes]
  end
  RUN --> FLOW
  AG --> BK
  ST --> FLOW
  FLOW --> DRV
  BK --> BRK[run broker<br/>unix socket]
  BRK --> SBX[(E2B sandbox<br/>pinned Ubuntu 26.04 template)]
  DRV --> SBX
  CARD --> DRV
  DRV --> FEN
  FEN --> REV[fresh Reviewer]
  REV --> DRV
  SUP --> DRV
```

## Roles: persistent writers, fresh readers

The two agents hmz hands the flow are cloned into six named roles. Writers
keep their context because they must continue unfinished reasoning; readers
start fresh because independence is part of the review boundary.

| Side | Role | Session | Job |
|---|---|---|---|
| builder | Drafter | persistent | produce the idea draft |
| builder | Planner | persistent | revise the candidate plan, seal it |
| builder | Builder | persistent | one bounded change per round, tool-guarded |
| reviewer | Analyst | fresh each reading | independent diagnosis when the run is stuck |
| reviewer | Reviewer | fresh each verdict | rule on the evidence after fences pass |
| reviewer | Supervisor | per round | steer the run from its own evidence |

```mermaid
sequenceDiagram
  participant P as Planner (persistent)
  participant B as Builder (persistent, tool-guarded)
  participant F as Fences (deterministic)
  participant R as Reviewer (fresh per verdict)
  participant S as Supervisor (per round)
  P->>B: sealed plan + round contract
  B->>F: one bounded change, committed
  F-->>R: review allowed only when every fence passes
  R-->>S: ADVANCED / STALLED / REGRESSED
  S-->>B: continue / retarget / restart / add analyst / grace / abort
```

## One run of a card

1. **Explore** (before any card exists): `lda explore <package>` measures a
   stock workload in a fresh sandbox, attributes cycles with `perf`, and
   writes an honest feasibility verdict — *including falsification* when the
   hot code turns out to live in another package. This is what keeps the
   project from burning runs on a package it cannot move.
2. **Setup**: sandbox from the pinned template; the recorded APT snapshot is
   the only package source; the installed set is aligned to that snapshot; the
   exact source version is fetched and committed as the baseline; the fence
   self-checks must flag known-bad samples before any verdict is trusted.
3. **Rounds**: a persistent Builder makes one bounded change per round (an
   in-turn tool guard blocks evidence tampering as it happens); fences and
   paired benchmarks judge the round; a fresh Reviewer rules on the evidence;
   the Supervisor steers.
4. **Finalize**: the whole result replays in fresh sandboxes from the
   immutable template — setup from the snapshot, patch re-applied, every fence
   re-run, fresh-seed holdout — before anything is called certified.

```mermaid
stateDiagram-v2
  [*] --> Setup
  Setup --> Idea
  Idea --> Plan
  Plan --> Implementation
  Implementation --> RegularReview
  Implementation --> FullAlignment
  RegularReview --> Implementation: continue
  FullAlignment --> Implementation: aligned
  RegularReview --> DriftRecovery: stalled twice
  FullAlignment --> DriftRecovery: stalled twice
  DriftRecovery --> Implementation: re-anchored
  RegularReview --> Stop: stalled three times
  FullAlignment --> Stop: stalled three times
  RegularReview --> CodeReview: COMPLETE
  FullAlignment --> CodeReview: COMPLETE
  CodeReview --> Implementation: findings
  CodeReview --> Finalize: no findings
  Finalize --> MethodologyAnalysis
  MethodologyAnalysis --> Complete
  Implementation --> MaxIter: iteration limit
  MaxIter --> MethodologyAnalysis
```

## Benchmarks on a noisy multi-tenant host

E2B sandboxes share hosts with other tenants, so the benchmark policy is
designed to make noise **visible and non-exploitable** rather than to pretend
it away. Every rule below exists because noise broke a run first:

- all timing is taken **inside** the sandbox by the workload script and tagged
  with a per-invocation nonce the measured process cannot see; host wall time
  is never judged;
- baseline and candidate **alternate within one sandbox**, per repetition, so
  host drift cancels inside each pair;
- one repetition runs for **seconds**, not tens of milliseconds — process
  start-up and scheduler jitter must be negligible next to the effect;
- a speedup certifies only when the **95% Student-t interval** on
  per-repetition log ratios excludes 1.0, the declared minimum is cleared, and
  fewer than three repetitions never certify;
- **co-tenant CPU steal above 10%** of any sample invalidates the run itself
  (one retry, then an infrastructure block — the candidate is not blamed); a
  spread wildly out of proportion to the effect is treated the same way;
- the micro inputs the Builder can see are the train set; certification also
  requires the declared margin on a **hidden holdout** from a host-held seed;
- before certification is trusted on a host, the baseline is measured against
  itself (an **A-A null run**): a harness that resolves an effect where none
  exists is a false-positive generator and its verdicts are refused;
- **finalize replays in fresh sandboxes** that land on other hosts, so a
  speedup that only existed on one machine does not certify.

Measurement capability of the sandboxes (probed and recorded per run): the
Firecracker guests expose no PMU — `cycles` is unsupported — so profiling uses
software sampling (`linux-perf` from the pinned snapshot). The target CPU
(Intel Xeon Gold 6548Y+, Emerald Rapids) reports the full AVX-512/AMX flag
set, and architecture-specific work targets those flags behind runtime
dispatch so the package stays correct anywhere.

## Supervision (the command layer)

Authority is fixed: **human control file > deterministic rules > LLM
counsel.**

- A **live watchdog** reads the Builder's growing trace during a turn, mirrors
  it to the host (so an agent cannot rewrite its own history), and kills a
  stalled agent process after double confirmation — a watchdog that cannot
  observe never kills. Every turn is independently wall-clock bounded inside
  the sandbox (`LDA_TURN_TIMEOUT`, default 4200s), so a runaway agent cannot
  outlive its relay.
- Between rounds the **Supervisor** assembles a pulse from the run's own
  evidence (verdicts, blocks, benchmark trend, trace statistics, sandbox load,
  spend) and emits one auditable decision: continue, retarget,
  restart the Builder, consult an independent Analyst, grant a one-per-run
  grace for an improving near-miss, or abort. An LLM supervisor is consulted
  only when the run is off-track; a malformed answer degrades to the rule
  decision, and an **LLM abort is demoted to retarget** — only humans and hard
  rules may end a run.
- `<run>/control.json` is the **human channel**, re-read at every phase
  boundary: `{"action": "abort"}`, `{"contract": "..."}`,
  `{"action": "restart_builder"}`.
- **Infrastructure failures never count against the candidate.** A Builder
  turn killed by a model-gateway outage, a Reviewer answer that is a transport
  error, an unstable benchmark window — each is recorded as an infrastructure
  block that consumes no stall budget and no iteration budget. Three in a row
  **pause** the run (state saved, sandbox released, exit 75) instead of ending
  it, and the driver loop resumes it: an outage that lasts an afternoon must
  not lose a card.
- The Builder-trace audit judges what the agent **did** — executed commands
  and edited paths — never what it said: prose legitimately quotes the very
  patterns a cheating command would contain. A session whose trace fails audit
  is replaced with a fresh session (clean trace, stall retained).

## Package priority: what to optimize first

Optimizing tens of thousands of Ubuntu packages is not a plan, so candidates
are ranked from the Ubuntu 26.04 desktop ISO's own dependency graph
(`data/candidates-ubuntu-2604.json`, surfaced by `lda candidates`).

The ISO manifest carries 1,814 Debian packages, 1,811 of which match the
Packages index exactly; the resulting graph has 12,369 edges, of which 8,401
are required (`Depends` + `Pre-Depends`). Candidates are filtered to packages
that are required by at least 5 others, have at least 3 required dependencies
of their own, and are not `oldlibs` or `required`-priority core libraries — so
`libc6`, `libgcc-s1` and `libstdc++6` deliberately do not appear. The score
combines fan-in (reuse, 0.40), required out-degree (layer position, 0.35) and
dependency surface (0.25), times a priority factor. **The score is a
prioritization proxy only — it says nothing about code quality or known
defects.**

Two directions come out of it: mid-layer UI/media infrastructure that many
components reuse (GTK, cairo, GStreamer, pango, gdk-pixbuf, libtiff,
libpulse), and high-layer desktop/system components with a wide direct
dependency surface (gnome-shell, LibreOffice, sssd, ibus, polkitd,
cups-filters). Current per-package verdicts are in the
[top-10 status table](#top-10-status) at the bottom.

## Quick start

Requirements: Python **≥ 3.12** (hmz requires it), access to an E2B cluster,
and credentials for a Claude-compatible model gateway.

```bash
git clone -b LDA-HM https://github.com/yisun219/Linux-Development-Agent-Flow.git lda
cd lda

# 1. one-time environment: the hmz harness, the E2B SDK, and this repository
python3.12 -m venv ~/.venvs/ldahm
~/.venvs/ldahm/bin/pip install "git+https://github.com/humanfia/humanize2.git" e2b
~/.venvs/ldahm/bin/pip install -e .          # provides the `lda` command
export PATH="$HOME/.venvs/ldahm/bin:$PATH"

# 2. sanity check: 100 engine tests, no sandbox and no model calls needed
python -m unittest discover -s tests         # expect: OK
bin/lda-hmz check                            # expect: drives: ('builder', 'reviewer')

# 3. E2B access, kept out of the repository (loaded automatically, chmod 0600)
install -d -m 700 ~/.config/lda-hm
cat > ~/.config/lda-hm/e2b.env <<'EOF'
E2B_API_URL=https://your-e2b-endpoint
E2B_SANDBOX_URL=https://your-e2b-endpoint
E2B_API_KEY=your-e2b-key
EOF
chmod 600 ~/.config/lda-hm/e2b.env

# 4. build the pinned lda-base template once (Ubuntu 26.04 + toolchain +
#    agent harness + the skills that ship into every sandbox)
python sandbox/build_template.py

# 5. model credentials for the in-sandbox agent CLIs. They are injected only
#    when a sandbox boots; the host-side relay processes never carry them.
export ANTHROPIC_BASE_URL=https://your-model-gateway
export ANTHROPIC_AUTH_TOKEN=your-token
```

Then run the workflow:

```bash
# what is worth optimizing, ranked from the ISO dependency graph
lda candidates

# measure a candidate before spending a run on it (no agent turns)
lda explore libsoup-3.0-0 --results-root ~/lda-runs

# open a card and run the full flow under the hmz harness
lda gen-card libsoup-3.0-0 --out examples/libsoup3-card.json
lda init-card ~/lda-work-soup examples/libsoup3-card.json
LDA_RESULTS_ROOT=~/lda-runs bin/lda-hmz-drive ~/lda-work-soup soup-production-001
```

`bin/lda-hmz-drive` is the production entry point: it keeps one run alive
across transient failures. **Interrupting a run loses nothing** — starting the
same command again resumes from the state hmz kept, and an infrastructure
outage parks the run rather than ending it.

Useful knobs:

| Knob | Effect |
|---|---|
| `<run>/control.json` | steer a live run (`abort`, `restart_builder`, new `contract`) |
| `LDA_RESULTS_ROOT` | durable evidence repository, separate from flow source |
| `LDA_BUDGET_USD` | spend cap for the run |
| `LDA_CERT_REPLICATIONS` | fresh-sandbox certification replications (default 2) |
| `LDA_TURN_TIMEOUT` | wall-clock bound on one agent turn (default 4200s) |
| `LDA_AGENT_MODEL` | model for both sides (default `claude-opus-4-8`); `LDA_AGENT_MODEL_REVIEWER` overrides the reader side |
| `lda trace <run-dir>` | render a run's behavioral timeline |
| `tools/e2b/reap-sandboxes.py` | collect sandboxes a SIGKILL'd driver could not release |

## Repository layout

```text
flows/lda/           the flow the hmz runner executes
src/lda_hm/
  driver.py          one run engine shared by both entry points
  hmz_glue.py        hmz agents -> LDA roles and the engine protocol
  hmz_backend.py     hmz agent backend: turns relayed into the sandbox
  hmz_relay.py       one relay process per agent turn
  hmz_launcher.py    `bin/lda-hmz`: builds the agents, calls hmz's Runner
  broker.py          the flow process lends its sandbox connection
  execution.py       E2B lifecycle, integrity pinning, certification
  fence.py gates.py  deterministic boundary before any reviewer
  benchmark.py       paired statistics, nonce samples, Student-t policy
  supervision.py     Supervisor rules, run pulse, Builder watchdog
  explore.py         pre-card feasibility probes for ranked packages
  cardgen.py         task-card generator for profiled candidates
  candidates.py priority.py   the ranked list and its scoring
sandbox/lda-base/    template recipe: Dockerfile, checks, harness, skills
examples/            generated task cards (libpng, cairo, soup, gtk3/4, sssd)
data/                ranked top-30 candidates from the ISO dependency graph
tests/               100 engine and card tests (no model calls, no sandbox)
docs/FLOW.md         flow mechanics in depth
docs/BASELINE.md     baseline capture and snapshot alignment
```

The skills shipped into every sandbox (`sandbox/lda-base/skills/`) use the
`<name>/SKILL.md` layout and are linked into the agent's skill path at
bootstrap, so the Builder actually loads them: the LDA fence, micro-benchmark,
end-to-end-benchmark and adversarial-review contracts, the measured libpng
lessons (including the validated patch), and the pinned Intel performance
skills.

## Development

```bash
python -m unittest discover -s tests -v   # 100 tests, no model or sandbox needed
bin/lda-hmz check                         # verify the flow declaration
```

---

# Certified results

Every number below comes from paired in-sandbox benchmarks, held on a hidden
holdout the Builder never saw, re-certified in fresh sandboxes, with the full
ABI/FFI surgical-replacement fence suite green. Evidence lives in the run
directories under the results root.

## libpng16-16t64 — certified

**Run `libpng-2604-production-008`, COMPLETE (2026-08-28).**

| Layer | Result |
|---|---|
| Micro (train) | **+6.77%** decode |
| Micro (hidden holdout) | **+6.76%** (95% CI on ratio 0.9323–0.9419, 7 repetitions, max steal 0.16%) |
| End-to-end | **+12.40%** on the cairo PNG-to-surface stack |
| Fresh-sandbox re-certification | +6.68% / +6.95% micro, +12.44% / +11.48% e2e in 2 fresh sandboxes with fresh-seed holdouts |
| Fences | 10/10 green; independent code review 0 findings |
| Drop-in check | the deb installs over stock `libpng16-16t64` 1.6.57-1 on a live system and rolls back cleanly |

**How it was accelerated.** The SSE4.1 Paeth unfilter replaces the SSE2
multi-op abs/select emulation with `pabsw` + `pblendvb`, plus an SSE2 Up-filter
row (`-O2` never autovectorizes that byte loop). Reached through one-time
CPUID dispatch, with hidden symbols and the SSE2 fallback kept.

**Why it is faster.** The same per-row filter recurrence retires in fewer uops
on the target Xeon. It is byte-exact by construction: the blend mask comes from
`cmpeq`, so the selection is the same one the scalar code makes.

**Why it stays drop-in.** Dispatch is internal and the new code is hidden, so
SONAME, the dynamic symbol table and `abidiff` are all untouched — which is
exactly why it can be shipped to an existing Ubuntu system.

**A finding worth recording:** Ubuntu 26.04's gdk-pixbuf 2.44 decodes PNG via
`glycin` (Rust), so libpng work **cannot** move the pixbuf path (0% ± 0.7% over
6 measurements). `cairo_image_surface_create_from_png` is the real desktop
libpng consumer, and that is where the +12.4% lands. Chasing the pixbuf path
would have produced a true micro win with no user-visible effect.

## Measured but not yet certified

**libsoup-3.0-0**: +8.0% train / +7.4% hidden holdout on the header-layer
micro — forward-order list building without the `g_slist_reverse` walk, and
quality-list parsing without the intermediate GSList+strdup churn;
allocation-count-neutral, byte-identical output. The run ended on a trace-audit
false positive (the audit was scanning prose; fixed — it now reads only
executed actions) before certification could run. Re-run queued.

## Top-10 status

Verdicts as of 2026-08-31. Every candidate is explored with measurements
*before* any optimization is attempted; per-package evidence sits in
`explore/<package>/` under the results root.

| # | Package | Score | Status | What the evidence says |
|---|---|---|---|---|
| 1 | libgtk-4-1 | 71.50 | carded, run queued | the gi driver diluted attribution (~11% of cycles in libgtk-4), so the card uses a compiled dlopen workbench whose three inputs (CSS parse, selector match, full-tree layout) are gtk's own machinery by construction — probed deterministic and linearly scaling before the card opened |
| 2 | libgtk-3-0t64 | 69.42 | carded, run queued | same compiled workbench, gtk3 API variant; gtk3 style resolution costs ~6× gtk4's per iteration, which is exactly the in-package surface the card rewards |
| 3 | gnome-shell | 64.28 | **falsified honestly** | the frame loop lives in libmutter/clutter and the JS in gjs; recompiling gnome-shell itself cannot move those hot paths |
| 4 | libreoffice-core | 63.34 | deferred: not operable per-round | headless convert-to-pdf is a ready e2e workload, but one candidate rebuild costs hours in-sandbox (56G build tree) |
| 5 | sssd-common | 60.69 | carded, run queued | headless proxy-files domain workbench: installed-mode A/B (`dpkg -i` + daemon restart outside the timed region), seeded NSS lookup schedules with a hidden holdout, fresh-process `getent` e2e |
| 6 | libcairo2 | 60.20 | measured negative so far | the first deck was mis-attributed (paint/mask are pixman's code, png-load is libz's); on the corrected cairo-owned deck (dashed-bezier stroking, self-intersecting fills, corpus text paths), re-enabling the LTO the packaging had disabled measured +1.38% summed — real but below the pre-registered 2% bar. `target_clones` stacked on LTO regressed (IFUNC defeats cross-TU inlining on serial scan-converter code). The next candidate needs a second mechanism on top of LTO. |
| 7 | gnome-settings-daemon | 59.67 | deferred: needs a session harness | most gsd plugins need a live session bus; only a startup subset is measurable headlessly |
| 8 | gstreamer1.0-plugins-good | 59.55 | **falsified for decode** | perf shows 90.3% of decode cycles in the external codec (libvpx); the package's own demux/parse share is under 3% |
| 9 | ibus | 57.77 | deferred: needs an input fixture | a truthful key-roundtrip benchmark needs a focused window and synthetic input events |
| 10 | libsoup-3.0-0 | 54.01 | mechanism proven, re-run queued | header parsing (quality lists, params, case-insensitive lookups) is string-heavy `-O2` code entirely inside the package; measured +8.0% train / +7.4% holdout with byte-identical output (see above) |

"Falsified" is a deliberate, useful outcome: the exploration proved that
recompiling *that* package cannot move the measured hot paths, because the hot
code lives somewhere else. Recording it costs one probe and saves a whole run —
and it is the reason the certified numbers above can be taken at face value.
