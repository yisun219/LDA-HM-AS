# Linux Development Agent（LDA）

Linux Development Agent 是一套面向 Linux 发行版 package 的自动研究、构建、验证和性能优化系统。当前 Campaign 面向 Ubuntu 26.04 的性能关键 library/package，目标是在不改变用户使用方式的前提下，产出可通过 `.deb` 原位替换官方包的优化版本。

LDA 不是单个“写代码 Agent”。它由动态 Portfolio 管理器、固定的 package Mission、独立确定性 Judge、E2B 隔离执行、可恢复 World State 和可审计 Artifact/Event Store 组成。Agent 可以提出研究方向和生成 Candidate，但无权修改兼容性 Fence、接受自己的 Candidate、篡改 Benchmark、发布 package 或决定 Run 收敛。

完整组件、状态和信任边界见 [架构文档](docs/architecture.md)。

## 目标

- 优化 Ubuntu package，并产出可安装、可回滚的 `.deb` Candidate。
- 保持 package 名、架构、安装路径、SONAME、symbol、symbol version、动态依赖、header、pkg-config、ABI、API 和 FFI 兼容。
- 在目标 CPU 能力范围内，以固定输入、原始样本和置信区间测量性能。
- 使用真实 End-to-End/Portfolio workload 作为系统级 Reward，不把多个 Micro speedup 相加。
- 所有关键决定都能从结构化 World State、hash-chained Event 和 Artifact 引用中恢复与审计。
- E2B、source、build、Judge、Benchmark、hardware 或 rollback 证据缺失时 fail closed。

## 非目标

- 通过新 API、修改 header 用法或要求应用重新适配来获得性能。
- 允许 LLM 覆盖 Fence 或 Judge 失败。
- 在 Controller 主机上裸机 build/test，或在 E2B 不可用时切换到 Docker/本地执行。
- 把调研排名直接当成已验证的 package 数据库。
- 把局部 Micro win 当成可发布的系统级优化。
- 在真实 Top 10 Campaign 尚未完成前宣称已经获得可发布加速。

## 总体 Flow

```text
Argus 外层 Life Loop
  Observe -> Summarize -> Manager Decision -> Policy Validate
  -> Execute -> Outcome Learning -> Capability Check -> Convergence
                              |
                              v
固定 LDA Package Mission
  Official Baseline -> Manifest -> Profile -> Hypothesis -> Plan
  -> Candidate Build -> Local Verify -> Independent Review -> Trace Audit
                              |
                              v
独立确定性 Clean Judge
  Package/ABI/API/FFI -> Anti-cheat -> Benchmark Evidence
  -> Install -> Replacement -> Rollback
```

外层 Argus 每个 Life Cycle 都从持久化 World State 重新观察全局，可以创建、重排、暂停、恢复或终止 Mission，也可以提出 Research Snapshot、Capability Mission 和 Portfolio E2E。每个具体 package 仍必须进入固定 LDA Mission，不能从 Manager 建议直接跳到接受 Candidate。

最终收敛只由确定性 `ConvergenceEvaluator` 根据预算、周期、进展、Mission 状态和 Portfolio 指标决定。Manager 的 `PROPOSE_STOP` 只是建议。

## 快速开始

Python 和当前经过测试的 E2B SDK 版本分别记录在 `pyproject.toml` 和 `requirements.txt`。生产凭据应由运行环境或被 Git 忽略的 operator-only 配置提供；不得提交到 Git，也不得进入 Prompt、Template、Snapshot、Artifact 或 Event Log。

```bash
export E2B_API_URL="https://e2b.fact-lab.work"
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_ACCESS_TOKEN="dummy"
export E2B_API_KEY="<由运行环境注入>"

./lda e2b preflight
./lda template build --all
./lda research ingest research/
./lda run --flow argus-humanize \
  --run-id ubuntu-2604-campaign \
  --campaign-input "/absolute/path/to/research-input.md"
```

一条 `lda run` 负责执行 Preflight、Campaign 输入复制与 hash、Controller Sandbox 创建、E2B 上传验证、Qualification、Canary 授权、Argus Life Loop、固定 Mission、Judge、Outcome 分类和确定性收敛。任一强制 Gate 不可用时命令以非零状态退出，不会回退到裸机。

