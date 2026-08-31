---
name: lda-micro-benchmark
description: How LDA micro benchmarks are run and judged: paired baseline/candidate in one sandbox, alternating order, in-sandbox nonce-tagged timing, hidden holdout; micro speedup is local reward only.
---

# LDA Micro Benchmark

Benchmark each optimized function/library with representative, boundary, and
adversarial inputs. Run baseline and candidate in the same sandbox, alternate
their order, preserve every observation, and report the median plus raw values.
Micro speedup is local reward only; it never overrides an ABI/FFI or behavior
failure.
