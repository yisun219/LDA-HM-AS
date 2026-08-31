---
name: lda-libpng-lessons
description: Measured lessons from the certified libpng pilot on Ubuntu 26.04 / Xeon Gold 6548Y+: confirmed wins, traps, and where a libpng speedup actually translates (cairo yes, gdk-pixbuf no).
---

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
  is checked in at `/opt/lda/skills/lda-libpng-lessons/lda-libpng-validated-r0.patch`. It
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

## Translation reality (measured, decisive)

- On Ubuntu 26.04, gdk-pixbuf 2.44 ships NO legacy loaders: PNG decoding
  goes through glycin (`libglycin-2.so.0`, the Rust png crate) and never
  reaches libpng. Six independent paired measurements of a +13% libpng win
  showed 0.0% +/- 0.7% on the pixbuf path - a true architectural fact, not
  noise. Do not spend rounds trying to move the pixbuf benchmark with libpng
  changes; it exists as a translation verifier and regression fence only.
- cairo (`cairo_image_surface_create_from_png`) IS the desktop stack's
  direct system-libpng consumer (GTK asset loading, librsvg rasterization,
  screenshots, printing). The validated patch measured +12.3% on the
  cairo-png e2e workload (ratios ~0.890 across 12 alternated pairs, decoded
  pixels byte-identical). That is the certifying end-to-end path.
- The libpng-only micro win (png_image API) measured +13% with the validated
  patch; direct-API consumers (image tools, compositors, custom software)
  get the full benefit.
