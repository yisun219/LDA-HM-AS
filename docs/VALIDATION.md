# Validation

The local contract is:

```bash
python3.12 -m pip install -e '.[dev]'
pytest
ruff check src tests flows templates validation
python3.12 -m compileall -q src flows templates validation
lda-flow campaign campaigns/ubuntu2604-core-libs.yaml --dry-run
```

Remote verification requires the pinned E2B SDK and credentials. The controller fails closed
when credentials or the Ubuntu 26.04 `lda-base` template are unavailable; it never substitutes
Docker or the host machine.

