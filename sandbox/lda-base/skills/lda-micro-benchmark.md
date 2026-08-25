# LDA Micro Benchmark

Benchmark each optimized function/library with representative, boundary, and
adversarial inputs. Run baseline and candidate in the same sandbox, alternate
their order, preserve every observation, and report the median plus raw values.
Micro speedup is local reward only; it never overrides an ABI/FFI or behavior
failure.
