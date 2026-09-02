Ultimate Goal

Acceptance Criteria

Active Tasks

Confirmed: lessons line 25 = "lazy static in the unfilter itself", line 26 = "never in the per-image setup path"; and the pngpriv.h additions land at source ~252–266 (runtime gate) and ~1646/~1660–1670 (decls), which the plan had labeled with patch-file coordinates. Corrections applied below.

---

# Candidate Plan (Rev 5) — libpng Decode Optimization, Round 0 (Ubuntu 26.04)

## 0. Preserved Original Draft

The complete Drafter-stage idea is retained verbatim as the plan's source of record (see "Original idea"). Key invariants carried forward unchanged:

- **Primary direction: D1 — execute the prescribed Round 0 verbatim** (apply → compile → verify → commit → end). No modifications in Round 0.
- Retained later-round alternatives in priority order: **D2** (Average-filter SIMD), **D4** (row-output/transform copy), **D3** (Sub-filter refinement). **D5** (AVX2/512 widening) and **D6** (PGO/-O3) are documented traps — rejected.
- Binding constraints for all rounds: micro ≥2%, cairo e2e ≥3%, no per-input regression (esp. 1×1 boundary / 240k-decode dispatch case), pixbuf expectations never touched, dispatch resolved once per process, no baseline ISA raise (no `-march`), ABI/SONAME/symbols/DT_NEEDED unchanged, byte-exact output.

> **Review history:** Rev 2 resolved the P3/N1 execution-vs-location REQUIRED_CHANGE. Rev 3–4 applied cosmetic/defensive improvements (two CONVERGED reviews). Rev 5 (this) resolves the sole remaining REQUIRED_CHANGE — mislabeled verification anchors (patch-file coordinates presented as source coordinates; one off-by-one lessons citation) — and folds in the two optional improvements (up-front build-system detection; tail-correctness note).
>
> **Anchor convention (new, to prevent the recurrence of the fixed defect):** line numbers into the *patch file* `/opt/lda/skills/lda-libpng-validated-r0.patch` are written as **"patch line N"**; line numbers into the *post-apply source* are written as **"`<file>` source ~line N"** (approximate, since they shift on apply). Lessons-file citations are **"lessons line N"**.

---

## 1. Scope & Path Boundaries

### In-scope files (exactly the five the patch touches)
| Path | Change type | Nature |
|------|-------------|--------|
| `CMakeLists.txt` | modify | add `intel/filter_sse41_intrinsics.c` to SSE source list |
| `intel/filter_sse2_intrinsics.c` | modify | add `png_read_filter_row_up_sse2` |
| `intel/filter_sse41_intrinsics.c` | **new file** | SSE4.1 Paeth3/4 variants |
| `intel/intel_init.c` | modify | once-per-process SSE4.1 dispatch + Up wiring |
| `pngpriv.h` | modify | `PNG_INTEL_SSE41_RUNTIME` gate + function decls |

### Out-of-scope (hard boundaries — must NOT be touched in Round 0)
- Any file **not** in the five above.
- Pixbuf benchmark harness, expectations, or glycin path (architecturally immovable by libpng; verifier/fence only).
- Build flags / `-march` / baseline ISA (no ISA raise).
- `png.h`, symbol-version map, SONAME, any exported-symbol surface.
- The Average, Sub kernels and any transform/row-copy code (later-round D2/D3/D4 territory).
- **`Makefile.am` / Autotools build files** — the patch does not touch them; do not improvise an edit (see §5a build-path decision).

---

## 2. Task Breakdown (bounded, ordered)

