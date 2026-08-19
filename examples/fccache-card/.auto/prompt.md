# 任务卡:fccache-card(示例·真实 Ubuntu 26.04 加速任务:删掉 fc-cache 里为 FAT 文件系统留的 2 秒死等)

这是一张**真实任务卡**,与本流程生产出第一个加速交付物的卡同源(fontconfig 整族 .deb,
micro 层每次 `fc-cache -f` 消除约 2 秒,并通过了独立对抗审查)。开工先读仓库根 **FLOW.md**
(§3 兼容红线/§9 测量规则/§10 检查点标准/§11-§12 交付)。

## 运行环境要求(先看这一条)

本卡的实验必须在 **Ubuntu 26.04** 环境里执行:推荐按 FLOW §8 使用 E2B 沙箱
(模板=预装 build-essential/dpkg-dev/devscripts/fakeroot/abigail-tools 的 26.04 快照);
没有沙箱服务时,任一 Ubuntu 26.04 容器/虚拟机等价。引擎会话本身可以在任何机器上,
但每条实验命令要在 26.04 环境内执行,并把**原始输出**取回卡内 evidence/。
`apt-get source` 前先把 `/etc/apt/sources.list.d/ubuntu.sources` 的 `Types:` 改为 `deb deb-src`。
**跑前先把本卡拷贝到 `tasks/` 并 `git init`**(示例原件保持干净,避免日后 `git pull` 冲突)。

## 目标(一句话)

fontconfig 的 `fc-cache` 在收尾处为 1990 年代 FAT 文件系统的 mtime 粒度留了一个
**无条件 sleep(2)**——在现代文件系统上是纯死等。把它安全地去掉,整族重建 `.deb`
(版本后缀 `a0turbo1`),证明 micro 层每次 `fc-cache -f` **消除约 2000ms** 且行为零变化;
**若发现该 sleep 在当前版本仍承担正确性职责,前提证伪,整卡停下如实收尾——那也是结论**。

## 前提(已知事实,你只需在自己的构建源上复核)

- 源码:`fc-cache/fc-cache.c` 约 417-426 行,注释原文含
  "Now we need to sleep a second (or two, to be extra sure)" 与
  `/* the resolution of mtime on FAT is 2 seconds */`,随后 `if (changed) sleep (2);`
- 打包路径:`debian/fontconfig.postinst` 触发器路径用 `fc-cache -s -v`(不带 -f,一般不睡);
  fontconfig 自身配置时用 `fc-cache -s -f -v`(-f ⇒ changed 恒真 ⇒ 必睡);
- 运行时可见证:冷缓存 `fc-cache -f` 全程 ≈2.0 秒被一次
  `clock_nanosleep({tv_sec=2})` 占据(strace 可证),热态(无 -f)毫秒级。
- 收益面要如实写窄:带 `-f` 的调用(fontconfig 自身装/升级/重配 + 工具链手工调用);
  普通字体包安装的触发器不带 -f,不在收益面内。

## 检查点定义(与 state/GATES.tsv 一一对应)

### G0 前提复核
在你的构建源上复核上述源码行号与 postinst 两条路径;strace 见证 `clock_nanosleep(tv_sec=2)`;
说明为什么删它不破坏缓存有效性判定(fontconfig 自身的缓存校验逻辑,行号级)。记 `PREMISE-CONFIRMED`。

### G1 micro(判据=消除的等待时间)
- 负载:`fc-cache -f`(冷/热两态)与 postinst 的 `-s -f` 形态;同一实例内 **A,B,A,B 交替**
  + A→B→A′ 三段;重复次数先算后跑;
- 读数:wall 毫秒 + `clock_nanosleep(tv_sec=2)` 出现次数(**补丁臂必须=0**,产物级证据);
- 预注册(rules.json,跑前冻结):方向=补丁臂快,区间 **1900-2100ms**;冷扫描耗时不算本卡收益;
- 测量有效性自证:往对照臂注入已知 sleep 的慢臂必须被判显著慢;空对照必须无差;原始逐次观测入 evidence/。

### G2 ABI 门
整族重建(以 `debian/control` 为准,实测该源码包共出 6 个二进制包:fontconfig /
fontconfig-config / libfontconfig1 / libfontconfig-dev / libfontconfig1-dev / libfontconfig-doc)
版本 `a0turbo1`;**`libfontconfig.so` 必须与
未打补丁的重建逐字节相同**(本卡只准动 fc-cache 可执行文件;.so 有差分=夹带,查明);
两臂完整编译旗逐项对照,只许零差异。

### G3 行为等价(含本卡命门)
- 同字体集两臂 `fc-cache -f` 后:`fc-list` 输出全同、缓存文件可被对方臂正常读取;
- 毒样本:故意截断一个缓存文件,两臂都必须能检出并重建(证据留 POISON-CAUGHT);
- **时间戳边界(命门,必答)**:构造"fc-cache 结束的同一秒内改字体目录"的场景,
  用行为见证证明补丁臂的缓存有效性判定仍然正确——这正是那句 sleep 想防的事,
  答不上来=前提动摇,如实上报停卡;
- FFI:不重编译的调用方(如 python3 gi/fontconfig 绑定)两臂行为一致。

### G4 交付
版本序矩阵:`a0turbo1` 覆盖基础版本、且**不压制** `ubuntu0.X` 形状的官方安全更新(真跑比较);
安装→升级→卸载→重装全循环 + `dpkg -V`(带未改动对照臂);归因=FLOW §11 第 1 类
(历史保守值,上游可提补丁——材料整理进卡,提交与否由仓库所有者决定)。

### G5 端到端(记录义务)
真实事务:`apt-get install --reinstall fontconfig`(走 postinst `-s -f` 路径)装前/装后
A,B,A,B;数字带机器/环境标识与日期;**不与 micro 并排**。

### G6 收尾
运行 `bash .auto/checks.sh`(先对故意做坏的样本验证它会报错),退出码写进证据;
`work/` 残留清零(被证据引用的原始数据在 evidence/,不许删);八条兼容线逐条判
(不适用的写一句理由);已知问题开登记册(KI-N 只追加)。

## 铁律(FLOW 摘)
五要素证据(无调度作业标 NO-JOB 与逐步 rc);产数脚本先提交再运行;每步 git 提交;
临时只放卡内 work/;门证据登记 sha256 进 evidence/HASHES.tsv;对照臂仪器必须相同;
一卡一部件(只动 fontconfig 族);卡根 .lda-run/ 是驱动器运行区,不得触碰。

## 审查反馈(只增不删)
<!-- Reviewer 追加;Engineer 不得修改或删除已有条目 -->
