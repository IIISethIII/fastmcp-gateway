#!/usr/bin/env python3
"""One-time OAuth 2.1 consent bootstrap for the Google Workspace MCP server.

Run ON THE DOCKER HOST from the stack directory with the gateway's Docker image. The OAuth client
registers as a "native" app, so the redirect MUST be a loopback URL:

    docker run --rm --network host --env-file .env \
      -v "$PWD":/stack \
      -v "$PWD"/workspace-tokens:/workspace-tokens \
      fastmcp-gateway-fastmcp-gateway python /stack/scripts/google_oauth_bootstrap.py

1. The script binds the OAuth callback on <docker-host>:8766.
2. Make <docker-host>:8766 reachable as localhost:8766 from the machine running the
   browser — VS Code Remote auto-forwards port 8766 (check the Ports panel),
   otherwise `ssh -L 8766:localhost:8766 <docker-host>`.
3. Open the printed Google authorization URL in the desktop browser and approve.
4. Tokens are written to /stack/workspace-tokens/mcp-client and are picked up
   automatically by the fastmcp-gateway container (same FileTreeStore layout).

The FastMCP OAuth client refreshes tokens automatically afterwards; only
rerun this if the Google refresh token itself is revoked/expired.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/stack")

from fastmcp import Client
from fastmcp.client.auth import OAuth
from fastmcp.client.transports import StreamableHttpTransport
from key_value.aio.stores.filetree import FileTreeStore

from app.google_scopes import GOOGLE_SCOPES, ScopedOAuth

MCP_URL = os.getenv("MCP_URL") or os.environ["GOOGLE_WORKSPACE_URL"]
TOKEN_DIR = os.getenv("TOKEN_DIR", "/workspace-tokens/mcp-client")
CALLBACK_HOST = os.getenv("CALLBACK_HOST", "localhost")
CALLBACK_PORT = int(os.getenv("CALLBACK_PORT", "8766"))


async def main() -> None:
    token_store = FileTreeStore(data_directory=TOKEN_DIR)
    oauth = ScopedOAuth(
        mcp_url=MCP_URL,
        scopes=GOOGLE_SCOPES,
        token_storage=token_store,
        client_name="FastMCP Gateway Bootstrap",
        callback_host=CALLBACK_HOST,
        callback_port=CALLBACK_PORT,
        callback_timeout=600.0,
    )
    transport = StreamableHttpTransport(MCP_URL, auth=oauth)
    print(f"Connecting to {MCP_URL} ...", flush=True)
    print("If the browser does not open automatically, copy the "
          "authorization URL printed below and open it manually.", flush=True)
    async with Client(transport) as client:
        tools = await client.list_tools()
        google_tools = [t.name for t in tools]
        print(f"\nSUCCESS — authenticated, {len(google_tools)} tools visible:")
        for name in google_tools:
            print(" -", name)
    print(f"\nTokens persisted under {TOKEN_DIR}. The gateway will reuse them.")


if __name__ == "__main__":
    asyncio.run(main())
