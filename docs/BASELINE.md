# Ubuntu 26.04 Baseline Contract

LDA-HM has two baseline modes:

* source_package: transitional build-only mode. It verifies the Ubuntu
  release, codename, and architecture, then prepares a package source tree.
* iso_snapshot: production distribution mode. The E2B template must be an
  immutable snapshot derived from the exact Ubuntu 26.04 Desktop amd64 ISO.

The ISO is the authoritative distribution artifact. The E2B snapshot is the
standardized execution form. These identities are related but not conflated:
the ISO Debian and Snap manifests describe the shipped Desktop distribution,
while the live E2B package and Snap inventory digests describe the exact tools
available to a development run. A production card records both sides plus the
ISO SHA256, build ID, APT snapshot, rootfs digest, and immutable E2B template
ID. The verification script rejects a sandbox before source setup or
benchmarking when any recorded identity does not match.

The package-level run still follows the A/B/A' model:

~~~text
A  = pristine ISO-derived E2B snapshot
B  = A with exactly the candidate package installed
A' = fresh restored copy of A
~~~

Micro benchmarks may use a package-focused workspace. End-to-end tests must
exercise a real consumer path in the standardized GUI/browser-capable E2B
snapshot and remain anchored to the Desktop ISO manifests. Runtime unversioned
package fetching is forbidden. Exact source retrieval from the recorded Ubuntu
Snapshot is permitted and must include the Debian source version.

The checked-in libpng card is pinned to Ubuntu 26.04 Desktop build
`20260423.1`, source `libpng1.6=1.6.57-1`, and the immutable production E2B
template ID. The E2B template is not claimed to have booted the ISO; it proves
the execution inventory separately while carrying the verified ISO identity.
