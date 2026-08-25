# Security

LDA is E2B-only. `lda-flow` refuses to run without `E2B_API_URL`, `E2B_SANDBOX_URL`,
`E2B_API_KEY`, and `E2B_ACCESS_TOKEN`; it has no Docker or host fallback. E2B credentials are
never put in YAML, template layers, artifacts, traces, or reports.

Only four model environment names can be forwarded: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`DEEPSEEK_API_KEY`, and `DEEPSEEK_BASE_URL`. Values are redacted before controller artifacts
are written. Hard Fences are literal `True` fields in Pydantic models and cannot be disabled.

Builders are constrained by protected-path hashes and a source allowlist. Trace auditing reads
only tool/process command events, so prose containing a forbidden flag is not treated as an
execution. A real command containing that flag is a P0 finding.

