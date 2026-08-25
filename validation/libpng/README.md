# libpng validation

The Mission runs the upstream `pngtest` and `pngvalid` commands, a header consumer,
Python `ctypes` consumer, ImageMagick PNG decode/encode/resize, package metadata checks,
`readelf`/`objdump`/`abidiff`, `abi-dumper`, and `abi-compliance-checker` against explicit
baseline and candidate roots.

