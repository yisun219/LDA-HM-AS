# lda-base:标准执行环境

流程的执行端统一在这一张模板上:编译打包工具链、兼容性比对与测量工具、
agent 运行时(node + Claude Code CLI)与预置技能包(`skills/`,箱内位于 `/opt/lda/skills`,
并链到 `~/.claude/skills`)。公共依赖只装这一次,之后每个沙箱从快照秒级克隆,脏了就丢。

```bash
# 构建(需要 E2B 凭据在环境里)
python3 tools/e2b/template/build.py            # 默认命名 lda-base
python3 tools/e2b/template/build.py my-base    # 换个名字

# 让流程默认用它
export E2B_TEMPLATE=lda-base
```

改环境就是改 `lda-base.Dockerfile`;加技能就是往 `skills/` 里放一个 .md,重建模板即生效。

没有 E2B 服务时,同一份 Dockerfile 可 `docker build` 当本地容器用,实验命令与证据要求不变。
