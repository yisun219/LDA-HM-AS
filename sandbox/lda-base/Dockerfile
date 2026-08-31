FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive \
    LDA_TARGET_CPU="INTEL(R) XEON(R) GOLD 6548Y+" \
    LDA_TARGET_RELEASE="ubuntu-26.04" \
    PLAYWRIGHT_BROWSERS_PATH="/opt/lda/ms-playwright" \
    PATH="/opt/lda/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential clang cmake ninja-build meson pkg-config \
    git git-lfs python3 python3-pip python3-venv \
    nodejs npm \
    binutils elfutils abigail-tools \
    libffi-dev strace linux-perf devscripts debhelper dpkg-dev fakeroot \
    ca-certificates jq curl wget procps file time sudo xz-utils squashfs-tools \
    libpng-dev libpng-tools python3-pil libgdk-pixbuf2.0-bin \
    xvfb xauth dbus-x11 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/lda/ms-playwright \
    && npm install -g @anthropic-ai/claude-code @openai/codex @earendil-works/pi-coding-agent playwright \
    && PLAYWRIGHT_BROWSERS_PATH=/opt/lda/ms-playwright npx playwright install --with-deps chromium

RUN id -u user >/dev/null 2>&1 || useradd --create-home --shell /bin/bash user; \
    printf '%s\n' 'user ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/lda-user; \
    chmod 0440 /etc/sudoers.d/lda-user; \
    mkdir -p /opt/lda/{bin,skills,harness,baseline,work,evidence}; \
    chown -R user:user /opt/lda

COPY skills/ /opt/lda/skills/
COPY harness/ /opt/lda/harness/
COPY checks/ /opt/lda/harness/checks/
COPY humanize/ /opt/lda/humanize/

RUN find /opt/lda/harness /opt/lda/humanize -type f -name '*.sh' -exec chmod +x {} +

# Agent skills: Claude Code loads skills from ~/.claude/skills/<name>/SKILL.md,
# so every LDA skill directory and every vendored Intel performance skill is
# linked there for the in-sandbox agent user.
RUN mkdir -p /home/user/.claude/skills \
    && for skill in /opt/lda/skills/*/SKILL.md /opt/lda/skills/intel-performance-skills/skills/*/SKILL.md; do \
         dir="$(dirname "$skill")"; ln -sfn "$dir" "/home/user/.claude/skills/$(basename "$dir")"; \
       done \
    && chown -R user:user /opt/lda /home/user

USER user

WORKDIR /opt/lda/work

CMD ["/bin/bash"]
