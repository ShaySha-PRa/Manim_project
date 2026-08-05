FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY apps/api ./apps/api
COPY apps/runner ./apps/runner
COPY packages/contracts ./packages/contracts
COPY migrations ./migrations
COPY infra/api_entrypoint.py ./infra/api_entrypoint.py

RUN python -m pip install --no-cache-dir . \
    && groupadd --gid 10001 workbench \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin workbench \
    && mkdir -p /data \
    && chown workbench:workbench /data

EXPOSE 8000
ENTRYPOINT ["python", "/app/infra/api_entrypoint.py"]
