FROM ubuntu:26.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates chromium-browser && rm -rf /var/lib/apt/lists/*
COPY manifest.json /opt/lda/template-manifest.json
WORKDIR /workspace
