# Ubuntu 26.04 Baseline

The Campaign baseline is the exact Ubuntu 26.04 Desktop amd64 ISO state. A floating
`apt-get download package` result is not an acceptable baseline because it can silently
move to another archive version.

Before a real Campaign, place the ISO manifest and a generated lock file at the paths in
`campaigns/ubuntu2604-core-libs.yaml`:

```text
.lda/ubuntu2604-desktop-amd64.manifest
.lda/ubuntu2604-baseline.lock.yaml
```

The lock is derived from the manifest and has this shape:

```yaml
schema_version: 1
origin: ubuntu-26.04-desktop-amd64-iso
release: "26.04"
architecture: amd64
manifest_sha256: <sha256 of the manifest>
packages:
  libpng16-16t64:
    package: libpng16-16t64
    version: <exact ISO version>
    architecture: amd64
    sha256: <sha256 of the official deb>
    source_package: libpng1.6
    source_version: <exact source version>
    source_sha256: <optional source archive sha256>
```

The controller verifies the manifest digest, package identity, architecture, exact Debian
version, binary SHA256, source package, and source version before accepting a Mission. The
remote baseline download is version-pinned from the lock, and the independent baseline Fence
re-checks the downloaded artifact. If the manifest or lock is absent or inconsistent, a real
Campaign stops before creating optimization work.
