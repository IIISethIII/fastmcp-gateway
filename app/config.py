import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    fastmcp_host: str = "0.0.0.0"
    fastmcp_port: int = 8000
    log_level: str = "INFO"
    # Bearer token required on /mcp, /sse and /messages; empty = no auth
    gateway_token: str = ""

    # SearXNG
    searxng_url: str = "http://searxng:8080"

    # Firecrawl
    firecrawl_api_key: str = ""
    firecrawl_api_url: str = "https://api.firecrawl.dev"

    # Context7
    context7_api_key: str = ""
    context7_api_url: str = "https://api.context7.com"

    # Shared Brain
    shared_brain_path: str = "/app/shared_brain"

    # Google Workspace (workspace-mcp proxied sub-server)
    google_workspace_enabled: bool = True
    # Must match FASTMCP_SERVER_AUTH_GOOGLE_BASE_URL resource path (see workspace-mcp Dockerfile)
    google_workspace_url: str = ""     # e.g. https://gws.example.com/mcp; empty = not mounted
    # FileTreeStore for the gateway's OAuth 2.1 client tokens (shared volume with workspace-mcp).
    # Must match the bootstrap's TOKEN_DIR path exactly (see scripts/google_oauth_bootstrap.py).
    google_token_store_path: str = "/workspace-tokens/mcp-client"

    # Home Assistant (ha-mcp proxied sub-server, plain HTTP, token via HOMEASSISTANT_TOKEN)
    ha_mcp_enabled: bool = True
    ha_mcp_url: str = "http://ha-mcp:8086/mcp"

    # Google Health (google-health-mcp proxied sub-server, plain HTTP on the
    # private `health-internal` compose network — NO public exposure, see
    # google-health-mcp/SETUP.md. Namespace: fitbit -> tools fitbit_google_health_*)
    google_health_mcp_enabled: bool = True
    google_health_mcp_url: str = "http://google-health-mcp:3000/mcp"

    # Email (mcp-email-server proxied sub-server, plain HTTP, IMAP-only read)
    email_mcp_enabled: bool = True
    email_mcp_url: str = "http://email-mcp:8087/mcp"

    # Vinted (vinted-mcp proxied sub-server, HTTP + bearer token, namespace: vinted)
    vinted_mcp_enabled: bool = True
    vinted_mcp_url: str = "http://vinted-mcp:3001/mcp"
    vinted_mcp_token: str = ""

    # Kleinanzeigen (kleinanzeigen-mcp proxied sub-server, plain HTTP, namespace: kleinanzeigen)
    kleinanzeigen_mcp_enabled: bool = True
    kleinanzeigen_mcp_url: str = "http://kleinanzeigen-mcp:8020/mcp"

    # Browser (Playwright MCP proxied sub-server, plain HTTP on the private
    # `browser-internal` network, namespace: browser -> tools browser_*)
    browser_mcp_enabled: bool = True
    browser_mcp_url: str = "http://browser-mcp:8931/mcp"

    # Music (music_play / music_control): Plex + headless Plexamp first, Spotify as
    # fallback. Each backend is off while its settings are empty.
    plex_url: str = ""                 # Plex server as the gateway reaches it, e.g. http://plex:32400
    plex_token: str = ""
    plex_music_section: str = ""       # library section id; empty = artist library titled Music/Musik, else the first one
    plexamp_url: str = ""              # headless Plexamp player, e.g. http://192.168.x.x:32500
    plex_player_server_url: str = ""   # Plex server as the PLAYER reaches it, e.g. https://plex.example.com:443
    music_default_station: str = "Library Radio"
    music_resume_minutes: int = 30     # "play music" resumes (next track) if Plexamp played within this window
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_token_file: str = "/music-tokens/spotify.json"  # written by scripts/spotify_auth.py
    spotify_device: str = ""           # Spotify Connect device name, e.g. hifiberry
    music_order: str = "plex,spotify"  # fallback order when no service is named
    audiocontrol_url: str = ""         # HiFiBerryOS AudioControl (Bluetooth/AirPlay control), e.g. http://192.168.x.x

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
