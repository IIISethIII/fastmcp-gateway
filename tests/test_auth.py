"""Tests for app/auth.py (no network).

Run inside the gateway container, see tests/test_music.py.
"""
import unittest

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.auth import BearerTokenMiddleware


async def ok(request):
    return PlainTextResponse("ok")


inner = Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"]), Route("/health", ok)])
client = TestClient(BearerTokenMiddleware(inner, "secret"))


class BearerTokenTest(unittest.TestCase):
    def test_valid_token_passes(self):
        r = client.post("/mcp", headers={"Authorization": "Bearer secret"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "ok")

    def test_missing_token_rejected(self):
        r = client.post("/mcp")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers["www-authenticate"], "Bearer")

    def test_wrong_token_rejected(self):
        for value in ("Bearer wrong", "secret", "Bearer secretX", "Basic secret"):
            r = client.post("/mcp", headers={"Authorization": value})
            self.assertEqual(r.status_code, 401, value)

    def test_health_is_public(self):
        self.assertEqual(client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
