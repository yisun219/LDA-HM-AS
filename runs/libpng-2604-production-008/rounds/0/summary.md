Round complete. Factual summary follows.

## Summary

**Objective advanced:** The plan's highest-priority unmet criterion — **D1 / Round 0**: apply the pre-certified validated optimization artifact (`/opt/lda/skills/lda-libpng-validated-r0.patch`) verbatim, verify it builds and passes the fences, and commit. Done.

**Changed files (5, exactly the in-scope set):**
- `CMakeLists.txt` — add `intel/filter_sse41_intrinsics.c` to the SSE source list.
- `intel/filter_sse41_intrinsics.c` — **new**: SSE4.1 Paeth3/Paeth4 unfilter (`pabsw` + `pblendvb`).
- `intel/filter_sse2_intrinsics.c` — add `png_read_filter_row_up_sse2` (16 B/iter `_mm_add_epi8`).
- `intel/intel_init.c` — once-per-process `__builtin_cpu_supports("sse4.1")` static-guarded dispatch; Up + Paeth wiring for bpp 3/4.
- `pngpriv.h` — `PNG_INTEL_SSE41_RUNTIME` gate + 3 `PNG_INTERNAL_FUNCTION` (hidden) declarations.

**Commit:** `ad9e005` — "libpng: SSE4.1 Paeth unfilter + SSE2 Up filter with runtime dispatch". Worktree clean.

**Checks run (all pass):**
- ABI fence (ELF/SONAME/symbol-version/pkg-config/abidiff type-level): pass — no exported-symbol/SONAME/DT_NEEDED change.
- Behavior, result-equivalence, FFI, security-hardening fences: pass; decode hashes byte-identical to baseline on all four inputs.
- Baseline (Debian + upstream libpng tests), dependency (Pillow/gdk-pixbuf), package-lifecycle (install/run/rollback): pass.
- Full CMake package build: clean.
- Micro (single-run, byte-exact): boundary flat (0.661s, no regression on the 240k-decode dispatch case), small ~11.6%, large ~10.7%, incompressible ~2.3% faster.
- Cairo e2e (certifying path): baseline 5.591s → candidate 4.996s ≈ **10.6% faster**, byte-identical pixels.

**Speedup mechanism & attribution:**
- Paeth unfilter: collapses the SSE2 multi-op `|x|`/select emulation into single `_mm_abs_epi16` + `_mm_blendv_epi8`; byte-exact because the blend mask comes from `_mm_cmpeq_epi16` (0xFFFF/0x0000 lanes). Attribution: **upstream omission** (upstream stops at SSE2 emulation) combined with **hardware specialization for the pinned Xeon Gold 6548Y+** (SSE4.1), reached only via runtime CPUID so non-SSE4.1 amd64 stays on the SSE2 fallback.
- Up filter: **upstream omission** — upstream leaves it to autovectorization that the package `-O2` does not perform, so an explicit SSE2 (amd64-baseline) loop replaces a scalar byte loop. No `-march`/ISA raise.

This is decode-mechanism work (filter kernels + dispatch), not fixture-byte tuning, so it should hold on the hidden holdout.

**Remaining risks:**
- Benchmark numbers above are single-run in a 2-CPU sandbox; the fences re-run at 7/5 reps and on the hidden holdout — margins (small/large ~10%, cairo ~10%) are comfortably above the 2%/3% thresholds, but final authority rests with the deterministic fences and a fresh Reviewer, not this claim.
- The `have_sse41` first-write race is benign (idempotent value, untorn aligned `int`); left as certified per plan §3b. No locking added.
- Later-round items (D2 Average SIMD, D4 row-output copy, D3 Sub refinement) remain deferred, per the sealed plan.

**Did this round advance the sealed plan?** Yes — Round 0 (D1) is executed and committed; the certifying micro and cairo-e2e criteria are met in-sandbox with ABI/FFI/behavior/security/replacement compatibility preserved.
