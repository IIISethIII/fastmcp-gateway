import logging
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from fastmcp import FastMCP
from fastmcp.server.http import create_streamable_http_app, create_sse_app
from fastmcp.server.transforms.search.bm25 import BM25SearchTransform

from app.auth import BearerTokenMiddleware
from app.config import settings
from app.tools import (
    searxng_search,
    firecrawl_scrape,
    context7_docs,
    music_play,
    music_control,
    music_lifespan,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gateway.server")

# Initialize FastMCP Server
mcp = FastMCP(
    name="Central-Gateway",
    instructions="Central MCP Gateway providing Web Search (SearXNG), Web Scraping (Firecrawl), "
                 "Documentation Retrieval (Context7), and Google Workspace (Gmail, Calendar, Tasks) "
                 "via a proxied workspace-mcp sub-server. Also proxies a Home Assistant MCP "
                 "sub-server under the ha_ prefix, an IMAP Email sub-server under the mail_ prefix, "
                 "a Vinted marketplace sub-server under the vinted_ prefix, "
                 "a Kleinanzeigen marketplace sub-server under the kleinanzeigen_ prefix, "
                 "and a headless Playwright browser sub-server under the browser_ prefix. "
                 "music_play / music_control play music on the home speaker (Plex first, Spotify fallback). "
                 "Only the core tools are listed directly. Find all others (ha_*, vinted_*, kleinanzeigen_*, "
                 "browser_*, further fitbit_* and google_* tools) with search_tools and run them with call_tool.",
    lifespan=music_lifespan,
)

# Register all Gateway Tools
mcp.tool()(searxng_search)
mcp.tool()(firecrawl_scrape)
mcp.tool()(context7_docs)
mcp.tool()(music_play)
mcp.tool()(music_control)

# Mount the Google Workspace MCP server (workspace-mcp) under the `google_` prefix.
# Uses FastMCP proxy composition: tools appear as google_<tool_name>.
#
# Authentication: workspace-mcp runs in OAuth 2.1 mode. The gateway authenticates
# with FastMCP's OAuth client (PKCE + dynamic client registration). Tokens are
# persisted in a FileTreeStore on the shared ./workspace-tokens volume
# (/app/google-client-tokens), so the consent done once via
# scripts/google_oauth_bootstrap.py survives gateway AND workspace-mcp restarts.
# If no valid tokens exist, run the bootstrap script (see workspace-mcp/SETUP.md).
google_workspace_mounted = False
if settings.google_workspace_enabled and settings.google_workspace_url:
    try:
        from fastmcp.client.auth import OAuth
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy
        from key_value.aio.stores.filetree import FileTreeStore

        token_store = FileTreeStore(
            data_directory=settings.google_token_store_path
        )
        from app.google_scopes import GOOGLE_SCOPES, ScopedOAuth

        oauth_provider = ScopedOAuth(
            mcp_url=settings.google_workspace_url,
            scopes=GOOGLE_SCOPES,
            token_storage=token_store,
            client_name="FastMCP Central Gateway",
        )
        transport = StreamableHttpTransport(
            settings.google_workspace_url, auth=oauth_provider
        )
        google_proxy = create_proxy(transport, name="Google-Workspace")
        mcp.mount(google_proxy, namespace="google")
        google_workspace_mounted = True
        logger.info("Google Workspace sub-server mounted from %s (namespace: google, OAuth 2.1 client)", settings.google_workspace_url)
    except Exception:
        logger.exception("Failed to mount Google Workspace sub-server at %s; continuing without it", settings.google_workspace_url)



# Mount the Home Assistant MCP server (ha-mcp) under the `ha` prefix.
# Uses FastMCP proxy composition: tools appear as ha_<tool_name>.
#
# Authentication: ha-mcp holds the Home Assistant long-lived access token itself
# (HOMEASSISTANT_URL / HOMEASSISTANT_TOKEN in .env); the gateway connects without
# OAuth, like any unauthenticated HTTP MCP client. If HA credentials are missing
# or ha-mcp is unreachable, we log and continue without the HA tools.
ha_mcp_mounted = False
if settings.ha_mcp_enabled:
    try:
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy

        transport = StreamableHttpTransport(settings.ha_mcp_url)
        ha_proxy = create_proxy(transport, name="Home-Assistant")
        # NOTE: no namespace — ha-mcp tools already carry the native `ha_` prefix
        mcp.mount(ha_proxy)
        ha_mcp_mounted = True
        logger.info("Home Assistant sub-server mounted from %s (namespace: ha)", settings.ha_mcp_url)
    except Exception:
        logger.exception("Failed to mount Home Assistant sub-server at %s; continuing without it", settings.ha_mcp_url)

# Mount the mcp-email-server sub-server (email-mcp) under the `mail` namespace.
# Uses FastMCP proxy composition: tools appear as mail_<tool_name> because the
# email sub-server exposes generic tool names (list_emails_metadata, ...).
# mode="legacy": mcp-email-server 1.6.2 rejects the gateway's default (modern)
# handshake with "400 Missing session ID" -> 0 tools listed. Same fix as fitbit.
# IMAP-only and read-only per the bound-mounted legacy TOML config
# (./email-mcp/config.toml, allowed_mutations = []); account secrets live in that
# config file only. If the sub-server is unreachable, we log and continue without
# the mail_ tools.
email_mcp_mounted = False
if settings.email_mcp_enabled:
    try:
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy

        transport = StreamableHttpTransport(settings.email_mcp_url)
        email_proxy = create_proxy(transport, name="Email-IMAP", mode="legacy")
        mcp.mount(email_proxy, namespace="mail")
        email_mcp_mounted = True
        logger.info("Email sub-server mounted from %s (namespace: mail)", settings.email_mcp_url)
    except Exception:
        logger.exception("Failed to mount Email sub-server at %s; continuing without it", settings.email_mcp_url)



# Mount the google-health-mcp sub-server (google-health-mcp-unofficial) under
# the `fitbit` namespace. Uses FastMCP proxy composition: tools appear as
# fitbit_google_health_* (native names carry google_health_; the fitbit namespace
# keeps them unambiguous vs the workspace-mcp google_ prefix and clear for agents).
# ⚠️ SECURITY: upstream HTTP mode has NO Bearer auth -> the sub-server is NEVER
# on traefik-proxy and NEVER LAN-reachable; it is reachable ONLY via the
# dedicated `health-internal` compose network joined by this gateway, plus a
# LOOPBACK-ONLY host publish (127.0.0.1:3000) for the headless OAuth flow (see
# google-health-mcp/SETUP.md). Explicit readonly scope URLs in compose env (the
# server does NOT expand scope presets from GOOGLE_HEALTH_SCOPES); reuses the
# SAME Google OAuth client as the gateway's gmail/workspace-mcp (GOOGLE_OAUTH_* env).
# Tokens live in the container-only volume `health-mcp-data` (HOME=/app/data,
# token file chmod 0600), isolated from the gateway/workspace token stores.
# ⚠️ PROTOCOL: the Node sub-server (google-health-mcp-unofficial@0.7.8) only
# speaks up to MCP protocol version 2025-11-25 and REJECTS newer versions with
# "Bad Request: Unsupported protocol version". The gateway (FastMCP 4.0.11)
# defaults to mirroring the front connection's era (2026-07-28) -> every proxied
# tool call failed. Pin the backend era with create_proxy(mode="2025-11-25").
google_health_mcp_mounted = False
if settings.google_health_mcp_enabled:
    try:
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy

        transport = StreamableHttpTransport(settings.google_health_mcp_url)
        # mode="legacy": pin the backend era to legacy MCP handshake.
        # The Node sub-server (google-health-mcp-unofficial@0.7.8 / MCP SDK 1.32.1)
        # only speaks up to protocol version 2025-11-25 and rejects modern (2026-07-28+)
        # single-exchange requests.
        google_health_proxy = create_proxy(
            transport, name="Google-Health-Fitbit", mode="legacy"
        )
        mcp.mount(google_health_proxy, namespace="fitbit")
        google_health_mcp_mounted = True
        logger.info("Google Health sub-server mounted from %s (namespace: fitbit)", settings.google_health_mcp_url)
    except Exception:
        logger.exception("Failed to mount Google Health sub-server at %s; continuing without it", settings.google_health_mcp_url)

# Mount the Vinted MCP sub-server (@googlarz/vinted-client) under the `vinted`
# namespace: tools appear as vinted_search_items, vinted_get_item, ...
# Authenticated with a bearer token (VINTED_MCP_TOKEN in .env). Uses the legacy
# handshake like the other Node sub-servers (MCP SDK 1.32.x).
vinted_mcp_mounted = False
if settings.vinted_mcp_enabled:
    try:
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy

        transport = StreamableHttpTransport(
            settings.vinted_mcp_url,
            headers={"Authorization": f"Bearer {settings.vinted_mcp_token}"},
        )
        vinted_proxy = create_proxy(transport, name="Vinted", mode="legacy")
        mcp.mount(vinted_proxy, namespace="vinted")
        vinted_mcp_mounted = True
        logger.info("Vinted sub-server mounted from %s (namespace: vinted)", settings.vinted_mcp_url)
    except Exception:
        logger.exception("Failed to mount Vinted sub-server at %s; continuing without it", settings.vinted_mcp_url)

# Mount the Kleinanzeigen MCP sub-server (Samxel/kleinanzeigen-mcp) under the
# `kleinanzeigen` namespace: tools appear as kleinanzeigen_search_kleinanzeigen, ...
# No auth upstream: reachable only from the gateway over the internal docker network.
kleinanzeigen_mcp_mounted = False
if settings.kleinanzeigen_mcp_enabled:
    try:
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy

        transport = StreamableHttpTransport(settings.kleinanzeigen_mcp_url)
        kleinanzeigen_proxy = create_proxy(transport, name="Kleinanzeigen")
        mcp.mount(kleinanzeigen_proxy, namespace="kleinanzeigen")
        kleinanzeigen_mcp_mounted = True
        logger.info("Kleinanzeigen sub-server mounted from %s (namespace: kleinanzeigen)", settings.kleinanzeigen_mcp_url)
    except Exception:
        logger.exception("Failed to mount Kleinanzeigen sub-server at %s; continuing without it", settings.kleinanzeigen_mcp_url)

# Mount the Playwright MCP browser sub-server (browser-mcp): tools appear as
# browser_navigate, browser_snapshot, ... (native prefix, no namespace needed).
# No auth upstream: the sub-server is reachable ONLY via the private
# `browser-internal` compose network (gateway + browser-mcp), and its egress to
# the LAN is dropped by scripts/browser-firewall.sh. Sessions are isolated.
browser_mcp_mounted = False
if settings.browser_mcp_enabled:
    try:
        from fastmcp.client.transports import StreamableHttpTransport
        from fastmcp.server import create_proxy

        transport = StreamableHttpTransport(settings.browser_mcp_url)
        # mode="legacy": Playwright MCP (Node, MCP SDK 1.x) rejects the gateway's
        # default modern handshake ("Server not initialized"), like the other Node sub-servers.
        browser_proxy = create_proxy(transport, name="Browser", mode="legacy")
        # NOTE: no namespace — Playwright MCP tools already carry the native `browser_` prefix
        mcp.mount(browser_proxy)
        browser_mcp_mounted = True
        logger.info("Browser sub-server mounted from %s (native browser_ prefix)", settings.browser_mcp_url)
    except Exception:
        logger.exception("Failed to mount Browser sub-server at %s; continuing without it", settings.browser_mcp_url)

# Attach FastMCP's native BM25SearchTransform
# Keeps core tools visible while dynamically indexing the catalog
bm25_transform = BM25SearchTransform(
    max_results=5,
    always_visible=[
        "searxng_search",
        "firecrawl_scrape",
        "context7_docs",
        "music_play",
        "music_control",
        "search_tools",
        "call_tool",
        # Google Workspace (mounted from workspace-mcp under google_ prefix)
        "google_search_gmail_messages",
        "google_get_gmail_message_content",
        "google_get_gmail_messages_content_batch",
        "google_send_gmail_message",
        "google_list_calendars",
        "google_get_events",
        "google_manage_event",
        "google_list_tasks",
        "google_get_task",
        "google_manage_task",
        # Email (mounted from email-mcp under mail_ prefix)
        "mail_list_available_accounts",
        "mail_list_mailboxes",
        "mail_list_emails_metadata",
        "mail_get_emails_content",
        # Google Health (mounted from google-health-mcp under fitbit_ prefix).
        # NOTE: names must match the sub-server's actual tools (prefixed fitbit_):
        # there are NO sleep_summary/activity_summary/list_paired_devices tools.
        # Only the summaries are listed; raw data, profile and setup tools
        # (get_auth_url, exchange_code, ...) are found via search_tools.
        "fitbit_google_health_daily_summary",
        "fitbit_google_health_weekly_summary",
        "fitbit_google_health_wellness_context",
    ],
)
mcp.add_transform(bm25_transform)

# Build dual-transport Starlette application:
# 1. Streamable-HTTP on /mcp (for modern clients like DeepSeek Harness, pi-ai, DSH)
# 2. SSE on /sse & /messages (for legacy SSE clients like Cline, Claude Desktop, OpenClaw)
app_streamable = create_streamable_http_app(
    server=mcp,
    streamable_http_path="/mcp",
    host_origin_protection=False,
    allowed_hosts=["*"],
    allowed_origins=["*"],
)

app_sse = create_sse_app(
    server=mcp,
    message_path="/messages",
    sse_path="/sse",
)


# Health check endpoint for Traefik / observability
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "healthy",
        "service": "FastMCP Central Gateway",
        "transports": {
            "streamable-http": "/mcp",
            "sse": "/sse",
            "messages": "/messages",
        },
        "tools": [
            "searxng_search",
            "firecrawl_scrape",
            "context7_docs",
            "music_play",
            "music_control",
        ],
        "endpoints": {
            "streamable_http": "/mcp",
            "sse": "/sse",
            "messages": "/messages",
            "health": "/health",
        },
        "google_workspace": {
            "mounted": google_workspace_mounted,
            "url": settings.google_workspace_url,
        },
        "home_assistant": {
            "mounted": ha_mcp_mounted,
            "url": settings.ha_mcp_url,
        },
        "email": {
            "mounted": email_mcp_mounted,
            "url": settings.email_mcp_url,
        },
        "google_health": {
            "mounted": google_health_mcp_mounted,
            "url": settings.google_health_mcp_url,
        },
        "vinted": {
            "mounted": vinted_mcp_mounted,
            "url": settings.vinted_mcp_url,
        },
        "kleinanzeigen": {
            "mounted": kleinanzeigen_mcp_mounted,
            "url": settings.kleinanzeigen_mcp_url,
        },
        "browser": {
            "mounted": browser_mcp_mounted,
            "url": settings.browser_mcp_url,
        },
    })


# Combine routes into a single ASGI application sharing the server lifespan
combined_routes = list(app_streamable.routes) + list(app_sse.routes) + [
    Route("/health", health_check, methods=["GET"])
]

app = Starlette(
    routes=combined_routes,
    lifespan=app_streamable.router.lifespan_context,
)

# Optional bearer token for all MCP transports (/health stays public).
# Empty GATEWAY_TOKEN = no auth, only acceptable on a trusted network.
if settings.gateway_token:
    app = BearerTokenMiddleware(app, settings.gateway_token)
    logger.info("Bearer token auth enabled for /mcp, /sse and /messages")
else:
    logger.warning("GATEWAY_TOKEN is not set: the MCP endpoints accept unauthenticated requests")

if __name__ == "__main__":
    logger.info(
        f"Starting FastMCP Central Gateway on {settings.fastmcp_host}:{settings.fastmcp_port} "
        f"[Transports: streamable-http at /mcp, sse at /sse]"
    )
    uvicorn.run(
        app,
        host=settings.fastmcp_host,
        port=settings.fastmcp_port,
        log_level=settings.log_level.lower(),
        lifespan="on",
    )
