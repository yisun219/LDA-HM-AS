"""Compatibility entry point; the authoritative CLI lives in lda.cli.main."""

from lda.cli.main import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
