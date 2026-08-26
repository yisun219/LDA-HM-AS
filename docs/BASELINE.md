# Ubuntu 26.04 Baseline Contract

LDA 严格区分“发行版候选证据”和“可执行 package baseline”。

## 候选证据

Ubuntu 26.04 Desktop amd64 ISO manifest 用来回答目标桌面发行版包含哪些 Debian package 和 Snap。用户提供的依赖图、排名和 Top 10 是 Campaign 的候选选择证据。LDA 保存调研原文和 SHA-256，但不会默认其中的 package identity、依赖解析或排名结论正确。

当前调研输入：

```text
/Users/yisun/Desktop/Ubuntu ISO 解析结果及包优化推荐.md
SHA-256: 0f8e53e751953c93b587f8b78207038e5083e62f2c671bb5ea5a91a798035f04
Research Snapshot: research-368c0a9013d940c1aadb6fcd3b78a380
```

Run 开始时，LDA 逐字节导入该文件，把原始副本上传到 E2B 持久化空间并发布为不可变 artifact。Builder、Reviewer、恢复任务和审计任务都引用同一个内容哈希。

## 可执行 Baseline

实际构建和验收使用固定 Ubuntu Packages/Sources Snapshot：

```text
snapshot=https://snapshot.ubuntu.com/ubuntu/20260825T000000Z
release=26.04
codename=resolute
architecture=amd64
```

每个 Mission 必须在 Agent 修改源码前独立验证：

1. binary package 的精确名称、版本和架构；
2. 对应的 source package 和 source version；
3. Depends、Pre-Depends、Provides 与 alternative dependency；
4. 调研报告中相关 unresolved edge；
5. 固定源码能否在干净 `lda-base` 中重建；
6. 是否存在可复现、可稳定测量的真实性能热点；
7. 是否能建立 Micro 和 End-to-End benchmark；
8. Candidate `.deb` 是否能原位替换并恢复官方包。

LDA 下载精确官方 `.deb`、`.dsc`、upstream archive 和 Debian source archive，记录确定性 source bundle hash 与每个 package 的 SHA-256，并在 Mission Contract 中封存身份、测试、路径边界、workload 和验收策略。

## A/B/A' 模型

干净 Judge 会重新从固定 Snapshot 下载源码和 package，先核对 Contract 中的哈希，再应用 Candidate Patch：

```text
A  = 官方 Ubuntu .deb + 固定 Snapshot 的未修改源码
B  = 在 A 的源码上应用 Candidate Patch 后重新构建的 .deb
A' = E2E 测试后重新安装并验证的官方 Ubuntu .deb
```

- ABI/API/FFI identity 直接以官方 `A` 为准。
- Build reproducibility 使用未修改源码 rebuild。
- Candidate Micro Benchmark 在同一干净 Judge 环境比较 `A` 与 `B`。
- Portfolio E2E 随机化安装 `A`/`B`、保存原始样本，结束时恢复并验证 `A'`。

官方 runtime binary 往往已经 strip。SONAME、symbol、symbol version、安装路径和预编译 consumer 始终直接比较官方 binary；需要 DWARF 的公开类型 ABI 检查，则使用同一固定源码产生的未修改 debug rebuild 与 Candidate debug rebuild。Debug rebuild 只是类型信息对照，不会替代官方 package identity。

## E2B 环境边界

E2B Template 固定编译器、Debian build tool、Profiler、ABI/FFI tool、Benchmark harness 和目标 CPU 证据。它不是 ISO 启动出来的完整 rootfs，也不会伪造 ISO SHA-256、build ID、rootfs digest 或 E2B Snapshot identity。

若以后增加 ISO-rootfs 模式，必须额外冻结并验证：

- ISO SHA-256 和 build ID；
- rootfs digest；
- Debian manifest digest；
- Snap manifest digest；
- 构建该 rootfs 的不可变 E2B Snapshot identity。

在这些数据真实取得前，不能从 package 调研报告中推导或填写它们。