测试使用显式 fake data plane；它只能验证控制逻辑，不能替代真实 E2B、硬件、package build 或性能证据：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
```

## CLI

```text
lda e2b preflight
lda e2b reap --run-id RUN_ID
lda template build --all
lda research ingest PATH...
lda run --flow argus-humanize --run-id RUN_ID --campaign-input PATH
lda argus world --run-id RUN_ID
lda argus missions --run-id RUN_ID
lda argus capabilities --run-id RUN_ID
lda status --run-id RUN_ID
lda logs --run-id RUN_ID
lda resume --run-id RUN_ID
lda cancel --run-id RUN_ID
lda report --run-id RUN_ID
```

生产 Campaign 通常为每个 Run 使用独立目录。测试和诊断可以通过隐藏的 `--root` 选项指定状态根目录。

## Campaign Qualification

调研报告是候选筛选证据，不是权威 package 数据库。LDA 会：

1. 完整复制原始输入到 `.lda/artifacts/campaign-input/`。
2. 记录字节数、行数和 SHA-256。
3. 将同一份字节上传到 Controller 和 Qualification Sandbox。
4. 在 E2B 内重新计算 hash，确保 Builder、Reviewer、恢复和审计读取同一输入。
5. 在固定 Ubuntu 26.04 Packages/Sources Snapshot 中重新验证 package 事实。

当前首批候选为：

```text
libgtk-4-1
libgtk-3-0t64
gnome-shell
libreoffice-core
sssd-common
libcairo2
gnome-settings-daemon
gstreamer1.0-plugins-good
ibus
libsoup-3.0-0
```

Qualification 验证 binary metadata、source mapping、dependency metadata、固定 Sources Snapshot、源码解包和干净重建。`libcairo2` 与 `libsoup-3.0-0` 是第一批 Canary；其余八个 package 只有在两个 Canary 都获得确定性 Judge 成功和有效系统级测量后，才进入 Mission Graph。

## 固定 LDA Mission

每个 Candidate 都绑定不可变 Mission Contract，并按固定顺序执行：

```text
OFFICIAL_BASELINE
-> ABI/API/FFI_MANIFEST
-> MICROBENCH_GENERATION
-> E2E_MAPPING
-> PROFILE
-> HYPOTHESIS
-> PLAN
-> FORK_CANDIDATES
-> BUILD
-> LOCAL_VERIFY
-> ADVERSARIAL_REVIEW
-> TRACE_AUDIT
-> CLEAN_JUDGE
-> OUTCOME
```

Builder 可以选择 Policy 允许的安全优化参数。当前允许集合包括 `-O2`、`-O3`、`-fno-plt`、function/data sections 和 `-flto=auto`；`-march=native`、`-Ofast` 和 fast-math 被直接拒绝。所有 Candidate 从同一固定 source/version 产生，构建在 disposable `lda-base` E2B Workspace 中完成。

## Judge 与硬 Fence

Judge 不是 Agent，不包含 LLM。Canary Judge 在独立、无 Secret、无网络 Sandbox 中接收官方与 Candidate 的 runtime/dev `.deb`，并确定性检查：

- package、version、architecture、安装路径和 control declarations；
- SONAME、动态导出 symbol、symbol version 和 `NEEDED`；
- header 和 pkg-config metadata；
- Candidate 安装与官方 package rollback；
- 预编译 C `dlopen`/`dlsym` probe 和 Python `ctypes`；
- package、probe 和 Judge script 的 SHA-256；
- Secret 泄漏、`LD_PRELOAD`、control 文件修改和未追踪 binary。

任何必要检查缺失或失败都会 Reject。通用非 Canary package 已具备真实 Debian source build 路径，但在 package-specific immutable Judge adapter 完成前仍然不能被接受。

## Benchmark 与 Reward

Micro Benchmark 使用固定 warmup、30 个原始样本、确定性输入和置信区间。Candidate 必须同时满足配置中的 Micro speedup 与 CI 下界，并通过硬件和反作弊检查。

End-to-End 是 Mission guardrail，Portfolio E2E 是外层主要系统 Reward。LDA 不会把多个 library speedup 相加。`LOCAL_WIN` 不等于 Release；Top 10 放行需要两个 Canary 都记录 `SUCCESS_SYSTEM`、有效且 accepted 的 Benchmark、配置要求的 Portfolio geomean，以及足够数量的改进 workload。

## World State、恢复与 Artifact

```text
RUN_ROOT/
  .lda/
    world.json
    events.jsonl
    artifacts/
      campaign-input/
        manifest.json
        <原始调研输入>
      qualification.json
      <content-addressed artifacts>
