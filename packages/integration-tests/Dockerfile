FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml ./
COPY packages/ packages/

RUN uv sync --no-dev --package concerto-integration-tests

CMD ["uv", "run", "pytest", "packages/integration-tests/tests/", "-v", "--color=yes", "--junitxml=/results/integration.xml"]
