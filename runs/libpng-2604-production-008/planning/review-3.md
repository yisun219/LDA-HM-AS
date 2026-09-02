I verified the candidate plan's anchors directly against `/opt/lda/skills/lda-libpng-validated-r0.patch` and `/opt/lda/skills/lda-libpng-lessons.md`.

## AGREE

- **Primary direction (D1, verbatim R0).** Matches the mandate. Apply → build → verify → commit → end, no modifications. Correct.
- **Scope table.** The five in-scope files exactly match the patch (`CMakeLists.txt`, `filter_sse2_intrinsics.c`, new `filter_sse41_intrinsics.c`, `intel_init.c`, `pngpriv.h`). Out-of-scope boundaries (pixbuf/glycin, `-march`, `png.h`/SONAME, `Makefile.am`) are correct.
- **§3a / P3 / N1 lessons reconciliation is substantively correct and well-argued.** Verified: the expensive `__builtin_cpu_supports("sse4.1")` is behind `static int have_sse41 = -1; if (have_sse41 < 0)` (patch lines 262–265), so CPUID runs once per process; only a trivial `int` branch is per-image. The claim that the certified in-init placement (once **per image**) is strictly less frequent than the lessons' own "lazy static in the unfilter itself" suggestion (once **per row**) is accurate and is the right rebuttal to a future "relocate the CPUID" fix.
- **§3b benign-race / "do not add atomics."** Correct — same value stored, aligned int, and any change would breach the verbatim mandate.
- **N2 unreachability.** Verified: the only call-sites of `paeth{3,4}_sse41` are the two `if (have_sse41)` blocks (patch lines 275–277, 288–290); the pngpriv.h entries and TU are declarations/definitions, not call-sites.
- **P6/N3 ABI.** Verified: exactly three new functions (`up_sse2` + two `paeth*_sse41`), all `PNG_INTERNAL_FUNCTION` (hidden); no exported-surface change. The §4a read-only `readelf -d`/`nm -D` spot-check is a sound, mandate-safe addition.
- **Trap handling.** D5 (AVX/VEX-128, AVX2 saturation) and D6 (mis-profiled PGO) rejections match the lessons file; D2/D4/D3 retention/order preserved.
- **Build-path reasoning.** Technically correct: `PNG_INTEL_SSE41_RUNTIME` auto-defines on GCC/x86 (patch's pngpriv.h block), so `intel_init.c` references `paeth*_sse41` unconditionally on-target while the definitions live only in the CMake-added TU; an Autotools build (patch doesn't touch `Makefile.am`) would **link-fail**, not compile-fail. Abort-and-report rather than improvising a `Makefile.am` edit is the right call.

## DISAGREE

- None on substance.

## REQUIRED_CHANGES

1. **Fix the file-coordinate mislabeling of pngpriv.h anchors.** The references "`up_sse2` (pngpriv.h line 332)", "paeth41 (pngpriv.h lines 347–353)", and "`PNG_INTEL_SSE41_RUNTIME` … (pngpriv.h lines 317–323)" are **patch-file** line numbers, not pngpriv.h **source** line numbers. Per the hunk headers (`@@ -250,6 +250,21 @@` and `@@ -1628,6 +1643,9 @@`), those additions land near pngpriv.h source lines ~253–267 and ~1646–1670. As written, an implementer opening pngpriv.h at "line 332" for T1/T4 verification will land on unrelated code. Relabel these as "patch lines" (as the plan already correctly does for `intel_init.c`, e.g., patch lines 275–277) or substitute true source line numbers. Also: the §3a phrase "lazy static in the unfilter itself" is on lessons **line 25**, not line 26 (line 26 carries "never in the per-image setup path"). This does not change the apply/build/commit work, but it corrupts the verification anchors the plan leans on, so it must be corrected before convergence.

## OPTIONAL_IMPROVEMENTS

1. **Resolve §6.2 at T1/T3 rather than deferring.** The authoritative build system is directly observable in the working tree (presence and use of `debian/rules`→`./configure` vs. a driven CMake configure). Since this is the only item that can actually block "verify it compiles," inspect it up front instead of carrying it as a standing assumption.
2. **Add a one-line tail-correctness note.** paeth3's `if (rb > 0)` 3-byte tail (via `load3_41`) and paeth4's `rb = rowbytes+4; while (rb > 4)` construction are byte-exact per prior certification; noting this preempts a reviewer flagging the asymmetric tail handling.

## UNRESOLVED

- **§6.2 build system (CMake vs Autotools).** Genuinely open and the single item that could prevent satisfying "verify it compiles" under verbatim apply. Abort-and-report is the correct guard; not resolvable from the plan alone.
- **§6.1 inherited certification vs. optional local benchmark re-run.** Non-blocking; task requires only compile verification.
- **§6.4 Round 1 = D2 confirmation.** Deferred, no bearing on R0.

## Status

**NOT CONVERGED** — one REQUIRED_CHANGE remains (the pngpriv.h/lessons line-label inaccuracy in the verification anchors). It is a text-precision fix only; the substantive plan (verbatim D1 apply → CMake build → sanity/ABI checks → single commit → end round) is correct, faithful to the original idea, and verified against the patch. Once the anchor labels are corrected, I would expect CONVERGED.
