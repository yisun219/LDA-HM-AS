FROM ubuntu:26.04

ARG CODEX_RELEASE=0.149.1
ARG INTEL_PERFORMANCE_SKILLS_COMMIT=e9d0b6410fb1ad7a50fb81e0868fd23ae886882c

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

RUN export CODEX_RELEASE="$CODEX_RELEASE" \
      CODEX_NON_INTERACTIVE=1 \
      CODEX_INSTALL_DIR=/usr/local/bin \
      CODEX_HOME=/opt/codex \
    && curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/install-codex.sh \
    && sh /tmp/install-codex.sh \
    && rm /tmp/install-codex.sh \
    && codex --version | grep -F "$CODEX_RELEASE"

RUN git init /opt/lda/intel-performance-skills \
    && git -C /opt/lda/intel-performance-skills remote add origin \
       https://github.com/intel/intel-performance-skills.git \
    && git -C /opt/lda/intel-performance-skills fetch --depth 1 origin \
       "$INTEL_PERFORMANCE_SKILLS_COMMIT" \
    && git -C /opt/lda/intel-performance-skills checkout --detach FETCH_HEAD \
    && test "$(git -C /opt/lda/intel-performance-skills rev-parse HEAD)" = \
       "$INTEL_PERFORMANCE_SKILLS_COMMIT" \
    && rm -rf /opt/lda/intel-performance-skills/.git \
    && printf '{"codex_release":"%s","intel_performance_skills_commit":"%s"}\n' \
       "$CODEX_RELEASE" "$INTEL_PERFORMANCE_SKILLS_COMMIT" \
       > /opt/lda/agent-runtime-versions.json

COPY manifest.json /opt/lda/template-manifest.json
WORKDIR /workspace
