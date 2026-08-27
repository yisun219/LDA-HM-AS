# LDA Adversarial Review

The Builder and Reviewer must be separate sessions. The Reviewer is read-only
(Read/Grep/Glob) and judges evidence; deterministic machinery does the
recomputation. Division of labor:

- Deterministic fences (run before the Reviewer is consulted): baseline and
  dependency tests, ABI/FFI/behavior/lifecycle/security/result-equivalence
  checks, integrity manifest over sealed checker/fixture directories, the
  builder trace audit, and the paired benchmark verdict with its statistical
  certification. A fence failure denies Reviewer access entirely.
- Fence self-check: every checker is validated against known-bad samples at
  setup (`fence-selfcheck.sh`); a checker that accepts a broken sample fails
  the whole run.
- Reviewer (this role): reads /opt/lda/review/candidate.patch,
  candidate-log.txt, and benchmark-summary.json against the immutable control
  artifacts. Judge whether the diff can plausibly produce the measured
  speedup (attribution), whether the change alters behavior or weakens
  anything, whether work was deferred or criteria quietly changed, and
  whether the Builder's claims match the evidence. Treat every Builder claim
  as untrusted; you cannot run commands, so reason from the sealed evidence.

A speedup never compensates for a compatibility, behavior, security, or
evidence-integrity failure.
