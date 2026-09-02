# Idea Draft — libpng Decode Optimization (Ubuntu 26.04, Drafter Stage)

## Original Task (verbatim)

> Optimize libpng decode for Ubuntu 26.04 with surgical replacement compatibility. ROUND 0 IS PRESCRIBED: read /opt/lda/skills/lda-libpng-lessons.md, apply /opt/lda/skills/lda-libpng-validated-r0.patch VERBATIM with git apply, verify it compiles, commit, end the round - no modifications in round 0; the patch already passed full micro certification and measures +12.3 percent on the cairo end-to-end path. Later rounds may extend SIMD filter coverage for additional certified gains, keeping micro >=2 percent, cairo e2e >=3 percent, no per-input regression, and never touching the pixbuf benchmark expectations - Ubuntu 26.04 pixbuf decodes via glycin and cannot be moved by libpng work (the lessons file explains)

---

## Context Summary (from prescribed reading)

- **Target CPU**: Xeon Gold 6548Y+. Stock Ubuntu build already enables `PNG_INTEL_SSE` (SSE2 baseline).
- **Validated R0 patch** does three things: (1) adds SSE4.1 Paeth unfilter variants (`paeth3/4_sse41`) selected via one-time `__builtin_cpu_supports("sse4.1")`; (2) adds an SSE2 Up-filter row (`up_sse2`), bpp-independent; (3) wires runtime dispatch resolved **once per process** in `png_init_filter_functions_sse2`, never per-image/per-row.
- **Measured**: +6–7% micro (Paeth), +12.3% cairo e2e (ratios ~0.890 over 12 pairs), byte-identical output, SONAME/ABI/symbols unchanged, no new DT_NEEDED.
- **Hard constraints for later rounds**: micro ≥2%, cairo e2e ≥3%, no per-input regression, pixbuf expectations untouched.

### Decisive facts that constrain the design space
1. **pixbuf is unreachable by libpng.** gdk-pixbuf 2.44 routes PNG through glycin (Rust png crate). Six paired measurements of a +13% libpng win → 0.0% ±0.7% on pixbuf. Pixbuf is a *verifier/regression fence only*.
2. **cairo is the certifying e2e path** (`cairo_image_surface_create_from_png`): GTK assets, librsvg, screenshots, printing.
3. **Dispatch cost is visible at the 1×1 boundary input** (240k decodes). Any per-image/per-row CPUID check regresses past the 2% veto. Resolve dispatch once per process.
4. **AVX is a trap**: VEX-128 Paeth measured slower (SSE↔AVX transition penalty); AVX2 widening a serial recurrence saturates at 128 bits.
5. **PGO trap**: training on the wrong profile (one-shot `png_image` API) went negative e2e. If ever attempted, train on the row-by-row `png_read_row` progressive path.

---

## Six Orthogonal Directions

### D1 — Execute the prescribed Round 0 verbatim (apply → compile → commit → end)
- **What**: `git apply` the validated patch, confirm clean build, commit, end round. No modifications.
- **Evidence**: Patch already passed full micro certification (train +6%, hidden holdout, all four inputs incl. 1×1 boundary; ABI/FFI/behavior/lifecycle/security fences). +12.3% cairo e2e.
- **Risk**: Near-zero. It is a known-good, pre-certified artifact. Only risk is a stale base tree causing `git apply` context mismatch — mitigated by verifying the target files match the diff hunks before/after apply.
- **Cost/effort**: Minimal. **This is the mandated round.**

### D2 — SSE4.1 (or SSE2) Average-filter upgrade
- **What**: The R0 patch leaves `avg3/avg4` on the existing SSE2 path. Average is the other common recurrence filter. A tuned SSE4.1 variant (or improved SSE2 rounding-avg using `_mm_avg_epu8` where semantics permit) could add coverage.
- **Evidence**: Average is frequently selected by encoders; plausible incremental micro gain. But no measured number yet; must be certified.
- **Risk**: Medium. Average's `(a+b)>>1` semantics differ from `_mm_avg_epu8` (which rounds up); getting byte-exact requires care. Recurrence limits width like Paeth.
- **Cost/effort**: Moderate; strongest *orthogonal* candidate for a later round.

### D3 — Sub-filter (`sub3/sub4`) refinement
- **What**: Revisit the SSE2 Sub unfilter for a tighter shuffle-based prefix-sum, or SSE4.1 `_mm_shuffle_epi8`-assisted broadcast of the running accumulator.
- **Evidence**: Sub is a serial byte-add recurrence; existing SSE2 code is already reasonable. Upside likely small.
- **Risk**: Medium-low correctness risk, but low reward → may fail the ≥2% micro bar on its own.
- **Cost/effort**: Moderate reward-to-risk unfavorable.

