FROM ubuntu:26.04
ARG INTEL_PERFORMANCE_SKILLS_COMMIT=e9d0b6410fb1ad7a50fb81e0868fd23ae886882c
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential clang lld cmake ninja-build meson autoconf automake libtool \
    debhelper devscripts dpkg-dev equivs pkg-config \
    linux-tools-generic strace valgrind bpftrace numactl \
    abi-compliance-checker abi-dumper abigail-tools \
    python3 python3-dev python3-pip rustc cargo ca-certificates git \
    && git clone https://github.com/intel/intel-performance-skills.git /opt/lda/intel-performance-skills \
    && git -C /opt/lda/intel-performance-skills checkout "${INTEL_PERFORMANCE_SKILLS_COMMIT}" \
    && test "$(git -C /opt/lda/intel-performance-skills rev-parse HEAD)" = "${INTEL_PERFORMANCE_SKILLS_COMMIT}" \
    && rm -rf /opt/lda/intel-performance-skills/.git /var/lib/apt/lists/*
COPY manifest.json /opt/lda/template-manifest.json
WORKDIR /workspace