1. **T1 — Pre-apply base + build-system verification.** (a) Confirm the five target files match the diff's `index`/context hunks (verified in Rev 1 for three anchors; extend to the `filter_sse2_intrinsics.c` sub4 anchor and the pngpriv.h function-decl anchor). Abort if any hunk context mismatches. (b) **Determine the authoritative build system up front** by inspecting the working tree — presence/use of `debian/rules`→`./configure` (Autotools) vs. a driven CMake configure — and record the finding, since this is the only item that can block "verify it compiles" under a verbatim apply (see §5a / §6.2).
2. **T2 — Apply patch verbatim.** Run `git apply --check` first; on success, `git apply` the validated patch with no edits.
3. **T3 — Build (CMake path).** Configure + compile via the **CMake** build path (see §5a); confirm clean compilation of the new SSE4.1 TU and modified units. If T1(b) found Autotools-authoritative, apply the §5a abort-and-report guard.
4. **T4 — Dispatch + ABI sanity inspection.** Confirm: (a) `have_sse41` is a function-local `static int … = -1` resolved once via a single `__builtin_cpu_supports` guarded by `if (have_sse41 < 0)` (patch lines 262–265); (b) the only **dispatch/call-site** references to `png_read_filter_row_paeth{3,4}_sse41` are the two `if (have_sse41)` assignments in `intel_init.c` (patch lines 275–277, 288–290); (c) Up + Paeth wiring is present for both bpp==3 and bpp==4. **Optional ABI spot-check (see §4a):** a near-free `readelf -d` + `nm -D` diff of the built `.so` against the baseline.
5. **T5 — Commit.** Single commit containing the patch application; message records provenance (pre-certified R0 artifact), measured numbers, "no modifications" status, the build system detected in T1(b), and (if run) the optional ABI spot-check result.
6. **T6 — End round.** No further changes. Later-round work (D2/D4/D3) is explicitly deferred.

**Bound:** Round 0 is complete at T6. No optimization design, no new kernels, no benchmark authoring beyond confirming build integrity.

---

## 3. Positive Tests (must pass)

- **P1 (apply):** `git apply --check` reports the patch applies cleanly; after apply, all five files reflect the hunks and `filter_sse41_intrinsics.c` exists.
- **P2 (compile):** Full build succeeds with no errors; `filter_sse41_intrinsics.c` compiles under its `__target__("sse4.1")` function attributes.
- **P3 (dispatch executes once):** The SSE4.1 CPUID probe **executes at most once per process**. The invariant is on *execution*, not textual location: the patch intentionally places `__builtin_cpu_supports("sse4.1")` **inside** `png_init_filter_functions_sse2` (patch lines 262–265), guarded by a function-local `static int have_sse41 = -1` with `if (have_sse41 < 0)`. This placement is **expected, certified, and correct**. Verification confirms the static-guard structure is intact; it does **not** require (and must not induce) moving the call out of the init function. *(See §3a for lessons-tension reconciliation, §3b for the benign-race note, §3c for tail correctness.)*
- **P4 (wiring):** `PNG_FILTER_VALUE_UP` slot assigned `png_read_filter_row_up_sse2` for bpp 3 and 4; Paeth slot upgraded to `paeth{3,4}_sse41` only under `have_sse41`.
- **P5 (byte-exact, inherited certification):** Decoded output byte-identical to pre-patch across all four certification inputs incl. the 1×1 boundary (rely on prior certification recorded in lessons; optional local re-run per §6.1). Byte-identity is additionally guaranteed by the new TU's own construction: the select mask from `_mm_cmpeq_epi16` (0xFFFF/0x0000 per lane) makes `_mm_blendv_epi8` select identically to the SSE2 and/andnot/or expression.
- **P6 (ABI):** SONAME, exported symbol set, symbol versions, and DT_NEEDED unchanged vs. baseline. The patch adds **three** new internal functions — `png_read_filter_row_up_sse2` (declared at **patch line 332**, landing in **pngpriv.h source ~line 1646** after apply) and the two `png_read_filter_row_paeth{3,4}_sse41` (declared at **patch lines 347–353**, landing in **pngpriv.h source ~lines 1660–1670**) — all declared `PNG_INTERNAL_FUNCTION` (hidden), so none enters the exported ABI surface. *(Optionally observed this round via §4a.)*

