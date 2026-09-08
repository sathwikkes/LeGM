# LeGM API (FastAPI + WebSocket). Build from the repo root:
#   docker build -t legm-api .
#   docker run -p 8000:8000 -e LEGM_SECRET_KEY=... -v $(pwd)/data:/app/data legm-api
# Kept free of BuildKit-only syntax (cache mounts, VOLUME) so Railway's builder accepts it.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

WORKDIR /app

# Dependencies first so they cache independently of source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY legm ./legm
COPY config ./config
COPY README.md ./
COPY data/raw ./data/raw
RUN uv sync --frozen --no-dev

# Player data lives here (SQLite by default). Mount a volume here, or point
# LEGM_DATABASE_URL at Postgres so the container stays stateless.
RUN useradd --create-home --uid 10001 legm && chown -R legm:legm /app
USER legm

ENV PATH="/app/.venv/bin:$PATH" LEGM_CORS_ORIGINS="http://localhost:3000" PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=3).status == 200 else 1)"

# Shell form so $PORT (set by Railway, Fly, Render, etc.) is honoured.
CMD uvicorn legm.api.app:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
