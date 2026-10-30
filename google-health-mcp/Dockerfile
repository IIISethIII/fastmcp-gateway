# Build stage: node-gyp toolchain needed because better-sqlite3 (dependency of
# google-health-mcp-unofficial) ships no prebuilt binary for Node 20.x on glibc
FROM node:20-slim AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
RUN npm install --global --omit=dev google-health-mcp-unofficial@0.7.8 \
    && npm cache clean --force

# Final stage: slim runtime — only the built node_modules carry over
FROM node:20-slim
LABEL description="Google Health (Fitbit) MCP sub-server for the FastMCP gateway"
COPY --from=build /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=build /usr/local/bin /usr/local/bin
RUN sed -i 's/include_granted_scopes: "true"/include_granted_scopes: "false"/g' /usr/local/lib/node_modules/google-health-mcp-unofficial/dist/services/google-health-client.js
ENV GOOGLE_HEALTH_MCP_TRANSPORT=http \
    GOOGLE_HEALTH_MCP_PORT=3000 \
    GOOGLE_HEALTH_MCP_HOST=0.0.0.0 \
    GOOGLE_HEALTH_HOME=/app/data
RUN mkdir -p /app/data && chown -R node:node /app/data
USER node
EXPOSE 3000
CMD ["google-health-mcp-server", "--http"]
