# Google Health MCP — Setup & Operations

Sub-server `google-health-mcp` (google-health-mcp-unofficial@0.7.8, pinned),
proxied by the FastMCP Central Gateway under the namespace `fitbit`.
All tools appear as `fitbit_google_health_*` (e.g.
`fitbit_google_health_daily_summary`, `fitbit_google_health_sleep_summary`,
`fitbit_google_health_activity_summary`, `fitbit_google_health_connection_status`,
`fitbit_google_health_privacy_audit`, `fitbit_google_health_get_auth_url`,
`fitbit_google_health_exchange_code`).

## Security posture (upstream docs/authorization.md)
- HTTP mode has NO Bearer auth → NEVER on traefik-proxy, only a loopback-only port publish (127.0.0.1:3000) for the OAuth flow.
- Reachable ONLY via the dedicated `health-internal` compose network (gateway only).
- Tokens: `~/.google-health-mcp/tokens.json` (chmod 0600) in container-only
  volume `health-mcp-data`. NOT shared with workspace-mcp / gateway token stores.
- Scope preset `full` = DEFAULT_SCOPES (all readonly: profile, settings,
  activity_and_fitness, health_metrics_and_measurements, sleep, nutrition).
  No write scopes except opt-in nutrition.writeonly (not enabled).
- Reuses the SAME Google OAuth client as the gateway's gmail/workspace-mcp
  (GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET from stack .env).

## GCP console steps (user — OAuth client already exists for gmail)
In the SAME Google Cloud project as the gmail OAuth client:
1. Enable the Google Health API: `developers.google.com/health` → enable
   (API id: googlehealth.googleapis.com).
2. OAuth consent screen → add the 6 readonly scopes (DEFAULT_SCOPES):
   - googlehealth.profile.readonly
   - googlehealth.settings.readonly
   - googlehealth.activity_and_fitness.readonly
   - googlehealth.health_metrics_and_measurements.readonly
   - googlehealth.sleep.readonly
   - googlehealth.nutrition.readonly
3. OAuth client (Web application) → Authorized redirect URIs → add:
   `http://127.0.0.1:3000/callback`

## Deploy
```bash
cd fastmcp-gateway   # the stack directory
docker compose build google-health-mcp
docker compose up -d google-health-mcp
docker compose restart fastmcp-gateway
```

## Headless OAuth (Docker host without a browser, browser on another device)
```bash
# 1. Get the auth URL (tool call through the gateway, or CLI):
ssh -L 3000:127.0.0.1:3000 <user>@<docker-host>   # port 3000 is published on the host's loopback only
# Call tool: fitbit_google_health_get_auth_url  → copy the URL, open in browser
# (approval fails to load 127.0.0.1:3000/callback — that is expected)
# 2. Exchange: call tool fitbit_google_health_exchange_code with the full
#    redirect URL (or CLI `auth --code "<url>"` inside the container).
# 3. Verify: fitbit_google_health_connection_status → fitbit_google_health_daily_summary
```

## Verify
- Gateway health: `curl -s http://mcp.local/health | python3 -m json.tool`
  → "google_health": {"mounted": true, "url": "http://google-health-mcp:3000/mcp"}
- Container-only isolation check:
  `docker inspect google-health-mcp --format '{{json .NetworkSettings.Networks}}'`
  → must contain ONLY `fastmcp-gateway_health-internal`.
