# 实验环境快照(模板)配方

流程的实验段统一在 Ubuntu 26.04 沙箱里跑;公共依赖预装一次做成模板,
新沙箱从快照秒级克隆,脏了就丢。本目录就是那份模板的完整配方。

```bash
# 在本目录构建并命名模板(E2B 官方云或自建网关均可)
e2b template build --name lda-ubuntu2604

# 之后让流程默认用它
export E2B_TEMPLATE=lda-ubuntu2604
```

没有 E2B 服务时,同一份 Dockerfile 可直接 `docker build` 当本地容器用,
实验命令与证据要求不变(FLOW §8 的三选一实验环境)。
