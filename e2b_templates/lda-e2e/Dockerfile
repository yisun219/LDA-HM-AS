FROM ubuntu:26.04
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates fonts-dejavu-core \
    && python3 -m pip install --break-system-packages playwright==1.55.0 \
    && python3 -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/ms-playwright \
    && rm -rf /var/lib/apt/lists/*
COPY manifest.json /opt/lda/template-manifest.json
COPY run_portfolio_e2e.py /opt/lda/run_portfolio_e2e.py
COPY run-portfolio-e2e /usr/local/bin/run-portfolio-e2e
RUN chmod 0555 /opt/lda/run_portfolio_e2e.py /usr/local/bin/run-portfolio-e2e && mkdir -p /workspace/artifacts
WORKDIR /workspace
