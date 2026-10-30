#!/usr/bin/env python3
"""One-time Spotify login for the gateway's music tools.

Run ON THE DOCKER HOST from the stack directory, standard library only:

    python3 scripts/spotify_auth.py

1. Reads SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET from .env. The Spotify app
   needs the redirect URI http://127.0.0.1:8888/callback.
2. Prints the authorization URL. Open it in the desktop browser and approve.
3. The browser is redirected to 127.0.0.1:8888. VS Code Remote forwards that
   port to this script (check the Ports panel). If the page does not load,
   copy the full URL from the address bar and paste it here instead.
4. Writes music-tokens/spotify.json (mode 0600). The gateway refreshes the
   access token itself afterwards; only rerun this if the login is revoked.
"""
import base64
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

STACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(STACK, "music-tokens", "spotify.json")
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing user-library-read playlist-read-private"


def read_env():
    env = {}
    with open(os.path.join(STACK, ".env")) as f:
        for line in f:
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    return env


def main():
    env = read_env()
    client_id, secret = env.get("SPOTIFY_CLIENT_ID"), env.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not secret:
        sys.exit("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET missing in .env")

    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": SCOPES, "state": state})
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            result["url"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Spotify login received, you can close this tab.".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 8888), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    print("Open this URL in your browser and approve:\n\n" + url + "\n")
    print("Waiting for the redirect... (or paste the redirected URL and press Enter)")

    def read_paste():
        line = sys.stdin.readline().strip()
        if line:
            result.setdefault("url", line)
    threading.Thread(target=read_paste, daemon=True).start()
    while "url" not in result:
        time.sleep(0.3)

    query = urllib.parse.parse_qs(urllib.parse.urlsplit(result["url"]).query)
    if query.get("state", [""])[0] != state:
        sys.exit("State mismatch, aborting.")
    if "code" not in query:
        sys.exit(f"No code in redirect: {query.get('error', ['unknown error'])[0]}")

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({"grant_type": "authorization_code", "code": query["code"][0],
                                     "redirect_uri": REDIRECT}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()})
    with urllib.request.urlopen(req) as r:
        tok = json.load(r)

    os.makedirs(os.path.dirname(TOKEN_FILE), mode=0o700, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
                   "expires_at": time.time() + tok["expires_in"]}, f)
    print(f"Saved {TOKEN_FILE}. Restart the gateway: docker compose up -d --build fastmcp-gateway")


if __name__ == "__main__":
    main()
