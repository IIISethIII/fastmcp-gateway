"""Static bearer-token check in front of the MCP transports.

Plain ASGI middleware (not BaseHTTPMiddleware) so SSE and streamable-HTTP
responses keep streaming. Paths in `open_paths` (the health check) stay public.
"""
import hmac
import json


class BearerTokenMiddleware:
    def __init__(self, app, token: str, open_paths: tuple[str, ...] = ("/health",)):
        self.app = app
        self.expected = f"Bearer {token}".encode()
        self.open_paths = open_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.open_paths:
            return await self.app(scope, receive, send)

        auth = dict(scope["headers"]).get(b"authorization", b"")
        if hmac.compare_digest(auth, self.expected):
            return await self.app(scope, receive, send)

        body = json.dumps({"error": "unauthorized"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b"Bearer"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
