FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY manifest.json /opt/lda/template-manifest.json
WORKDIR /workspace
