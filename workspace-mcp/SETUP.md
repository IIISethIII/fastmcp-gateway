# Google Workspace MCP — One-Time Setup Guide

## 1. Google Cloud Console
1. Go to https://console.cloud.google.com → create a project (any name).
2. **APIs & Services → Library**: enable **Gmail API**, **Google Calendar API**, **Tasks API**
   (plus Drive/Docs/Sheets/Slides/Forms/Contacts/Chat if you later widen the tool tier).
3. **OAuth consent screen**: External (or Internal if Workspace account), add your Google account as test user.
4. **Credentials → Create Credentials → OAuth client ID → Web application**.
   - Authorized redirect URIs:
     - `https://<GWS_DOMAIN>/oauth2callback`
5. Copy the **Client ID** and **Client Secret** into the stack's `.env`
   (`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`).

## 2. Start the stack
```
cd fastmcp-gateway   # the stack directory
docker compose up -d --build workspace-mcp fastmcp-gateway
```

## 3. Authorize (OAuth 2.1, one-time per account — disk-persistent)
The stack runs workspace-mcp in **OAuth 2.1 mode** (`MCP_ENABLE_OAUTH21=true`, disk
storage under `/app/tokens/oauth-proxy`). The gateway client authorizes itself as a
separate OAuth client; its client registration + tokens are persisted on disk under
`./workspace-tokens/mcp-client/` and **survive container restarts without re-consent**.

In OAuth 2.1 mode tools no longer take `user_google_email` — identity comes from the session.

Bootstrap (run once, e.g. after a fresh clone or scope change):

```bash
# 1. Make sure VS Code forwards port 8766 (the local OAuth callback server)
# 2. Run the bootstrap container:
docker run --rm --name gauth-bootstrap --network host --env-file .env \
  -v "$PWD":/stack \
  -v "$PWD"/workspace-tokens:/workspace-tokens \
  fastmcp-gateway-fastmcp-gateway python /stack/scripts/google_oauth_bootstrap.py
# 3. Extract the authorization URL (it is also at /tmp/url_only.txt after the run):
python3 -c "import re;flat=re.sub(r'\n\s+','',open('/tmp/bootstrap.log').read()).replace(' ','');print(re.search(r'https://\S+?/authorize\?\S+',flat).group(0).split('INFO')[0])"
# 4. Open the URL in a browser (requires https://<GWS_DOMAIN>/oauth2callback to be
#    registered as a redirect URI in Google Cloud) and complete the consent.
#    The callback lands on localhost:8766 and the bootstrap writes the tokens.
```

Notes / gotchas:
- The client registration (`client_id`) changes on every DCR run; **always use the freshly
  printed URL** — stale URLs from earlier runs fail with a state mismatch.
- If scopes or the registration change, delete
  `workspace-tokens/mcp-client/mcp-oauth-client-info/https:/<GWS_DOMAIN>/mcp/client_info.json`
  (and `mcp-oauth-token/.../tokens.json`) before rerunning.
- Files written by the bootstrap container are owned by root — `sudo chown -R "$USER:$USER" workspace-tokens/mcp-client` if needed.
- The shared volume MUST be mounted at the same in-container path (`/workspace-tokens/mcp-client`)
  in both the bootstrap and the gateway (FileTreeStore persists absolute paths).
- `sitecustomize.py` (built into both images) disables MCP-SDK client scope subset
  validation — workspace-mcp's DCR/metadata quirks otherwise reject valid Google scopes
  ("Client was not registered with scope ...") with an endless-loading browser.

Tip: set `USER_GOOGLE_EMAIL` in `.env` for tools that still accept the parameter.

## 4. Verify
- Gateway health: `curl http://mcp.local/health | jq .google_workspace`
- List Google tools through the gateway: any MCP client connected to `http://mcp.local/mcp`
  will see tools namespaced as `google_*` (e.g. `google_list_calendars`, `google_query_gmail`).

## 5. Changing the tool tier
Edit the `CMD` in `workspace-mcp/Dockerfile`:
- `--tool-tier core` — Gmail, Calendar, Drive, Tasks essentials (default)
- `--tool-tier extended` — core + management operations
- `--tool-tier complete` — everything (120+ tools; heavy for BM25 catalog)
- Or cherry-pick: `workspace-mcp --transport streamable-http --tools gmail calendar tasks`

Then rebuild: `docker compose up -d --build workspace-mcp fastmcp-gateway`

## Troubleshooting
- `docker logs workspace-mcp` — OAuth/credential errors surface here.
- `redirect_uri_mismatch` — the redirect URI in `.env` must exactly match one registered in Google Cloud.
- Gateway mounts fail gracefully: if `workspace-mcp` is unreachable, the gateway still serves
  SearXNG/Firecrawl/Context7 (`google_workspace.mounted: false` in `/health`).