```

`world.json` 是原子写入的结构化恢复快照。`events.jsonl` 只追加并带 hash chain，Event payload 在落盘前经过 Secret Redactor。Mission、Candidate、Benchmark、Outcome、Capability、预算、Agent session 和 convergence signal 都保存在 World State 中；Controller 重启后不依赖模型记忆恢复。

Builder 与 Capability Builder thread 可以按 Candidate/Capability 恢复。Manager、Summarizer、Planner、Reviewer 和 Outcome Classifier 按定义的 independence group 使用新 thread，Reviewer 不继承 Builder history。

## Capability 生命周期

Capability 可以是 Profiler Adapter、Build Adapter、Benchmark Generator、Dependency Test、FFI Checker、E2E Workload 或 CPU dispatch helper。每个 Capability 都有 version、content hash 和 scope。

```text
PROPOSED -> POLICY_APPROVED -> BUILDING -> ISOLATED_TEST
-> ADVERSARIAL_REVIEW -> CAPABILITY_JUDGE -> ACTIVE
```

状态不能跳过。只有 isolated test 明确通过后才能进入 Review，只有 Capability Judge 明确通过后才能进入 `ACTIVE`。`ACTIVE` 与 `REJECTED` 都是终态。

## E2B 隔离与 Secret

目标拓扑为 Controller Sandbox 管理独立的 Agent Runtime、Candidate Work、Capability Work、Judge 和 E2E Sandbox。每个 Sandbox 都带 project、run、cycle、mission、candidate、role 和唯一 lease metadata。

- Bootstrap/Controller 只持有 E2B 控制面凭据。
- Agent Runtime 的 Codex 进程只获得模型凭据。
- Candidate/Qualification/E2E/Judge 不获得模型或 E2B Secret。
- Judge 默认无网络。
- E2B 不可用时 fail closed，不切换 Docker 或裸机。

共享网关适配器保留 SDK Header，并在 API URL 与 Sandbox URL 相同时幂等增加共享网关认证 Header。Preflight 覆盖 create/connect、command、filesystem、background PID、reconnect、snapshot/fork fallback、metadata、network、hardware、orphan reaping、template 和 kill。

## 当前真实状态

截至 2026-08-26，仓库已经实现并由本地测试覆盖：

- 结构化 Argus Action 和确定性 Policy；
- 固定 Mission Contract 与 Candidate attempt；
- E2B shared gateway、lease、reconnect、reap 和真实 Preflight 检查；
- AgentFactory independence policy 与 Builder session 恢复；
- Campaign hash、固定 source bundle、Qualification checkpoint 和 Canary release gate；
- Canary Micro/E2E evidence parser 与独立 runtime/dev package Judge；
- Top 8 固定 snapshot、精确 source/version、`dpkg-source`、build-dep、`dpkg-buildpackage` 的真实构建路径；
- sandbox-side long-command checkpoint，避免长 build 被单次 streaming RPC deadline 中止；
- World State、Event Store、恢复、Convergence 和 Capability activation gate。

仍未完成或仍需真实验证：

- E2B 网关当前返回 Cloudflare `530/1033`，正式 watcher 正在持续等待恢复。
- 最新正式 Campaign 在 Canary Qualification 的 build-dependency streaming deadline 处停止，尚未进入 Mission；新的 checkpoint 机制需要在网关恢复后实测。
- CLI 已创建 Controller Sandbox 并上传输入，但 Supervisor Python loop 仍由启动进程驱动，尚未完全迁入 Controller Sandbox。
- `lda-e2e` Template 尚未包含可执行的真实 `run-portfolio-e2e` harness。
- 通用 package 仍需要 package-specific Judge、reverse dependency suite 和 application E2E adapter。
- E2B 暴露的虚拟 CPUID 可证明 ISA/架构兼容，不能单独证明物理 Host 身份。
- 当前不能宣称 Top 10 已跑完，也不能宣称已经获得新的可发布 Ubuntu 26.04 加速结果。

## 参考与致谢

LDA 的固定 Mission 结构参考了 Humanize 类迭代工程 Flow 的部分思想，并在此基础上加入 Linux package compatibility Fence、E2B 隔离、动态 Portfolio 管理、独立 Judge、Benchmark Reward 和持久化恢复。当前兼容的 CLI Flow 标识为 `argus-humanize`。

