# 运行手册

## 正式 Campaign 前检查

```bash
git status --short
git branch --show-current
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
./lda e2b preflight
./lda template build --all
```

Preflight 任一项失败都不得继续。`--fake-e2b` 只用于测试控制逻辑，不能作为生产 fallback。

## 启动正式 Run

```bash
export E2B_API_URL="https://e2b.fact-lab.work"
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_ACCESS_TOKEN="dummy"
export E2B_API_KEY="<injected>"
export LDA_SOURCE_SNAPSHOT_ROOT="/absolute/path/to/source-snapshot"

./lda --root "runs/$RUN_ID" run \
  --flow argus-lda \
  --run-id "$RUN_ID" \
  --campaign-input "/absolute/path/to/campaign.md"
```

运行首先复制 Campaign 输入并核对 SHA-256，然后执行 Top 10 Qualification。Canary Gate 未满足时会停止在 `.lda/artifacts/qualification.json`，不会开始源码优化。

## 查看状态

```bash
./lda --root "runs/$RUN_ID" status --run-id "$RUN_ID"
./lda --root "runs/$RUN_ID" argus missions --run-id "$RUN_ID"
./lda --root "runs/$RUN_ID" argus capabilities --run-id "$RUN_ID"
./lda --root "runs/$RUN_ID" logs --run-id "$RUN_ID"
./lda --root "runs/$RUN_ID" report --run-id "$RUN_ID"
```

主要文件：

- `.lda/world.json`：原子恢复快照。
- `.lda/events.jsonl`：hash-chained Event。
- `.lda/artifacts/campaign-input/`：原始 Campaign 和 Manifest。
- `.lda/artifacts/qualification.json`：Qualification checkpoint/blocker。

## 恢复、取消和清理

```bash
./lda --root "runs/$RUN_ID" resume --run-id "$RUN_ID"
./lda --root "runs/$RUN_ID" cancel --run-id "$RUN_ID"
./lda e2b reap --run-id "$RUN_ID"
```

恢复依赖 World State、Event、Artifact 和持久 Agent session ID，不依赖模型记忆。取消只改变 Run 状态；`e2b reap` 负责清理带相同 `run_id` metadata 的孤儿 Sandbox。

## Gateway Watcher

当 E2B 控制面暂时不可用时，可以使用：

```bash
./scripts/watch_campaign.sh RUN_ID /absolute/path/to/campaign.md runs/RUN_ID
```

脚本每 30 秒检查 `/health`，只有 HTTP 200 才启动正式 Run。它不会改用 Docker、本地 build 或 fake E2B。日志写入 `runs/RUN_ID/watch.log`。

## 常见失败

### HTTP 530 / Cloudflare 1033

表示 E2B origin/control plane 不可达。保持 fail closed，确认 Watcher 存活，等待服务恢复；这不是 package build 失败。

### `context deadline exceeded`

长时间 build 应走 sandbox-side checkpoint。检查 `/tmp/lda-jobs/<job_id>/` 的 stdout、stderr 和 exit_code；不要仅依据单次 RPC timeout 判定 package 失败。

### Qualification blocker

读取 `qualification.json` 中对应 package 的 `checks`、evidence refs 和 release blockers。不得手工把 boolean 改为 true；必须重新产生可审计证据。

### Judge Reject

以 Judge evidence 中第一个失败硬 Gate 为准。Manager、Builder 和 Reviewer 都无权覆盖。
