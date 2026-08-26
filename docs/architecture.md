# Linux Development Agent 架构

本文定义 LDA 的控制模型、执行边界、持久化状态、信任边界和确定性验收规则。

## 不可变设计原则

1. ABI、API、FFI、package identity 和安装兼容性是不可变硬 Fence。
2. Agent 负责建议、研究和生成 Candidate；Policy、Judge、Benchmark 解释、Release 和 Convergence 由确定性代码负责。
3. 生产 package build、test、profile 和 Judge 只能在 E2B Sandbox 中执行；E2B 不可用时 fail closed。
4. Agent 不能验收自己的输出。Reviewer 与 Builder history 独立，Judge 不使用模型。
5. Research input 是证据，不是事实数据库；package 信息必须在固定 Ubuntu Snapshot 中重新验证。
6. World State 只保存结构化事实和 Artifact 引用，不保存模型隐藏思维过程。
7. Micro speedup 是局部证据；系统 Reward 必须来自真实 End-to-End Portfolio。

## 两层控制 Flow

```text
BOOTSTRAP
  |
  v
OBSERVE -> SUMMARIZE -> MANAGER_DECISION -> POLICY_VALIDATE
                                              |
                               rejected <-----+-----> accepted
                                                         |
                                                         v
                                                  EXECUTE_ACTION
                                                         |
                          +------------------------------+----------------+
                          |                                               |
                          v                                               v
                    固定 package Mission                         非 package Action
                          |                              Research / Mission / Capability / E2E
                          v
                  独立确定性 Clean Judge
                          |
                          v
             CLASSIFY_OUTCOME -> UPDATE_MEMORY
                          |
                          v
             CAPABILITY / PORTFOLIO CHECK
                          |
                          v
              确定性 ConvergenceEvaluator
```

外层 Argus 每个 Life Cycle 都读取完整持久化 World State，并只能选择 Schema 允许的一项 Action。`PolicyEngine` 在任何副作用发生前验证 Action shape、target、evidence、concurrency 和 budget。

Manager 可以创建、重排、暂停、恢复或终止 Mission，创建 Research Snapshot，提议或启动 Capability Mission，执行 Portfolio E2E，以及提出停止建议。它不能修改 Fence、接受 Candidate、改变官方 Baseline、修改测量证据、发布 package 或直接停止 Run。

## 固定 LDA Mission

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

Mission Executor 必须创建不可变 contract hash、Candidate record、disposable Work Sandbox、独立 Planner/Builder/Reviewer session、确定性 build evidence、Benchmark Artifact 和独立 Judge Sandbox。

两个 Canary 从固定 source bundle 构建，必须同时生成 runtime 与 development `.deb`。其余八个 package 也必须使用真实 Debian Source Builder：固定 Snapshot、精确 source/version、唯一 `.dsc`、`dpkg-source -x`、source version 复核、build-dep、`dpkg-checkbuilddeps`、`dpkg-buildpackage` 和 `.deb` metadata/hash。package-specific Judge 证据缺失时必须 fail closed。

## World State 与 Event Store

```text
WorldState
|- run_id / life_cycle / active
|- RunBudget / HardwareProfile
|- research_snapshots / package_inventory
|- missions / candidates
|- benchmark_ledger / outcome_ledger
|- capabilities / fence_versions
|- portfolio_e2e / convergence_signals
|- campaign_input / qualification
`- agent_sessions
```

Controller 通过临时文件原子替换写入 `.lda/world.json`。`.lda/events.jsonl` 只追加；每条 Event 包含 run/cycle、actor、event type、input/output refs、timestamp、previous hash、redacted payload 和自身 hash。

恢复流程加载 World State、恢复持久 Agent session 引用，并重新排队仍可重试的 invalid-evidence Mission，不依赖任何 Agent 记住历史。

## AgentFactory 与 Thread 独立性

| Role | Thread Policy | Independence Boundary |
| --- | --- | --- |
| Argus Manager | 每个 Life Cycle 新建 | Manager Cycle |
| World State Summarizer | 每个 Cycle 新建 | Summary Cycle |
| Mission Planner | 每个 Mission 新建 | Mission |
| Builder | 持久 | Candidate |
| Reviewer | 每轮全新 | Review Round |
| Outcome Classifier | 每次结果新建 | Mission Outcome |
| Capability Builder | 持久 | Capability |

Builder 持久 session 会把 E2B Sandbox ID 和真实 Codex thread ID 写入 World State。Reviewer 使用不同 session key，不能继承 Builder history。Agent 输出必须通过 role-specific JSON Schema；格式错误的输出不能成为 Policy Action 或 Judge Evidence。

## E2B 信任边界

```text
Controller Sandbox
|- Manager / Summarizer Agent Runtime
|- Planner / Builder / Reviewer Agent Runtime
|- Candidate Work Sandbox
|- Capability Work Sandbox
|- Judge Sandbox
`- Portfolio E2E Sandbox
```

