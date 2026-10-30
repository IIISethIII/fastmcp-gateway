FROM node:20-slim
LABEL description="Vinted MCP sub-server for the FastMCP gateway"
# Pinned version; playwright optional deps are skipped (browser mode not needed)
RUN npm install --global --omit=dev --omit=optional @googlarz/vinted-client@1.6.3 \
    && npm cache clean --force
ENV VINTED_MCP_TRANSPORT=http \
    VINTED_MCP_HOST=0.0.0.0 \
    VINTED_MCP_PORT=3001 \
    VINTED_MCP_PATH=/mcp
USER node
EXPOSE 3001
CMD ["vinted-mcp"]
