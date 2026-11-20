# API + job worker image. Both services share this image and differ only by command.
FROM python:3.13-slim

# No .pyc writes in a read-only-ish runtime; unbuffered logs so `docker logs` is live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The read-only MCP servers are installed too: they mount inside the API process.
# Drop the extra (".[mcp]") if you do not want them.
COPY pyproject.toml ./
COPY xenovarients ./xenovarients
RUN python -m pip install ".[mcp]"

# Alembic runs from /app so `alembic upgrade head` finds alembic.ini and its versions.
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chown -R app:app /app
USER app

EXPOSE 8001

# `alembic upgrade head` when RUN_MIGRATIONS=true, then exec the service command.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "xenovarients.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers"]
