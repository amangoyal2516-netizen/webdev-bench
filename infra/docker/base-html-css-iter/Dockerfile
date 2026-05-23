# Agent container for the -iter variant: -oneshot + Playwright + headless
# Chromium so the agent can render its own HTML and screenshot the result.
# Used in the A/B comparison vs -oneshot (decision #8).

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash coreutils curl ca-certificates git tree jq less \
        # Chromium runtime deps
        libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
        libasound2 libatspi2.0-0 libglib2.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.49.0
# `chromium` only — runtime libs are already installed in the apt block
# above. `--with-deps` would re-trigger apt for fonts (ttf-ubuntu-font-family,
# ttf-unifont) that don't exist in Debian Trixie and fail the build.
RUN playwright install chromium

WORKDIR /workspace
RUN mkdir -p /workspace/output /workspace/assets /workspace/reference

# One-liner render helper the agent can use, documented in instruction.md.
COPY render.sh /usr/local/bin/render
RUN chmod +x /usr/local/bin/render
