# lda-base —— LDA 的标准执行环境
# 一张模板承载全部执行端:编译打包工具链、测量工具、agent 运行时与技能包。
# 所有任务卡的沙箱都从它秒级克隆,环境一致才有可比性。
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive LC_ALL=C LANG=C TZ=UTC

# apt 源开 deb-src(apt-get source 需要,免掉每张卡自己改)
RUN sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources || true

# 编译与打包工具链
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential dpkg-dev devscripts debhelper fakeroot quilt patch \
      pkg-config cmake ninja-build autoconf automake libtool m4 ccache patchelf \
      gcc g++ binutils file xz-utils zstd bzip2 \
 && rm -rf /var/lib/apt/lists/*

# 兼容性比对与测量诊断
RUN apt-get update && apt-get install -y --no-install-recommends \
      abigail-tools strace ltrace time bsdextrautils \
 && rm -rf /var/lib/apt/lists/*

# 运行时与 agent 运行环境
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv git curl wget ca-certificates jq unzip \
      nodejs npm tmux \
 && rm -rf /var/lib/apt/lists/*

# 技能包、harness 清单与工作目录由 build.py 内联追加(本网关的构建接口不支持 COPY)
