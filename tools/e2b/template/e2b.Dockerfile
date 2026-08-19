# LDA 实验环境快照配方:Ubuntu 26.04 + .deb 重建工具链
# 预装一次做成模板,之后每个沙箱从快照秒级克隆(FLOW §8)。
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
# 开 deb-src(apt-get source 需要)
RUN sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential dpkg-dev devscripts fakeroot quilt \
      abigail-tools strace time git curl ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/*
