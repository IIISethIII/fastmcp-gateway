FROM python:3.12-slim
LABEL description="Kleinanzeigen MCP sub-server for the FastMCP gateway"
ARG KLEINANZEIGEN_MCP_REF=b25842042fad2c2342ac19374026a143083529b5
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && git clone https://github.com/Samxel/kleinanzeigen-mcp /app \
    && git -C /app checkout ${KLEINANZEIGEN_MCP_REF} \
    && rm -rf /app/.git /var/lib/apt/lists/* \
    && apt-get purge -y git && apt-get autoremove -y
WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt \
    # upstream binds 127.0.0.1; make it reachable on the docker network
    && sed -i 's/^HOST = "127.0.0.1"/HOST = "0.0.0.0"/' main.py
RUN useradd -r -u 1000 app
USER app
EXPOSE 8020
CMD ["python", "main.py"]
