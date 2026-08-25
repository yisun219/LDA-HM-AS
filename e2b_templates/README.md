# LDA E2B Templates

The five manifests are intentionally explicit about trust boundaries. `lda-controller`
contains orchestration only, `lda-agent-runtime` contains Codex runtime but no package
source, `lda-base` contains the pinned Ubuntu build toolchain, `lda-judge` contains no
LLM, and `lda-e2e` contains system workloads. Template manifests are produced by
`lda template build --all`.
