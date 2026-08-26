# 仓库导览

## 权威入口

- CLI：`src/lda/cli/main.py`
- Argus Supervisor：`src/lda/controller/supervisor.py`
- 固定 package Mission：`src/lda/humanize/mission.py`
- E2B Client/Preflight：`src/lda/e2b/`
- AgentFactory 与 JSON Schema：`src/lda/agents/`
- Canary Benchmark/Judge：`src/lda/benchmarks/canary.py`、`src/lda/judge/canary.py`
- World State/Event Store：`src/lda/models.py`、`src/lda/state/store.py`

`src/lda/main.py` 和 `src/lda/supervisor.py` 只保留兼容 import，不包含第二份实现。根目录 `lda` 是开发环境直接运行入口，安装 package 后则使用 `pyproject.toml` 注册的 `lda` console script。

## 目录职责

```text
src/lda/
  cli/                 命令解析和 Bootstrap
  controller/          Argus Life Loop 与执行编排
  argus/               Policy、Outcome、Capability、Convergence
  humanize/            固定 LDA package Mission 实现
  agents/              AgentSpec、AgentFactory、Role output schema
  codex/               Codex CLI session 适配
  e2b/                 shared gateway、Sandbox client、Preflight
  packages/            Debian source/package build adapter
  research/            Campaign ingest、Qualification、Release gate
  missions/            Mission Contract 与 Scheduler
  fences/              ABI/API/FFI compatibility model
  benchmarks/          Micro、Canary 和 Portfolio 计算
  judge/               无 LLM 的确定性 Judge
  state/               World State snapshot 与 Event Store
  artifacts/           content-addressed Artifact Store
  security/            Secret scope 与 redaction

e2b_templates/         五类 E2B Template 输入
schemas/               对外 JSON Schema
scripts/               运维辅助脚本
tests/unit/            确定性控制逻辑测试
tests/e2b/             需要真实 E2B Key 的 smoke test
docs/                  架构、仓库导览和运行手册
```

## Legacy Fixture

根目录 `humanize.py` 与 `tests/test_humanize.py` 是用于验证固定队列、Gate 和 Reviewer independence 思想的独立 legacy fixture，不是生产 LDA CLI、Controller 或 package runner。生产入口不会 import 或执行该文件。

## 配置与 Secret

- 可提交：无 Secret 的默认值、Template manifest、Schema、Prompt 和测试 fixture。
- 不提交：`configs/lda.yaml`、`.env*`、private key、Campaign input、Run state 和真实 Artifact。
- Operator 配置由环境变量、`~/.config/lda/e2b.env`、`~/.config/lda/codex.env` 或被 Git 忽略的私有 YAML 提供。

任何新增模块都应保持单一权威实现，避免在根目录或兼容 wrapper 中复制业务逻辑。
