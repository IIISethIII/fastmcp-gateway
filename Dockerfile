FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

# Copy application source code
COPY app /app/app

# Client-side scope patch: the MCP SDK's validate_scope() rejects Google-granted
# scopes during the OAuth 2.1 flow (workspace-mcp DCR/metadata quirks). In this
# trusted single-tenant setup scope subset validation is unnecessary.
COPY app/oauth_client_scope_patch.py /usr/local/lib/python3.12/site-packages/sitecustomize.py

# Create shared_brain mount point
RUN mkdir -p /app/shared_brain

EXPOSE 8000

CMD ["python", "-m", "app.server"]
