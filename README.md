# Linux Development Agent（LDA）

Linux Development Agent 是一套面向 Linux 发行版 package 的自动研究、构建、验证和性能优化系统。它可用于 Ubuntu 26.04 等发行版的性能关键 library/package，在不改变用户使用方式的前提下，产出可通过 `.deb` 原位替换官方包的优化版本。

LDA 不是单个“写代码 Agent”。它由动态 Portfolio 管理器、固定的 package Mission、独立确定性 Judge、E2B 隔离执行、可恢复 World State 和可审计 Artifact/Event Store 组成。Agent 可以提出研究方向和生成 Candidate，但无权修改兼容性 Fence、接受自己的 Candidate、篡改 Benchmark、发布 package 或决定 Run 收敛。

## 核心边界：手术刀式替换

ABI、API 和 FFI 兼容是 LDA 最核心、最硬的边界条件。优化 `libpng`、`libaio` 或其他系统库时，Candidate 必须能够直接替换 Ubuntu 官方 package：用户只需通过 apt 或安装 `.deb` 使用新版本，不需要更换发行版，也不需要修改原 binary、应用程序、开发代码、header 用法、动态链接方式或 FFI 调用。

替换兼容性至少覆盖：

- binary/source package identity、version、architecture、安装路径和依赖 metadata；
- SONAME、exported symbol、symbol version、calling convention 和数据布局；
- header、pkg-config、CMake config 和 unchanged source compilation；
- unchanged prebuilt binary、`dlopen`/`dlsym`、Python `ctypes`/`cffi` 和 Rust FFI；
- runtime/development `.deb` 配套安装、原位升级和官方 package rollback。

任何 Fence 失败都直接 Reject。Manager、Builder、Reviewer、Capability 和 Release 逻辑都无权豁免，也不能通过降低精度、关闭功能或要求调用方适配来换取性能。

进一步文档：

- [系统架构](docs/architecture.md)：两层 Flow、World State、Agent、Judge、E2B 与收敛。
- [仓库导览](docs/repository.md)：目录职责、权威入口和兼容层。
- [运行手册](docs/operations.md)：正式 Campaign、恢复、日志、Watcher 与故障处理。
- [Ubuntu 26.04 Campaign](docs/ubuntu-2604-campaign.md)：候选输入、Qualification 和 Canary 放行协议。

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
- 在完成全部确定性 Gate 前宣称 Candidate 已经获得可发布加速。

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

## Package 选择与优先级

LDA 不从发行版的全部 package 同时开始。Research Curator 先根据使用频率、实测 CPU share、dependency graph centrality、workload 通用性、预期投入产出和兼容风险筛选 5 至 10 个候选：

```text
priority
= 0.25 * usage_frequency
+ 0.25 * measured_cpu_share
+ 0.20 * dependency_centrality
+ 0.15 * workload_generality
+ 0.15 * expected_effort_efficiency
- compatibility_risk
```

Qualification 再验证候选的真实 package/source 映射、可重建性、热点、Benchmark 稳定性和可替换性。Argus 根据 Outcome 更新 expected value、failure probability、measured criticality、capability readiness、system contribution 和 remaining cost，但动态新增 Mission 仍必须经过 Policy 和全局预算。目标是优先发现可复用的 generic system-level speedup，而不是为单一 workload 长期死磕低价值 package。

## 快速开始

Python 和 E2B SDK 版本分别锁定在 `pyproject.toml` 和 `requirements.txt`。生产凭据应由运行环境或被 Git 忽略的 operator-only 配置提供；不得提交到 Git，也不得进入 Prompt、Template、Snapshot、Artifact 或 Event Log。

