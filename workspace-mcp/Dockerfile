FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WORKSPACE_MCP_PORT=8765 \
    WORKSPACE_MCP_HOST=0.0.0.0 \
    WORKSPACE_MCP_BASE_PATH=/app/tokens \
    MCP_ENABLE_OAUTH21=true \
    WORKSPACE_MCP_OAUTH_PROXY_STORAGE_BACKEND=disk \
    WORKSPACE_MCP_OAUTH_PROXY_DISK_DIRECTORY=/app/tokens/oauth-proxy

# The public OAuth URLs (WORKSPACE_EXTERNAL_URL, FASTMCP_SERVER_AUTH_GOOGLE_BASE_URL)
# and allowed client redirect URIs are set in docker-compose.yml from GWS_DOMAIN.

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Official taylorwilsdon/google_workspace_mcp package from PyPI
RUN pip install --upgrade pip && \
    pip install workspace-mcp

# Persistent OAuth token storage
RUN mkdir -p /app/tokens

# Server-side scope patch: workspace-mcp DCR drops `scope`, which makes the
# MCP SDK reject all Google scopes at token exchange
# ("Client was not registered with scope ..."). sitecustomize.py is imported
# automatically at Python startup from site-packages.
COPY sitecustomize.py /usr/local/lib/python3.12/site-packages/sitecustomize.py

EXPOSE 8765

# Only the requested services keeps the OAuth scope list to Gmail + Calendar + Tasks.
# Selected services: Gmail, Calendar, Tasks, Drive, Docs, Sheets, Slides, Forms, Contacts.
# Excluded by choice: chat, search (custom search), script (Apps Script).
# Override via COMPOSE command if you want more services:
#   --tool-tier core | extended | complete   (requires ALL APIs enabled incl. Chat/CSE/Script)
#   --tools gmail drive calendar tasks docs sheets slides forms contacts
CMD ["workspace-mcp", "--transport", "streamable-http", "--tools", "gmail", "drive", "calendar", "tasks", "docs", "sheets", "slides", "forms", "contacts"]
