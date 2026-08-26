# 历史 ISO Baseline 调整 Prompt

> 历史说明：这份 Prompt 早于当前固定 Packages/Sources Snapshot 实现，仅作为设计
> 演化记录保留，不是当前运行规范。当前行为以 `docs/BASELINE.md` 为准。

You are modifying the LDA-HM flow for Ubuntu 26.04 package optimization.
Preserve the Humanize control loop, but make the execution baseline
distribution-anchored and reproducible.

## Required baseline model

Use the official Ubuntu 26.04 Desktop amd64 ISO as the authoritative input.
Do not treat a generic Ubuntu image or a live apt-get source result as the
complete system baseline. Convert the ISO into an immutable E2B stock snapshot
and record:

~~~text
release=26.04
codename=resolute
edition=desktop
architecture=amd64
iso_sha256
iso_build_id
debian_manifest_sha256
snap_manifest_sha256
apt_snapshot
rootfs_digest
package_inventory_digest
snap_inventory_digest
~~~

## Flow changes

1. Add a baseline-resolution phase before source setup.
2. Select the E2B template from the task card, not from an implicit default.
3. Verify release, codename, architecture, ISO metadata, manifests, rootfs,
   package inventory, and Snap inventory inside E2B.
4. Fail closed before Builder or Reviewer starts when identity verification
   fails.
5. Pin the exact source package version and APT snapshot. Never use an
   unversioned package fetch in strict mode.
6. Preserve the A/B/A' model: pristine stock, candidate replacement, and a
   fresh restored stock copy.
7. Run micro benchmarks at package scope and end-to-end benchmarks on the full
   ISO-derived Desktop environment.
8. Store all baseline identities and digests in resumable Flow state and
   artifacts.
9. Use the ISO dependency graph to rank candidate packages by fan-in,
   required out-degree, total out-degree, priority, and metadata validity.
10. Keep ABI/FFI, behavior, dependency, lifecycle, security, result
    equivalence, trace audit, and restore fences ahead of semantic review.

## Acceptance criteria

The implementation is complete only when:

* a task card can declare source_package or iso_snapshot explicitly;
* iso_snapshot requires all identity fields and rejects placeholders;
* the E2B verifier runs before source setup and benchmarks;
* baseline artifacts contain the specification digest and verification result;
* a candidate cannot be reviewed without a verified baseline;
* existing source-package tests remain green;
* no host shell, Docker fallback, or mutable latest APT state is used for
  production execution;
* the final documentation clearly distinguishes ISO source, E2B execution
  snapshot, package artifacts, and benchmark measurements.

Do not invent an ISO hash, package version, manifest, or E2B snapshot ID. If
those inputs are unavailable, leave the production iso_snapshot run blocked
and report the exact missing artifact.
