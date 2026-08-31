---
name: lda-end-to-end-benchmark
description: How LDA end-to-end benchmarks work: real consumer workloads (browser render, GUI, web server) kept separate from micro results; a zero e2e gain is valid, a regression is not.
---

# LDA End-to-End Benchmark

Use real workloads such as browser rendering, GUI automation, and web-server
throughput to measure system-level effect. Keep end-to-end results separate from
micro results. A zero end-to-end gain is a valid result; it cannot excuse a
micro regression or compatibility failure.
