# Ubuntu 26.04 Baseline Contract

LDA-HM has two baseline modes:

* source_package: transitional build-only mode. It verifies the Ubuntu
  release, codename, and architecture, then prepares a package source tree.
* iso_snapshot: production distribution mode. The E2B template must be an
  immutable snapshot derived from the exact Ubuntu 26.04 Desktop amd64 ISO.

The ISO is the authoritative input artifact. The E2B snapshot is the execution
form. A production card must record the ISO SHA256, build ID, manifest SHA256,
APT snapshot, rootfs digest, and installed package inventory digest. The
verification script rejects a sandbox before source setup or benchmarking when
those identities do not match.

The package-level run still follows the A/B/A' model:

~~~text
A  = pristine ISO-derived E2B snapshot
B  = A with exactly the candidate package installed
A' = fresh restored copy of A
~~~

Micro benchmarks may use a package-focused workspace, but end-to-end tests
must run against the complete Desktop snapshot. Runtime apt-get update or
unversioned package fetching must not be used in iso_snapshot mode.

The checked-in examples/libpng-card.json remains in source_package mode until
the real ISO, manifest, APT snapshot, and E2B stock template are available. It
must not be presented as a complete Desktop baseline.
