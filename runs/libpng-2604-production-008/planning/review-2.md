I verified the candidate plan's specific claims against both the lessons file and the actual patch. My findings below.

## AGREE

- **Primary direction is correct and mandated.** D1 (apply verbatim → compile → verify → commit → end) is exactly what the task prescribes. The plan does not deviate.
- **Scope table matches the patch.** The five in-scope files (`CMakeLists.txt`, `filter_sse2_intrinsics.c`, new `filter_sse41_intrinsics.c`, `intel_init.c`, `pngpriv.h`) are precisely what the diff touches — nothing more.
- **Line-reference claims check out.** I verified each cited anchor against the patch: dispatch guard at patch lines 262–265; `if (have_sse41)` call-sites at 275–277 and 288–290; `up_sse2` decl at 332; the two `paeth*_sse41` decls at 347–353; auto-define block at 317–323. All accurate.
- **P6 "three new internal functions" is correct.** `png_read_filter_row_up_sse2` + `paeth3_sse41` + `paeth4_sse41`, all declared `PNG_INTERNAL_FUNCTION` (hidden) → no exported-ABI change. Confirmed in the diff.
- **N2 unreachability reasoning is correct.** The only *call-site* references to the SSE4.1 symbols are the two `if (have_sse41)` assignments; the pngpriv.h decls and the new-TU definitions are correctly excluded as non-call-sites. Byte-identical output is guaranteed by the patch's own comment (mask from `_mm_cmpeq_epi16` makes `_mm_blendv_epi8` select identically to the SSE2 and/andnot/or).
- **The §3a / N1 lessons-tension handling is the single most important thing this plan gets right.** The lessons (line 26) say resolve dispatch "never in the per-image setup path," yet the certified patch places the guarded static *inside* `png_init_filter_functions_sse2`. The plan correctly refuses to "fix" this under the verbatim mandate and correctly reasons that only a predictable branch is per-image while CPUID runs once. I independently confirm the reconciliation is sound.

## DISAGREE

- None that changes the work.

## REQUIRED_CHANGES

- None. Every claim I could verify against the artifacts is accurate, and the plan honors the verbatim mandate.

## OPTIONAL_IMPROVEMENTS

1. **Strengthen the tension argument (§3a).** Note that the patch's placement is actually *more* conservative than the lessons' own suggested remedy: init runs once **per image**, whereas the lessons' proposed "lazy static in the unfilter itself" would run once **per row**. So the certified design has strictly lower dispatch-check frequency than the alternative the lessons recommended — reinforcing why it passes the 240k/1×1 veto. This turns an apparent contradiction into a positive.
2. **Add a cheap post-build ABI spot-check to T4/T5.** P6/N3 assert SONAME/DT_NEEDED/dynsym unchanged but rely purely on inherited certification. Since a `readelf -d` + `nm -D` diff against the baseline `.so` is nearly free, running it locally would make the ABI invariant *observed* this round, not just inherited. Not required (task only says "verify it compiles").
3. **Thread-safety footnote on the static guard.** Concurrent first-calls could race on `have_sse41`, but the race is benign (all writers store the same value; no torn read of an `int` on the target). Worth a one-line note so it isn't mistaken for a defect and "fixed" in violation of verbatim.

## UNRESOLVED

- **Authoritative Ubuntu 26.04 build system (§6.2).** Genuinely open and correctly handled. The patch updates only `CMakeLists.txt`; if the package build is Autotools and does not add the new TU, verbatim apply link-fails on `paeth*_sse41` (since `PNG_INTEL_SSE41_RUNTIME` auto-defines on GCC/x86, so `intel_init.c` references the symbols unconditionally on the target). The plan's abort-and-report guard with a CMake working assumption is the right stance — and the fact that prior certification succeeded implies a valid path exists. This must remain a human-flagged item, not a premature resolution.
- **Optional local re-run of micro/cairo (§6.1)** and **Round 1 = D2 confirmation (§6.4)** — non-blocking, correctly deferred.

---

**CONVERGED.** The plan matches the artifacts on every verifiable point, executes the prescribed Round 0 verbatim, and — critically — pre-empts the one trap that could derail a well-meaning implementer (relocating the certified in-init CPUID guard). There are no required changes and no disagreement that alters the work. The three optional improvements are cosmetic/defensive, and the one substantive open item (build system) is properly retained as an abort-and-report guard rather than resolved by improvising an out-of-mandate `Makefile.am` edit.
