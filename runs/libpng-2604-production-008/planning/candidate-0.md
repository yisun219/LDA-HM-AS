Base tree verified — all three inspected hunks match the patch context exactly (`intel_init.c` has the pre-patch two-branch dispatch and the "No need optimize" comment; `CMakeLists.txt` lines 230–232 match the SSE source list; `pngpriv.h` has the `PNG_INTEL_SSE_IMPLEMENTATION` block the new hunk anchors to). The `git apply` should apply cleanly.

---

# Candidate Plan — libpng Decode Optimization, Round 0 (Ubuntu 26.04)

## 0. Preserved Original Draft

The complete Drafter-stage idea is retained verbatim as the plan's source of record (see "Original idea" above). Key invariants carried forward unchanged:

- **Primary direction: D1 — execute the prescribed Round 0 verbatim** (apply → compile → verify → commit → end). No modifications in Round 0.
- Retained later-round alternatives in priority order: **D2** (Average-filter SIMD), **D4** (row-output/transform copy), **D3** (Sub-filter refinement). **D5** (AVX2/512 widening) and **D6** (PGO/-O3) are documented traps — rejected.
- Binding constraints for all rounds: micro ≥2%, cairo e2e ≥3%, no per-input regression (esp. 1×1 boundary / 240k-decode dispatch case), pixbuf expectations never touched, dispatch resolved once per process, no baseline ISA raise (no `-march`), ABI/SONAME/symbols/DT_NEEDED unchanged, byte-exact output.

> **Note on independent analysis:** the supplied independent-analysis field returned an API error (`[cyber]` safeguard false-positive on legitimate SIMD/CPUID optimization work) and contained no technical content. This plan therefore rests on the original idea plus my direct reading of the two prescribed artifacts (lessons file + validated patch) and verification against the live base tree. This gap is logged as an unresolved item (§6).

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
- The Average, Sub kernels and any transform/row-copy code (those are later-round D2/D3/D4 territory).

---

## 2. Task Breakdown (bounded, ordered)

1. **T1 — Pre-apply base verification.** Confirm the five target files match the diff's `index`/context hunks (partially done above; extend to `filter_sse2_intrinsics.c` sub4 anchor and pngpriv.h function-decl anchor). Abort if any hunk context mismatches.
2. **T2 — Apply patch verbatim.** `git apply` the validated patch with no edits. Prefer a dry-run check (`git apply --check`) before the real apply.
3. **T3 — Build.** Configure + compile the package as shipped; confirm clean compilation of the new SSE4.1 TU and modified units.
4. **T4 — Dispatch sanity inspection.** Confirm the CPUID resolution is a lazy static resolved once (no per-image/per-row `__builtin_cpu_supports`), and that Up + Paeth wiring is present for both bpp==3 and bpp==4.
5. **T5 — Commit.** Single commit containing the patch application; message records provenance (pre-certified R0 artifact), measured numbers, and "no modifications" status.
6. **T6 — End round.** No further changes. Later-round work (D2/D4/D3) is explicitly deferred.

**Bound:** Round 0 is complete at T6. No optimization design, no new kernels, no benchmark authoring beyond confirming build integrity.

---

## 3. Positive Tests (must pass)

- **P1 (apply):** `git apply --check` reports the patch applies cleanly; after apply, all five files reflect the hunks and `filter_sse41_intrinsics.c` exists.
- **P2 (compile):** Full build succeeds with no errors; `filter_sse41_intrinsics.c` compiles under its `__target__("sse4.1")` function attributes.
- **P3 (dispatch-once):** Static analysis/inspection confirms `have_sse41` is a function-local static resolved once; no CPUID in per-row/per-image hot path.
- **P4 (wiring):** `PNG_FILTER_VALUE_UP` slot assigned `png_read_filter_row_up_sse2` for bpp 3 and 4; Paeth slot upgraded to `paeth{3,4}_sse41` only under `have_sse41`.
- **P5 (byte-exact, inherited certification):** Decoded output byte-identical to pre-patch across all four certification inputs incl. the 1×1 boundary (re-confirm if the harness is available; otherwise rely on prior certification recorded in lessons).
- **P6 (ABI):** SONAME, exported symbol set, symbol versions, and DT_NEEDED unchanged vs. baseline; the two new symbols are internal/hidden only.

## 4. Negative Tests (must fail / must be absent)

- **N1:** No per-image or per-row `__builtin_cpu_supports` / CPUID call (would regress the 240k-decode 1×1 case past the 2% veto).
- **N2:** No SSE4.1 instruction reachable on the default SSE2 dispatch path — `paeth*_sse41` must be unreachable unless `have_sse41==1` (no fault on non-SSE4.1 amd64).
- **N3:** No new DT_NEEDED, no SONAME bump, no new exported symbol.
- **N4:** No `-march`/baseline-ISA change in build config.
- **N5:** No edits outside the five in-scope files; pixbuf expectations untouched.
- **N6:** No AVX/VEX-128 encodings and no AVX2/512 widening introduced (documented trap).

---

## 5. Guardrails Inherited (later rounds)

- SSE2 remains the always-valid fallback → library stays drop-in on non-SSE4.1 amd64.
- pixbuf = verifier/regression fence only (immovable by libpng; do not target it).
- cairo (`cairo_image_surface_create_from_png`) = the certifying e2e path; any later gain must clear cairo e2e ≥3% and micro ≥2% with no per-input regression.
- D2 must **not** assume `_mm_avg_epu8` semantics for Average's `(a+b)>>1`; requires byte-exact validation.
- D6 (if ever) must profile the row-by-row `png_read_row` progressive path, never the one-shot `png_image` API.

---

## 6. Unresolved User Decisions

1. **Benchmark re-run vs. inherited certification.** Round 0 mandates apply-only. Should T5 re-run micro + cairo e2e to re-confirm the +12.3% / +6–7% locally, or rely solely on the recorded prior certification? (Task text implies no re-derivation required; confirm whether an in-sandbox confirmation run is wanted.)
2. **Build system.** Package ships both CMake and Autotools; the patch only edits `CMakeLists.txt`. Confirm the Ubuntu 26.04 package build path in use (CMake assumed). If Autotools is authoritative, the SSE4.1 TU may need a corresponding makefile inclusion — **flag before build**, do not improvise in Round 0.
3. **Independent-analysis gap.** The independent analysis was unavailable (safeguard error). Approve proceeding on the original idea + direct artifact reading, or request a re-run of the analysis stage before Round 0?
4. **Next-round selection.** Confirm D2 (Average SIMD) as the intended Round 1 target, or hold until Round 0 is merged.

---

*Planner stage output only. No source files edited, no build/commit performed. Reads were for verification and grounding only.*
