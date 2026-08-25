FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    LDA_TARGET_CPU="INTEL(R) XEON(R) GOLD 6548Y+" \
    LDA_TARGET_RELEASE="ubuntu-26.04" \
    PATH="/opt/lda/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential clang cmake ninja-build meson pkg-config \
    git git-lfs python3 python3-pip python3-venv \
    nodejs npm \
    binutils elfutils abigail-tools \
    libffi-dev strace linux-tools-generic devscripts debhelper \
    ca-certificates jq curl wget procps file time \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code @earendil-works/pi-coding-agent playwright \
    && npx playwright install --with-deps chromium

RUN mkdir -p /opt/lda/{bin,skills,harness,work,evidence}

COPY skills/ /opt/lda/skills/
COPY harness/ /opt/lda/harness/
COPY checks/ /opt/lda/harness/checks/

RUN chmod +x /opt/lda/harness/lda-agent-harness.sh /opt/lda/harness/checks/*.sh

RUN git clone https://github.com/intel/intel-performance-skills.git /opt/lda/skills/intel-performance-skills \
    && git -C /opt/lda/skills/intel-performance-skills checkout e9d0b6410fb1ad7a50fb81e0868fd23ae886882c \
    && rm -rf /opt/lda/skills/intel-performance-skills/.git

WORKDIR /opt/lda/work

CMD ["/bin/bash"]