### D4 — Row-output / transform copy path optimization
- **What**: Optimize post-unfilter row handling (e.g., the interlace/row copy, or `png_do_read_transformations` byte movement) rather than the filter kernels. Lessons explicitly flag "row-output copy" and "end-to-end gap" as uncovered.
- **Evidence**: cairo e2e includes more than unfiltering (format conversion to premultiplied BGRA). Gains here would help the *certifying* path directly, not just micro.
- **Risk**: Higher surface area, transforms are format-dependent; must preserve byte-exactness across many pixel formats. Harder to keep "no per-input regression."
- **Cost/effort**: High effort, potentially high e2e payoff — a candidate for a well-scoped later round.

### D5 — AVX2/AVX-512 widening of filters
- **What**: Widen Paeth/Up/Avg to 256/512-bit.
- **Evidence**: **Explicitly a documented trap.** VEX-128 slower here; AVX2 saturates at 128 bits for serial recurrences; SSE↔AVX transition penalties. Up-filter (non-recurrent) could in principle widen, but the Up win is already captured at 16B and the transition penalty risk plus new codegen constraints make it net-negative-risk.
- **Risk**: High — measured-negative precedent.
- **Cost/effort**: **Reject.** Retained only as a documented dead-end.

### D6 — PGO / -O3 rebuild
- **What**: Profile-guided rebuild of the decode path.
- **Evidence**: **Documented trap** when mis-profiled (went negative e2e). Only viable if profiled on the row-by-row progressive `png_read_row` path.
- **Risk**: High; build-config change touches whole library, harder ABI/reproducibility story, and prior negative result.
- **Cost/effort**: **Reject for now**; retain as conditional far-future experiment only with correct profile.

---

## Comparison Matrix

| Dir | Coverage added | Expected micro | e2e (cairo) relevance | Correctness risk | Regression/veto risk | Verdict |
|-----|----------------|----------------|-----------------------|------------------|----------------------|---------|
| **D1** | Paeth SSE4.1 + Up SSE2 | +6–7% (measured) | +12.3% (measured) | none (certified) | none (certified) | **PRIMARY (mandated)** |
| D2 | Avg SSE4.1/SSE2 | plausible + | moderate | medium (avg rounding) | medium | Best later-round alt |
| D3 | Sub refinement | small | low | low-med | med (may miss 2%) | Weak alt |
| D4 | Row/transform copy | n/a (e2e) | potentially high | med-high | med-high | Ambitious later alt |
| D5 | AVX2/512 widening | negative precedent | — | high | high | Rejected (trap) |
| D6 | PGO/-O3 | negative precedent | — | med | high | Rejected (trap) |

---

## Primary Direction Chosen: **D1 — Execute Round 0 verbatim**

**Rationale**: Round 0 is explicitly prescribed and the artifact is pre-certified with hard numbers on the *certifying* path (+12.3% cairo e2e, +6–7%/+13% micro), byte-exact output, and unchanged ABI/SONAME/symbols/DT_NEEDED. It dominates every alternative on the evidence axis (measured vs. speculative) and on the risk axis (fully fenced vs. unproven). The task forbids modifications this round. There is no rational reason to deviate.

**Execution shape (for the implementing stage, not performed here)**:
1. Confirm base tree hunks match the diff (CMakeLists.txt, intel/filter_sse2_intrinsics.c, intel/filter_sse41_intrinsics.c [new], intel/intel_init.c, pngpriv.h).
2. `git apply` the patch **verbatim** — no edits.
3. Build; verify it compiles cleanly.
4. Sanity-verify the dispatch is process-once (no per-image CPUID) and Up/Paeth wiring is present.
5. Commit; **end the round**.

**Guardrails inherited**: keep pixbuf expectations untouched (it is a verifier, not movable by libpng); preserve byte-exact decode; no new DT_NEEDED; SSE2 remains the safe fallback so the library stays drop-in on non-SSE4.1 amd64.

---

## Retained Alternatives (for later rounds, in priority order)

1. **D2 (Average-filter SIMD)** — highest-value orthogonal extension. Requires byte-exact validation of `(a+b)>>1` semantics (do **not** assume `_mm_avg_epu8`). Reuse the same once-per-process SSE4.1 dispatch already established by R0.
2. **D4 (Row-output/transform copy)** — targets the e2e gap directly on the cairo path; scope narrowly (one pixel-format conversion at a time) to preserve "no per-input regression."
3. **D3 (Sub-filter refinement)** — only if it can independently clear the ≥2% micro bar; otherwise fold into a bundle with D2.
4. **D5 / D6** — documented traps; retained solely as negative results. D5 rejected outright. D6 only ever revisited with a `png_read_row` progressive-path profile.

**Constraints binding all later rounds**: micro ≥2%, cairo e2e ≥3%, no per-input regression (esp. the 1×1 boundary / 240k-decode dispatch-sensitivity case), pixbuf expectations never touched, dispatch resolved once per process, no baseline ISA raise (no `-march`), ABI/SONAME/symbols/DT_NEEDED unchanged, byte-exact output.

---

*Drafter stage output only. No source files edited, no implementation commands run, no commits created.*
