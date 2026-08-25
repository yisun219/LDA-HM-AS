FROM ubuntu:26.04
RUN apt-get update && apt-get install -y --no-install-recommends build-essential clang lld cmake ninja-build meson autoconf automake libtool debhelper devscripts perf strace valgrind bpftrace numactl pkg-config && rm -rf /var/lib/apt/lists/*
COPY manifest.json /opt/lda/template-manifest.json
WORKDIR /workspace
