FROM node:24-slim

# System deps: git for repo cloning, python3 for worker, dumb-init for PID 1
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        python3 \
        python3-pip \
        python3-venv \
        dumb-init \
    && rm -rf /var/lib/apt/lists/*

# uv for Python dependency management (matches project conventions)
RUN pip3 install uv --break-system-packages --quiet

# OpenClaw CLI (needs Node 22.14+ — satisfied by node:24-slim)
RUN npm install -g openclaw@latest --quiet

WORKDIR /app

# Install Python deps into a venv via uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

# OpenClaw agent config (executor profile; API keys come from env at runtime)
RUN mkdir -p /root/.openclaw
COPY openclaw.json /root/.openclaw/openclaw.json

# Worker source
COPY src/ ./src/

# Task working directories are created here at runtime
RUN mkdir -p /workspace

CMD ["dumb-init", "python3", "src/worker.py"]