```bash
export E2B_API_URL="https://e2b.fact-lab.work"
export E2B_SANDBOX_URL="$E2B_API_URL"
export E2B_ACCESS_TOKEN="dummy"
export E2B_API_KEY="<由运行环境注入>"

./lda e2b preflight
./lda template build --all
./lda research ingest research/
./lda run --flow argus-lda \
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
lda run --flow argus-lda --run-id RUN_ID --campaign-input PATH
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

Qualification 验证 binary metadata、source mapping、dependency metadata、固定 Sources Snapshot、源码解包和干净重建。Policy 从通过 Qualification 的候选中选择小规模 Canary；其余候选只有在 Canary 获得确定性 Judge 成功和有效系统级测量后，才进入 Mission Graph。具体候选和 Canary 属于版本化 Campaign Contract，不硬编码为 LDA 的通用设计。

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

Builder 可以选择 Policy 允许的安全优化参数。默认允许集合包括 `-O2`、`-O3`、`-fno-plt`、function/data sections 和 `-flto=auto`；`-march=native`、`-Ofast` 和 fast-math 被直接拒绝。所有 Candidate 从同一固定 source/version 产生，构建在 disposable `lda-base` E2B Workspace 中完成。

## Judge 与硬 Fence

Judge 不是 Agent，不包含 LLM。Canary Judge 在独立、无 Secret、无网络 Sandbox 中接收官方与 Candidate 的 runtime/dev `.deb`，并确定性检查：

- package、version、architecture、安装路径和 control declarations；
- SONAME、动态导出 symbol、symbol version 和 `NEEDED`；
- header 和 pkg-config metadata；
- Candidate 安装与官方 package rollback；
- 预编译 C `dlopen`/`dlsym` probe 和 Python `ctypes`；
- package、probe 和 Judge script 的 SHA-256；
- Secret 泄漏、`LD_PRELOAD`、control 文件修改和未追踪 binary。

任何必要检查缺失或失败都会 Reject。非 Canary package 同样必须具备真实 Debian source build 路径和 package-specific immutable Judge adapter，不能以通用成功标记替代 package 级证据。

Judge 分级执行：

```text
Level 0  upstream self test
Level 1  ABI/API/FFI Fence
Level 2  unchanged prebuilt binaries
Level 3  direct reverse dependencies
Level 4  high-centrality applications
Level 5  Chrome / Web server / GUI E2E
Level 6  Portfolio E2E
```

Self test 验证源码本身的功能契约，dependency test 验证未修改的下游 package 和应用仍能工作。Builder 只收到脱敏失败摘要，不能读取 hidden test 或 Judge 实现。

Builder 与 Reviewer 是两个不同 independence group：Builder 负责提出和实现优化，Reviewer 使用全新 thread 对功能变化、ABI/FFI 风险、测量方法和作弊痕迹做 adversarial review。随后 Trace Auditor 检查工具事件，最终仍由不含 LLM 的 Clean Judge 独立裁决，不能由 Agent 互相认可代替。

Anti-cheat 会拒绝 test/benchmark 修改、workload 缩小、hardcode 输出、已知输入 memoization、精度下降、feature disable、baseline 污染、affinity/governor 操纵、未声明 `LD_PRELOAD`、未追踪预编译 binary、网络下载作弊、忽略失败样本、cherry-pick 最好一次，以及 Judge 与 Baseline 环境不一致。Trace 只记录工具事件和可审计事实，不保存模型隐藏思维过程。

## Benchmark 与 Reward

Benchmark 分为 Micro 与 End-to-End 两层。Micro Benchmark 面向具体 library/function，生成多 input、多尺寸和固定 seed 的 workload，使用固定 warmup、30 个原始样本和置信区间；它是 Builder 的局部 Reward，用于排序 Candidate。Candidate 必须同时满足配置中的 Micro speedup 与 CI 下界，并通过硬件和反作弊检查。

End-to-End Benchmark 使用 Chrome 页面渲染、GUI、Web server 和其他真实应用路径，验证一个或多个 library 的局部优化是否真正折射成系统 speedup。它是 Mission guardrail；Portfolio E2E 是 Argus 外层的主要长期 Reward。LDA 不会把多个 Micro speedup 相加，`LOCAL_WIN` 也不等于 Release。系统放行必须同时满足无功能/ABI 回归、有效 Portfolio geomean、足够数量的改进 workload、关键依赖覆盖和实际成本约束。

每次有效测量都记录 CPU model、CPUID、microcode、kernel、governor、turbo、NUMA、SMT、affinity 和邻居负载。目标硬件配置是 Intel Xeon Gold 6548Y+；涉及 architecture-specific 优化时必须绑定该 Hardware Profile，并保留通用 fallback。公共 drop-in package 禁止全局 `-march=native`，允许经过 Fence 的 runtime dispatch、IFUNC、function multiversioning、AVX2/AVX-512 path 和 generic path。

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

执行端全部 E2B 化。Controller Sandbox 管理独立的 Agent Runtime、Candidate Work、Capability Work、Judge 和 E2E Sandbox；build、profile、self test、dependency test、Benchmark、环境恢复、fork/snapshot 和 Agent session 都通过 Sandbox API 完成，不依赖裸机 runner。每个 Sandbox 都带 project、run、cycle、mission、candidate、role 和唯一 lease metadata。

`lda-base` Template 标准化 Ubuntu 26.04 编译、Debian packaging、perf/trace、ABI/FFI 和 Benchmark 环境，并预装固定 commit 的 [Intel Performance Skills](https://github.com/intel/intel-performance-skills)。公共依赖、source cache 和工具链可以预装后制作版本化 Snapshot，使并发 Candidate 从同一干净 Baseline 快速 fork。Agent Runtime 通过 Scoped Tool Gateway 操作 Workspace，不能直接取得裸机 shell。

- Bootstrap/Controller 只持有 E2B 控制面凭据。
- Agent Runtime 的 Codex 进程只获得模型凭据。
- Candidate/Qualification/E2E/Judge 不获得模型或 E2B Secret。
- Judge 默认无网络。
- E2B 不可用时 fail closed，不切换 Docker 或裸机。

生产拓扑通过 `max_live_sandboxes`、`max_live_codex_sessions`、heartbeat、timeout、budget cancellation 和 orphan reaper 控制规模。唯一 `lease_id` 防止网络重试重复创建 Sandbox；Controller 重启后根据 Event Store 和 Sandbox metadata 重连或清理。

共享网关适配器保留 SDK Header，并在 API URL 与 Sandbox URL 相同时幂等增加共享网关认证 Header。Preflight 覆盖 create/connect、command、filesystem、background PID、reconnect、snapshot/fork fallback、metadata、network restriction、hardware fingerprint、orphan reaping、Template exists/build 和 kill。任一项失败都阻止正式 Run。

## 参考与致谢

LDA 的固定 Mission 结构参考了 Humanize / Humanize2 一类迭代工程 Flow 的部分思想，并围绕 Linux package 工程加入 compatibility Fence、E2B 隔离、动态 Portfolio 管理、独立 Judge、Benchmark Reward 和持久化恢复。旧版 CLI Flow 标识 `argus-humanize` 作为兼容 alias 保留。