| Boundary | Network | Secret | Model | 职责 |
| --- | --- | --- | --- | --- |
| Bootstrap/Controller | E2B gateway | E2B 控制凭据 | 无验收权 | create/connect/reap、持久化、调度 |
| Agent Runtime | 模型 Provider | 仅模型凭据 | Codex CLI | 结构化研究、规划、构建建议、Review |
| Candidate Work | 固定 package mirror | 无 | 无 | source、build、profile、local verify、Benchmark |
| Judge | 禁止 | 无 | 无 | compatibility、FFI、install、rollback、anti-cheat |
| E2E | workload 所需 | 无 | 无 | system workload measurement |

Candidate、Qualification、E2E 和 Judge 不获得模型 Secret；Judge 不属于允许联网的 role。Shared Gateway Adapter 保留 SDK Header，并仅在 Control URL 与 Sandbox URL 相同时幂等增加认证 Header。

## Preflight

生产 `lda run` 必须通过已测试 SDK、control create、data command、filesystem、background PID、reconnect、snapshot/fork fallback、metadata、network restriction、hardware fingerprint、orphan reap、template manifest 和 kill。任一检查失败都会阻止 Run。

## Campaign 与 Qualification

Campaign preparation 复制原始调研输入、记录 bytes/lines/SHA-256、生成 Manifest，并把同一内容上传到 Controller 与 Qualification Sandbox 后重新计算 hash。

Qualification 在固定 Ubuntu 26.04 Snapshot 中验证 binary metadata、source mapping、dependency metadata、source index、source hash、unpack、clean rebuild 和 blocker。Checkpoint 允许 Controller 重启后保留已完成 row。

初始只授权 `libcairo2` 与 `libsoup-3.0-0`。其余八个 package 只有在两个 Canary 都获得 `SUCCESS_SYSTEM`、valid accepted Benchmark、达到 Portfolio geomean 和 improved workload 数量要求后才进入 Mission Graph。

## Deterministic Judge

Canary Judge 向全新离线 Sandbox 传输 official/candidate 的 runtime/development 四个 `.deb`。Judge 比较 package/version/architecture、payload path、control declaration、SONAME、dynamic symbol、symbol version、`NEEDED`、header 和 pkg-config；执行安装、预编译 C FFI probe、Python `ctypes` 和官方 rollback。

Evidence 包含 package、Judge script、预编译 probe 的 hash，以及 command output hash、环境事实和 anti-cheat finding。Controller 会独立核对 transfer bytes 与 Judge 报告 hash。任何必需字段缺失或 false 都会 Reject。

## Benchmark、Hardware 与 Outcome

默认 Micro Benchmark 使用 10 次 warmup 和 30 个原始样本，计算 speedup 与 CI lower bound。Portfolio 由 workload 到 measured speedup ratio 的映射组成，LDA 只计算 geomean 与 improved-workload count，不累加 Micro gain。

Canary harness 记录 CPU model、vendor、family/model/stepping、microcode、ISA flags、kernel、governor、turbo 和 NUMA。虚拟 CPUID 只能建立 ISA/架构兼容性，不能证明物理 Host 身份。

Outcome 分类包含 compatibility failure、invalid benchmark、regression、local success、system success、capability gap 和 no optimization space。数值 speedup 不能单独产生 `SUCCESS_SYSTEM`。

## Capability 生命周期

```text
PROPOSED -> POLICY_APPROVED -> BUILDING -> ISOLATED_TEST
-> ADVERSARIAL_REVIEW -> CAPABILITY_JUDGE -> ACTIVE
```

状态不能跳过或重复。`ISOLATED_TEST` 必须记录 passing evidence，`ACTIVE` 必须由 passing Capability Judge 决定。`ACTIVE` 与 `REJECTED` 是终态。

Capability Executor 由 Capability Builder、独立 Work Sandbox、隔离测试、全新 Reviewer 和无 Secret/无网络 Capability Judge 组成。Builder 输出文件被限制在 Capability Workspace，测试命令禁止下载、系统调优和 Fence/Judge 修改，Artifact 在二次 Judge 前后按 SHA-256 核对。

## 长命令恢复

长时间 `apt-get build-dep` 和 `dpkg-buildpackage` 使用 sandbox-side checkpoint：Sandbox 后台执行，stdout/stderr/exit code 写入 job 目录，Controller 只执行短轮询 RPC；完成后读取完整证据，超时返回确定性 exit code 124。这样单次 streaming RPC deadline 不会直接杀死仍在 E2B 中运行的 build。

## Convergence

只有 `ConvergenceEvaluator` 可以结束 Run。条件包括 max life cycles、预算耗尽、连续三个 quiet cycle、所有高优先级 Mission 终止，以及 Portfolio target 达标。Manager stop proposal 只作为 signal。