### 3a. Lessons-tension reconciliation (preempt a future "fix")
The lessons file says dispatch must be resolved "never in the per-image setup path" (**lessons line 26**), yet the certified patch's guarded static **does** sit inside `png_init_filter_functions_sse2`. This is **not** a contradiction: the *expensive* CPUID executes exactly once (static-guarded), and only a trivial `static int` branch is per-image. Moreover, the certified placement is **strictly more conservative than the lessons' own suggested remedy**: `png_init_filter_functions_sse2` runs once **per image**, whereas the lessons' proposed "lazy static in the unfilter itself" (**lessons line 25**) would evaluate the guard branch once **per row** — a far higher frequency. The certified design therefore has *lower* dispatch-check frequency than the alternative the lessons recommended, which is exactly why it clears the 240k/1×1 veto. **Do not relocate the CPUID call in Round 0.**

### 3b. Benign-race footnote (do not "fix")
Concurrent first-calls from multiple threads could race on `have_sse41`. The race is **benign**: every writer stores the same value (the CPU's fixed SSE4.1 capability), and an aligned `int` load/store is not torn on the target. This is not a defect; **do not add locking/atomics in Round 0** — such a change would breach the verbatim mandate and is unnecessary.

### 3c. Tail-correctness footnote (do not "fix")
The two SSE4.1 kernels use asymmetric tail handling that is **byte-exact per prior certification**: `paeth3_sse41` processes 4-byte chunks in `while (rb >= 4)` then a final 3-byte tail via `if (rb > 0)` using `load3_41`/`store3_41` (patch lines 176–201); `paeth4_sse41` uses `rb = row_info->rowbytes + 4; while (rb > 4)` with 4-byte steps (patch lines 216–241). These constructions are intentional and certified; **do not "normalize" the asymmetric tail** in Round 0.

## 4. Negative Tests (must fail / must be absent)

- **N1 (no *repeated* CPUID):** The CPUID probe must not **execute** on a per-image or per-row basis. The forbidden condition is *unguarded or re-executing* dispatch resolution reached on every image/row, which would regress the 240k-decode 1×1 case past the 2% veto. **Textual presence of the guarded, once-executing `__builtin_cpu_supports` inside `png_init_filter_functions_sse2` is NOT a violation** — it is the certified design. Do not "fix," relocate, or otherwise modify this call in Round 0.
- **N2 (SSE4.1 unreachable without support):** `paeth*_sse41` must be unreachable unless `have_sse41==1` (no fault on non-SSE4.1 amd64). Concrete check: the only **dispatch/call-site** references to these two symbols are the two `if (have_sse41)` assignments in `intel_init.c` (patch lines 275–277, 288–290). *(They are additionally declared in pngpriv.h — patch lines 347–353, source ~1660–1670 — and defined in the new TU; those are declarations/definitions, not call-sites, and must not be flagged.)*
- **N3:** No new DT_NEEDED, no SONAME bump, no new exported symbol.
- **N4:** No `-march`/baseline-ISA change in build config.
- **N5:** No edits outside the five in-scope files; pixbuf expectations untouched; no `Makefile.am`/Autotools edit.
- **N6:** No AVX/VEX-128 encodings and no AVX2/512 widening introduced (documented trap).

### 4a. Optional ABI spot-check (defensive, not required)
The task requires only "verify it compiles," so P6/N3 may rest on inherited certification. Because it is nearly free, an optional local `readelf -d` (DT_NEEDED / SONAME) plus `nm -D` (dynamic symbol set) diff of the freshly built `.so` against the baseline library would make the ABI invariant **observed this round** rather than only inherited. This is a read-only verification step; it changes no source and is safe under the verbatim mandate.

---

## 5. Guardrails Inherited (later rounds)

- SSE2 remains the always-valid fallback → library stays drop-in on non-SSE4.1 amd64.
- pixbuf = verifier/regression fence only (immovable by libpng; do not target it).
- cairo (`cairo_image_surface_create_from_png`) = the certifying e2e path; any later gain must clear cairo e2e ≥3% and micro ≥2% with no per-input regression.
- D2 must **not** assume `_mm_avg_epu8` semantics for Average's `(a+b)>>1`; requires byte-exact validation.
- D6 (if ever) must profile the row-by-row `png_read_row` progressive path, never the one-shot `png_image` API.

## 5a. Build-Path Decision (resolved)

**Decision:** Round 0 builds via the **CMake** path. Rationale: the patch touches only `CMakeLists.txt`; `PNG_INTEL_SSE41_RUNTIME` auto-defines on GCC/x86 (added by **patch lines 306–323**, landing in **pngpriv.h source ~lines 252–266**), so — **effectively unconditionally on the target toolchain** — `intel_init.c`'s references (under `#ifdef PNG_INTEL_SSE41_RUNTIME`) to `png_read_filter_row_paeth{3,4}_sse41` are compiled in, while the *definitions* live only in the new TU added to CMake's source list. An **Autotools** build (which the patch does not update) would therefore fail at **link time** with an undefined reference — not at compile time. **Abort-and-report condition:** if T1(b) finds the authoritative package build is Autotools and a link failure appears, stop and report; do **not** improvise a `Makefile.am` edit (that would breach the verbatim mandate). The prior certification succeeded, confirming a valid build path (almost certainly CMake) exists.

---

## 6. Unresolved Human Decisions (retained explicitly)

1. **Benchmark re-run vs. inherited certification (non-blocking).** Task text ("verify it compiles"; no re-derivation demanded) implies inherited certification suffices. An optional in-sandbox confirmation run of micro + cairo e2e is harmless but not required. *User confirmation welcome, not blocking Round 0.*
2. **Authoritative Ubuntu 26.04 build system (highest-signal open item; now inspected up front in T1(b)).** Debian/Ubuntu `libpng1.6` has historically built via **Autotools** (`debian/rules`→`./configure`), which the patch does **not** update; a verbatim apply would then link-fail on `paeth*_sse41`, and "verify it compiles" can only be satisfied via the **CMake** path. Working assumption is CMake (see §5a) with abort-and-report on Autotools link failure and no `Makefile.am` edit. T1(b) now detects this from the working tree before building; prior certification succeeding implies a valid path exists (supports but does not prove the assumption). *If the user knows the package build is Autotools-authoritative and CMake is not acceptable for the deliverable, flag before T3.*
3. **Independent-analysis API error (process note only, non-blocking).** The Rev-1 analysis field returned a `[cyber]` safeguard false-positive with no technical content; four subsequent independent reviews supplied full artifact-verified assessments, so technical grounding is confirmed. No action needed unless the user wants the analysis stage re-run for the record.
4. **Round 1 target = D2 (deferred).** Confirm D2 (Average SIMD) as the intended Round 1 target, or hold until Round 0 is merged. No bearing on Round 0.

---

## 7. Convergence Status

The sole remaining **REQUIRED_CHANGE** — verification anchors that used patch-file line numbers while labeling them as source (`pngpriv.h`) line numbers, plus a §3a lessons citation off by one — is resolved: an explicit **anchor convention** is introduced (§0), every affected reference is relabeled as "patch line N" with an approximate "pngpriv.h source ~line N" for the implementer (P6, N2, §5a), and the §3a citation is corrected to **lessons line 25** ("lazy static in the unfilter itself") vs. **line 26** ("never in the per-image setup path"), both verified against the files this round. Both OPTIONAL_IMPROVEMENTS are incorporated: build-system detection is pulled forward into **T1(b)** (§6.2), and a **§3c tail-correctness footnote** preempts an out-of-mandate "fix" of the asymmetric Paeth tail. Remaining §6 items are non-blocking human decisions retained explicitly; §6.2 stays a human-flagged abort-and-report guard rather than a premature resolution.

*Planner stage output only. No source files edited, no build/commit performed. Reads were for verification and grounding only.*
