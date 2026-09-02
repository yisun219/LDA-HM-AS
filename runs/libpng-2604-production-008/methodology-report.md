I've gathered the grounding artifacts. Note: `/opt/lda/review` presented as a directory but I could not locate any populated files in it despite extensive probing (no "did-you-mean" matches surfaced, unlike `/opt/lda/control`), so it appears empty for this round. My analysis is therefore grounded in: the immutable plan (`control/plan.md`, Rev 5), the goal tracker (`control/goal-tracker.md`), the lessons ledger (`skills/lessons.md`), the validated patch (`skills/lda-libpng-validated-r0.patch`), the Builder's commit message (`.git/COMMIT_EDITMSG`), the reflog (`.git/logs/HEAD`), and the applied source in the work tree.

---

# Methodology Report — libpng Decode Optimization, Round 0

## 1. What the round actually did (observed)
Round 0 was a **verbatim-apply** round: take the pre-certified patch, confirm it applies, compile-check, commit, stop. The work tree confirms this literally — `intel/filter_sse41_intrinsics.c`, `intel/intel_init.c`, and (by the commit) the other three files match the patch **byte-for-byte** (I diffed the applied `intel_init.c` and the new TU header against the patch; identical, including comments). The reflog shows one substantive commit (`ad9e005`) preceded by a reset to baseline and followed by a no-op reset to itself — i.e., a clean single-commit landing, tree clean.

## 2. Builder choices that produced measured progress
- **Reusing the certified artifact instead of re-deriving** (lessons §"Confirmed wins" explicitly directs this). The gains are *inherited* certification, not re-measured this round: +6–7% micro Paeth aggregate, **+12.3% cairo-png e2e** (ratios ~0.890 across 12 alternated pairs, byte-identical pixels), +13% `png_image` micro.
- **The mechanism itself:** replace the SSE2 Paeth `and/andnot/or` select + multi-op `|x|` with single `pabsw` (`_mm_abs_epi16`) + `pblendvb` (`_mm_blendv_epi8`); add an SSE2 Up filter (16 B/iter `_mm_add_epi8`) because the package's `-O2` does **not** autovectorize the generic byte loop (a measured, non-obvious gap the commit calls out).
- **Correct build-system identification (the decisive T1(b) call):** the commit records `debian/rules: dh --buildsystem=cmake` → **CMake authoritative**. This is the single item that could have blocked "verify it compiles," because the new TU is only in the CMake source list; an Autotools build would *link*-fail. Resolving this up front was the highest-signal choice of the round.
- **Compile evidence with substance:** the commit states the focused compile emits `pabsw/pblendvb/pminsw`, i.e., the intended SSE4.1 instructions were actually generated, not merely that the file parsed.

## 3. Fences that protected correctness
- **Byte-exactness (structural + inherited):** the blend mask originates from `_mm_cmpeq_epi16` (0xFFFF/0x0000 per lane), so `pblendvb` selects *identically* to the SSE2 expression — correctness is a construction property, not just a test result; backed by prior certification across all four inputs incl. the 1×1 boundary.
- **Dispatch-frequency fence:** `static int have_sse41 = -1` resolved once via `__builtin_cpu_supports`, **outside** the per-row path. This is what clears the documented 2% veto on the 240k-decode 1×1 case (lessons "Confirmed traps").
- **ABI fence:** all three new functions are `PNG_INTERNAL_FUNCTION` (hidden), with **distinct names** so SSE2 remains an always-valid fallback → no SONAME/symbol/DT_NEEDED change, library stays drop-in on non-SSE4.1 amd64.
- **Scope fence:** exactly the five in-scope files; no `Makefile.am`/Autotools edit, no `-march`/ISA raise.
- **Anti-"fix" fences (the round's most important discipline):** the plan's §3a/§3b/§3c pre-empted three *tempting but out-of-mandate* changes — relocating the CPUID probe, adding atomics for the benign `have_sse41` race, and "normalizing" the asymmetric Paeth3/4 tail. The Builder honored all three (applied source is unmodified), preserving the certification.

## 4. Failed or misleading approaches (correctly avoided)
- **A misleading lesson caught by the plan:** lessons line 26 ("dispatch … never in the per-image setup path") read literally would push the CPUID *into the unfilter* (per-row) — strictly *higher* frequency. §3a correctly reconciled that the certified per-image-once placement is *more* conservative than the lesson's own suggested remedy. This is the clearest case where following an artifact literally would have regressed the veto.
- **Autotools link-failure trap:** avoided by the CMake determination (§5a / T1(b)).
- **Documented rejected traps (D5/D6):** VEX-128 re-encoding measured slower (SSE↔AVX transition penalties); AVX2 widening of a serial recurrence saturates at 128 bits; PGO/-O3 on an unrepresentative profile measured slightly negative. All correctly deferred/rejected.
- **pixbuf as a dead target:** on Ubuntu 26.04, PNG decode goes through glycin (Rust), never libpng; a +13% libpng win moved pixbuf 0.0%±0.7% over six paired runs. Correctly treated as a regression fence only, not a target.
- **Process misfire:** the Rev-1 independent-analysis stage returned a `[cyber]` safeguard false-positive with no technical content — a tooling artifact, not a technical finding; compensated by four later artifact-verified reviews.

## 5. Residual uncertainty
- **Performance not re-measured this round.** All headline numbers are *inherited* from prior certification. Acceptable under the "verify it compiles" mandate, but the +12.3% cairo / +6–7% micro / 1×1-veto clearance were **not re-observed** here.
- **Compile check was focused, not a full package build.** Link-time integration under the real `debian/rules` CMake build was not exercised; only that the new/modified TUs compile and emit the expected opcodes.
- **ABI invariance is argued/inherited, not observed.** The optional `readelf -d` / `nm -D` spot-check (§4a) is not reported in the commit; P6/N3 rest on the hidden-symbol construction plus prior certification.
- **Benign-race assumption** on `have_sse41` depends on non-torn aligned-`int` load/store on the target — correct for the pinned Xeon, but an unverified-this-round assumption.

## 6. Reusable lessons
- **Pre-certified-artifact reuse + verbatim apply** is high-leverage/low-risk *when* paired with explicit anti-"improvement" fences; the discipline of *not* refining the artifact is what preserves the certification.
- **Encode "looks-wrong-but-is-right" reconciliations in the plan** (the CPUID placement is the exemplar) to inoculate against well-intentioned regressions by later stages.
- **Resolve build-system authority before claiming "it compiles"** — the compile-vs-link failure mode depends entirely on it; make it the first task, not an afterthought.
- **Distinct-symbol + one-time runtime CPUID dispatch + always-valid baseline fallback** is the reusable recipe for ISA specialization at zero ABI/portability cost.
- **Measure translation reality; target the real consumer** (cairo), not the architecturally disconnected one (pixbuf/glycin). Assumed benchmark relevance is a trap that only measurement exposes.
- **Prefer structural correctness arguments** (mask-equivalence guaranteeing byte-exactness) over test-only assurance where the math permits it.

*Analyst stage: reads only; no source, evidence, or artifacts modified.*
