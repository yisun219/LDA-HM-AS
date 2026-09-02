I've verified the candidate plan against the actual patch and lessons file. Both artifacts match the plan's descriptions faithfully. My assessment:

## AGREE

- **Primary direction is correct and mandatory.** D1 (apply verbatim → compile → commit → end) is exactly what the task prescribes and what the lessons file directs ("Apply it with `git apply`... instead of re-deriving"). The plan preserves this without deviation.
- **Scope boundary is accurate.** The plan's five in-scope files exactly match the patch's five diff targets (`CMakeLists.txt`, `filter_sse2_intrinsics.c`, `filter_sse41_intrinsics.c` [new], `intel_init.c`, `pngpriv.h`). Verified against the diff headers.
- **Rejections are sound.** D5 (AVX/VEX-128, AVX2 widening) and D6 (PGO/-O3) are documented traps in the lessons file (lines 27–33); the plan correctly rejects them and retains D6's "profile the `png_read_row` progressive path" caveat.
- **Retained alternatives ordered correctly.** D2 (Average SIMD) as top later-round candidate, with the crucial `_mm_avg_epu8` ≠ `(a+b)>>1` warning preserved. Matches the idea.
- **Constraint set is complete and correctly carried:** micro ≥2%, cairo e2e ≥3%, no per-input regression (1×1/240k case), pixbuf-as-fence-only, once-per-process dispatch, no `-march`, ABI/SONAME/DT_NEEDED unchanged, byte-exact.
- **pixbuf immovability correctly encoded** as an architectural fact (glycin/Rust png crate), verifier-only — matches lessons lines 35–42.

## DISAGREE

- None material. The plan does not contradict the original idea on any decision that changes the work.

## REQUIRED_CHANGES

1. **Clarify N1/P3 wording to prevent a false-positive that could trigger a forbidden modification.** N1 states "No per-image or per-row `__builtin_cpu_supports`/CPUID call." But the validated patch *textually places* `__builtin_cpu_supports("sse4.1")` **inside** `png_init_filter_functions_sse2` (a per-image function), guarded by a function-local `static int have_sse41 = -1` so the CPUID *executes* only once per process (patch lines 262–265). A literal reading of N1 would flag the very patch being applied as a violation, tempting the executor to "fix" it and break the verbatim mandate. N1/P3 must be reworded to state the real invariant: *the CPUID must **execute** at most once per process (static-guarded); textual presence inside the per-image init function is expected and certified.* This is the single change needed to keep Round 0 truly verbatim.

## OPTIONAL_IMPROVEMENTS

- **Build-system resolution (plan §6.2) should be pre-decided, not left open.** The patch edits only `CMakeLists.txt`, never `Makefile.am`. Since `intel_init.c` references `png_read_filter_row_paeth{3,4}_sse41` whenever `PNG_INTEL_SSE41_RUNTIME` auto-defines (pngpriv.h lines 317–323, unconditional on GCC/x86), an **Autotools** build that doesn't compile the new TU would fail at **link** (undefined reference), not compile. The prior certification necessarily succeeded, and the only build file the patch touches is CMake — so the executor should default to the **CMake** build path and treat a link failure as the signal, not improvise a `Makefile.am` edit (which would breach verbatim). Recommend elevating "assume CMake" from an open question to the working assumption, with Autotools link-failure as an explicit abort-and-report condition.
- **T4/N2 verification method:** confirming `paeth*_sse41` is unreachable without SSE4.1 can be checked cheaply by confirming the only references are the two `if (have_sse41)` assignments (intel_init.c lines 275–277, 288–290). Worth naming that concrete check rather than "static analysis."

## UNRESOLVED

- **§6.1 (re-run vs. inherited certification):** Task text ("verify it compiles," no re-derivation demanded) implies inherited certification suffices; an optional in-sandbox confirmation run is harmless but not required. User confirmation welcome but not blocking.
- **§6.3 (independent-analysis API error):** A process artifact only. My independent read of both artifacts confirms the plan's technical grounding, so this does not block Round 0. No further action needed unless the user wants the analysis stage re-run for the record.
- **§6.4 (Round 1 = D2):** Correctly deferred; no bearing on Round 0.

---

Not CONVERGED. One required change remains: reword N1/P3 so the once-per-process **execution** invariant (static-guarded CPUID) is not misread as forbidding the CPUID's textual presence in the per-image init function — otherwise the executor risks "correcting" the pre-certified patch and violating the verbatim mandate. Once that wording is fixed, the plan is ready.
