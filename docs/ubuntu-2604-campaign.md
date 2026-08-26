# Ubuntu 26.04 Campaign 协议

本 Campaign 以版本化调研输入作为候选来源。原始输入必须在 Run 开始前完整复制到 Artifact Store，记录 SHA-256，并把同一字节序列上传到 Controller 和 Qualification Sandbox。调研排名只提供候选筛选证据，不直接授权源码修改。

## 首批候选

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

## Qualification

每个候选必须在固定 Ubuntu 26.04 Packages/Sources Snapshot 中独立验证：

1. binary package 的准确名称、版本和架构；
2. binary 对应的 source package 和 source version；
3. Depends、Pre-Depends、Provides、alternative dependency 和 unresolved edge；
4. source hash、解包和干净重建；
5. 可复现性能热点与稳定 Benchmark；
6. Micro 和 End-to-End workload 映射；
7. `.deb` 原位替换、兼容性和 rollback 能力。

Qualification 输出为逐 package 的结构化 record、evidence refs 和 blocker。报告中的排名不能替代这些证据。

## Canary Gate

第一批 Canary 是 `libcairo2` 和 `libsoup-3.0-0`。两个 Canary 必须分别完成 Baseline、Builder、Reviewer、ABI/API/FFI、Micro、E2E、`.deb` 替换和 rollback，并获得确定性 Judge 接受。

只有两个 Canary 都形成有效系统级测量，且 Portfolio Gate 达到配置阈值，Policy 才能把其余八个候选加入动态 Mission Graph。Manager 无权跳过该 Gate。

## 重新排序

Top 10 的报告顺序表示 dependency graph 重要程度，不等于优化顺序。Qualification 后的优先级必须综合：

- 可复现热点；
- Benchmark 稳定性；
- ABI/FFI 风险；
- 构建和 Judge 成本；
- 预期收益与系统 workload 覆盖；
- Capability readiness 和剩余全局预算。

所有调整写入 Event Store；旧 Research Snapshot、Qualification record 和排名证据不可覆盖。
