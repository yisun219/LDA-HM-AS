# LDA E2B Templates

五个 Template 明确对应不同信任边界：

| Template | 内容 | 不应包含 |
| --- | --- | --- |
| `lda-controller` | Argus Supervisor、Policy、State、Artifact、E2B Client | package source、模型验收逻辑 |
| `lda-agent-runtime` | Codex CLI、JSON Schema、Role Prompt | package source、Judge Secret |
| `lda-base` | Ubuntu 26.04 toolchain、packaging、profile/ABI 工具 | Codex/E2B Secret |
| `lda-judge` | immutable Fence、FFI probe、install/rollback、anti-cheat | LLM、网络、任何 Secret |
| `lda-e2e` | 浏览器、Web/GUI/system workload | 模型与控制面 Secret |

`lda template build --all` 生成并检查 manifest。正式注册到 E2B 前还必须执行真实 Template build 与 smoke test；仅有本地 manifest 不代表远端 Alias 可用。
