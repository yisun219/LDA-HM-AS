# libaio validation

The Mission runs upstream `make partcheck`, a header consumer, Python FFI consumer, package
metadata and ABI checks, and an unmodified fio `ioengine=libaio` workload against explicit
baseline and candidate roots.

