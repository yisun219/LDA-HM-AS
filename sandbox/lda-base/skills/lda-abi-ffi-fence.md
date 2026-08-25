# LDA ABI/FFI Fence

The optimized package must replace the Ubuntu package without recompiling
existing binaries or changing source-level callers.

Before claiming compatibility, run and preserve evidence for:

- SONAME and exported symbol equality;
- `abidiff` type and layout comparison;
- FFI smoke tests for every supported binding;
- command-line, exit-code, configuration, and result equivalence;
- security defaults and upgrade/install behavior.

Any unexplained mismatch is a blocking failure, regardless of benchmark speedup.
