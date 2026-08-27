# Validated libpng Optimization Lessons (Ubuntu 26.04, Xeon Gold 6548Y+)

Evidence-backed lessons from certified benchmark rounds; every claim below
was measured under paired in-sandbox benchmarks with holdout.

## Confirmed wins

- SSE4.1 Paeth unfilter (`pabsw`/`pblendvb` replacing the SSE2 multi-op
  emulation) with runtime CPUID dispatch: +6-7% micro decode aggregate,
  byte-exact output, SONAME/symbols/ABI unchanged, no new DT_NEEDED.
  The stock Ubuntu build already enables `PNG_INTEL_SSE` (SSE2 baseline), so
  the win must come from upgrading the Paeth path, not enabling SSE.
- A COMPLETE VALIDATED PATCH implementing this (plus an SSE2 Up-filter row)
  is checked in at `/opt/lda/skills/lda-libpng-validated-r0.patch`. It
  passed the full micro certification (train +6%, hidden holdout, all four
  inputs including the 1x1 boundary, ABI/FFI/behavior/lifecycle/security
  fences) in a prior run. Apply it with `git apply` as the starting point
  instead of re-deriving the mechanism; then spend the round on what it does
  not yet cover (remaining filter rows, row-output copy, end-to-end gap).

## Confirmed traps

- Dispatch cost is visible at the 1x1 boundary input (240k decodes): any
  per-image or per-row dispatch check regresses it past the 2% veto. Resolve
  dispatch once per process (lazy static in the unfilter itself, or an
  IFUNC-style one-time pointer), never in the per-image setup path.
- VEX-128 encodings of the same Paeth kernel measured slower than the SSE4.1
  legacy encoding here (SSE<->AVX transition penalties); AVX2 widening of a
  serial recurrence saturates at 128 bits - do not chase it.
- A PGO/-O3 rebuild trained on an unrepresentative profile measured slightly
  negative end-to-end; if attempting PGO, train the profile on the pixbuf
  loader path (row-by-row png_read_row with progressive callbacks), not on
  the one-shot png_image simplified API.

## Translation reality (why e2e is harder than micro)

The GTK/gdk-pixbuf image path adds loader machinery, GIO chunked reads,
per-row callbacks, and buffer copies around libpng; a +6% micro decode win
translated to only +0.2-0.7% on the pixbuf-decode end-to-end benchmark.
Clearing an end-to-end bar therefore needs mechanisms that cover the whole
libpng share of that path (all SIMD filter rows, row-copy/`png_combine_row`,
IDAT chunk handling), not just one kernel.
