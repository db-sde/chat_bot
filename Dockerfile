FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy chatbot pyproject.toml and lockfile
COPY chatbot/pyproject.toml chatbot/uv.lock chatbot/README.md ./

# Install dependencies into system Python
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy remaining chatbot code
COPY chatbot/ .

# Ensure var directory exists
RUN mkdir -p var

EXPOSE 8000

# Bind dynamically to Railway's $PORT (defaults to 8000 if PORT is unset)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
