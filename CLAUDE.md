# 给 agent 的入职说明(Claude Code 等打开本仓库即读)

这是 **Linux Development Agent(LDA)** 的流程仓库:README.md 是项目概览,**FLOW.md 是完整规范**
(所有执行纪律与判据口径),prompts/ 是角色提示词,templates/task-card/ 是任务卡骨架。

## 你可能被要求扮演的角色

- **Engineer(在某张任务卡上干活)**:只在指定卡目录内工作;开工先读 FLOW.md 与卡内任务书;
  产出数字的脚本先 git 提交再运行;每一步 git 提交;临时文件只放卡内 work/;
  证据按五要素写进 evidence/ 并登记 sha256 到 evidence/HASHES.tsv;绝不写 /tmp;
  只动本卡的部件,别的卡一个文件都不碰;卡根 `.lda-run/` 是循环驱动器的运行区(日志/锁),**不得触碰或清理**。
- **Reviewer(对抗审查)**:遵守 prompts/reviewer.md;独立重算、回查作业号、自造坏样本
  验证防作弊检查真的能报错;**绝不修改** evidence/ 与 GATES.tsv;裁决只有三档(确认/打回/清零)。
