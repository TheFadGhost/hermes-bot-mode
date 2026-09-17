# syntax=docker/dockerfile:1.7
# Build from the bot-mode root so this file can consume the separately-owned
# ../backend and ../frontend trees without copying either into integration/.

ARG CODEX_CLI_VERSION=0.154.0

FROM node:22-bookworm-slim AS codex-cli
ARG CODEX_CLI_VERSION
RUN npm install --global "@openai/codex@${CODEX_CLI_VERSION}" \
    && codex --version

FROM node:22-bookworm-slim AS web-build
WORKDIR /src
COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOT_BIND_HOST=127.0.0.1 \
    BOT_BIND_PORT=9120 \
    BOT_MODE_STATIC_DIR=/app/static \
    BOT_DATABASE_PATH=/data/bot-mode.sqlite3 \
    BOT_WORKSPACE_ROOT=/data/workspaces \
    BOT_DEFAULT_MODEL=gpt-5.6-luna \
    BOT_DESKTOP_URL=http://127.0.0.1:9121 \
    BOT_DESKTOP_SECRET="" \
    CODEX_HOME=/data/codex \
    CODEX_CLI=/usr/local/bin/codex

# Copy the pinned CLI and its Node runtime into the Python service image. The
# backend launches one stdio app-server process; no Telegram poller lives here.
COPY --from=codex-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=codex-cli /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && codex --version

WORKDIR /app
COPY backend/ /tmp/bot-mode-backend/
RUN python -m pip install --no-cache-dir /tmp/bot-mode-backend \
    && rm -rf /tmp/bot-mode-backend
COPY --from=web-build /src/dist /app/static
COPY skills/slopmonster/ /app/skills/slopmonster/

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin botmode \
    && mkdir -p /data \
    && chown -R botmode:botmode /app /data
USER botmode
VOLUME ["/data"]
EXPOSE 9120

CMD ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "9120"]
