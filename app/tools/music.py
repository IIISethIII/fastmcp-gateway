"""Music playback for voice assistants: Plex + headless Plexamp first, Spotify as fallback.

Plex: search and play queues on the Plex server, playback commands straight to the
Plexamp player (Plex Companion API on :32500). Spotify: Web API with a user token
from scripts/spotify_auth.py, played on one Spotify Connect device.
"""
import asyncio
import json
import logging
import os
import random
import re
import time
from difflib import SequenceMatcher
from urllib.parse import urlsplit

import httpx
from fastmcp.server.lifespan import lifespan

from app.config import settings

logger = logging.getLogger("gateway.music")
# The resume watcher polls Plexamp every 20 s; keep those requests out of the log
logging.getLogger("httpx").addFilter(lambda r: "/player/timeline/poll" not in r.getMessage())

CLIENT_ID = "fastmcp-gateway-music"
KINDS = ("auto", "artist", "album", "track", "playlist", "station")
AUTO_ORDER = ("artist", "album", "playlist", "track")


class MusicError(Exception):
    """Expected failure (not found, backend offline) that triggers the fallback."""


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-zäöüß]", "", (text or "").lower())


def _similar(query: str, name: str) -> float:
    """Name similarity 0..1 that ignores case, spaces and punctuation."""
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if len(q) >= 4 and (q in n or n in q):
        return 0.9
    return SequenceMatcher(None, q, n).ratio()


def _pick(candidates: list[dict], query: str, kind: str, artist: str, threshold: float = 0.75) -> dict | None:
    """Best candidate of the wanted kind ({type, title, artist, ...}); auto prefers AUTO_ORDER on ties."""
    kinds = AUTO_ORDER if kind == "auto" else (kind,)
    best, best_score = None, 0.0
    for c in candidates:
        if c["type"] not in kinds:
            continue
        score = _similar(query, c["title"])
        if artist and c["type"] != "artist":
            score = min(score, _similar(artist, c.get("artist", "")))
        score -= kinds.index(c["type"]) * 0.01  # tie-break by kind priority
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= threshold else None


def _describe(item: dict) -> str:
    by = f" by {item['artist']}" if item.get("artist") and item["type"] != "artist" else ""
    return f"{item['type']} '{item['title']}'{by}"


# --------------------------------------------------------------------------- Plex

class Plex:
    name = "plex"

    def __init__(self):
        self._machine_id = None
        self._section = settings.plex_music_section or None
        self.last_playing = 0.0  # set by the watcher whenever Plexamp reports "playing"

    @property
    def enabled(self) -> bool:
        return bool(settings.plex_url and settings.plex_token and settings.plexamp_url and settings.plex_player_server_url)

    def _server(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.plex_url, timeout=10.0,
            headers={"X-Plex-Token": settings.plex_token, "Accept": "application/json",
                     "X-Plex-Client-Identifier": CLIENT_ID},
        )

    async def _player(self, path: str, **params) -> str:
        params.setdefault("type", "music")
        params["commandID"] = int(time.time() * 1000) % 2_000_000_000
        async with httpx.AsyncClient(base_url=settings.plexamp_url, timeout=8.0,
                                     headers={"X-Plex-Client-Identifier": CLIENT_ID}) as c:
            r = await c.get(path, params=params)
            r.raise_for_status()
            return r.text

    async def _ids(self) -> tuple[str, str]:
        if self._machine_id and self._section:
            return self._machine_id, self._section
        async with self._server() as c:
            self._machine_id = (await c.get("/identity")).json()["MediaContainer"]["machineIdentifier"]
            if not self._section:
                dirs = [d for d in (await c.get("/library/sections")).json()["MediaContainer"]["Directory"]
                        if d["type"] == "artist"]
                if not dirs:
                    raise MusicError("Plex has no music library")
                named = [d for d in dirs if d["title"].lower() in ("music", "musik")]
                self._section = (named or dirs)[0]["key"]
        return self._machine_id, self._section

    async def timeline(self) -> dict:
        xml = await self._player("/player/timeline/poll", wait=0)
        m = re.search(r'<Timeline[^>]*type="music"[^>]*>', xml)
        return dict(re.findall(r'(\w+)="([^"]*)"', m.group(0))) if m else {}

    async def stations(self) -> list[dict]:
        _, section = await self._ids()
        async with self._server() as c:
            hubs = (await c.get(f"/hubs/sections/{section}", params={"includeStations": 1})).json()
        return [{"type": "station", "title": m["title"], "key": m["key"]}
                for h in hubs["MediaContainer"].get("Hub", []) if h.get("hubIdentifier", "").startswith("music.stations")
                for m in h.get("Metadata", [])]

    async def _search(self, query: str) -> list[dict]:
        out = []
        async with self._server() as c:
            for q in dict.fromkeys((query, query.replace(" ", ""))):  # "annen may kantereit" -> one word
                r = await c.get("/library/search", params={"query": q, "searchTypes": "music", "limit": 15})
                for res in r.json()["MediaContainer"].get("SearchResult", []):
                    m = res["Metadata"]
                    if m.get("type") in ("artist", "album", "track"):
                        out.append({"type": m["type"], "title": m["title"], "key": f"/library/metadata/{m['ratingKey']}",
                                    "artist": m.get("parentTitle") if m["type"] == "album" else m.get("grandparentTitle", "")})
                if out:
                    break
            pls = (await c.get("/playlists", params={"playlistType": "audio"})).json()["MediaContainer"].get("Metadata", [])
            out += [{"type": "playlist", "title": p["title"], "key": f"/playlists/{p['ratingKey']}"} for p in pls]
        return out

    async def _play_key(self, key: str, shuffle: bool):
        machine_id, _ = await self._ids()
        async with self._server() as c:
            r = await c.post("/playQueues", params={
                "type": "audio", "shuffle": int(shuffle), "continuous": 0,
                "uri": f"server://{machine_id}/com.plexapp.plugins.library{key}"})
            r.raise_for_status()
            pq = r.json()["MediaContainer"]["playQueueID"]
        srv = urlsplit(settings.plex_player_server_url)
        await self._player("/player/playback/playMedia",
                           key=f"/playQueues/{pq}", containerKey=f"/playQueues/{pq}?own=1",
                           machineIdentifier=machine_id, protocol=srv.scheme, address=srv.hostname,
                           port=srv.port or (443 if srv.scheme == "https" else 32400), token=settings.plex_token)
        self.last_playing = time.time()

    async def play(self, query: str, kind: str, artist: str) -> str:
        if kind == "station" or (kind == "auto" and query):
            stations = await self.stations()
            hit = _pick(stations, query, "station", "", threshold=0.8)
            if hit:
                await self._play_key(hit["key"], shuffle=False)
                return f"Playing station '{hit['title']}' on Plex."
            if kind == "station":
                raise MusicError(f"No Plex station '{query}'. Stations: {', '.join(s['title'] for s in stations)}")
        hit = _pick(await self._search(query), query, kind, artist)
        if not hit:
            raise MusicError(f"'{query}' not found on Plex")
        await self._play_key(hit["key"], shuffle=hit["type"] in ("artist", "playlist"))
        return f"Playing {_describe(hit)} on Plex."

    async def play_default(self) -> str:
        tl = await self.timeline()
        if tl.get("state") == "playing":
            return "Plex is already playing; nothing changed (query was empty, so no specific music was requested)."
        recent = time.time() - self.last_playing < settings.music_resume_minutes * 60
        if tl.get("state") == "paused" and recent:
            await self._player("/player/playback/skipNext")  # also starts playback
            return "Resumed the previous Plex queue with its next track (query was empty, so no specific music was requested)."
        return await self.play(settings.music_default_station, "station", "")

    async def control(self, action: str) -> str:
        cmd = {"pause": "pause", "resume": "play", "next": "skipNext", "previous": "skipPrevious", "stop": "stop"}[action]
        await self._player(f"/player/playback/{cmd}")
        if action != "stop":  # it was playing until now (the watcher only polls every 20 s)
            self.last_playing = time.time()
        return f"Plex: {action}."

    async def get_volume(self) -> int:
        return int((await self.timeline()).get("volume") or 0)

    async def set_volume(self, level: int):
        await self._player("/player/playback/setParameters", volume=level)

    async def now_playing(self) -> dict | None:
        tl = await self.timeline()
        if tl.get("state") not in ("playing", "paused", "buffering") or not tl.get("ratingKey"):
            return None
        async with self._server() as c:
            m = (await c.get(f"/library/metadata/{tl['ratingKey']}")).json()["MediaContainer"]["Metadata"][0]
        return {"service": "plex", "state": tl["state"], "title": m.get("title"), "artist": m.get("grandparentTitle"),
                "album": m.get("parentTitle")}


# ------------------------------------------------------------------------ Spotify

class Spotify:
    name = "spotify"
    API = "https://api.spotify.com/v1"

    def __init__(self):
        self._token: dict | None = None

    @property
    def enabled(self) -> bool:
        return bool(settings.spotify_client_id and settings.spotify_client_secret and settings.spotify_device
                    and os.path.exists(settings.spotify_token_file))

    async def _access_token(self) -> str:
        if self._token is None:
            with open(settings.spotify_token_file) as f:
                self._token = json.load(f)
        if self._token.get("expires_at", 0) - 60 < time.time():
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post("https://accounts.spotify.com/api/token",
                                 data={"grant_type": "refresh_token", "refresh_token": self._token["refresh_token"]},
                                 auth=(settings.spotify_client_id, settings.spotify_client_secret))
            if r.status_code != 200:
                raise MusicError(f"Spotify token refresh failed ({r.status_code}); rerun scripts/spotify_auth.py")
            new = r.json()
            self._token.update(access_token=new["access_token"], expires_at=time.time() + new["expires_in"])
            if new.get("refresh_token"):
                self._token["refresh_token"] = new["refresh_token"]
            with open(settings.spotify_token_file, "w") as f:
                json.dump(self._token, f)
        return self._token["access_token"]

    async def _api(self, method: str, path: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(base_url=self.API, timeout=10.0,
                                     headers={"Authorization": f"Bearer {await self._access_token()}"}) as c:
            r = await c.request(method, path, **kwargs)
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = r.text[:200]
            raise MusicError(f"Spotify {method} {path}: {r.status_code} {msg}")
        return r

    async def _device_id(self) -> str:
        devices = (await self._api("GET", "/me/player/devices")).json()["devices"]
        for d in devices:
            if d["name"].lower() == settings.spotify_device.lower():
                return d["id"]
        raise MusicError(f"Spotify device '{settings.spotify_device}' is not available")

    async def _start(self, shuffle: bool, **body):
        device = await self._device_id()
        # Play first: Spotify refuses shuffle on an inactive device ("Restriction violated"), and
        # transferring playback beforehand made librespot open a new session whose state the
        # Web API no longer tracked (pause commands stopped reaching the device).
        await self._api("PUT", "/me/player/play", params={"device_id": device}, json=body)
        try:
            await self._api("PUT", "/me/player/shuffle", params={"state": str(shuffle).lower(), "device_id": device})
        except MusicError as e:
            logger.info("Spotify shuffle not set: %s", e)

    async def play(self, query: str, kind: str, artist: str) -> str:
        if kind == "station":
            raise MusicError("Spotify has no stations")
        types = AUTO_ORDER if kind == "auto" else (kind,)
        q = f"{query} artist:{artist}" if artist and kind in ("album", "track") else query
        data = (await self._api("GET", "/search", params={"q": q, "type": ",".join(types), "limit": 5})).json()
        candidates = []
        for t in types:
            for it in (data.get(f"{t}s") or {}).get("items") or []:
                if it:
                    candidates.append({"type": t, "title": it["name"], "uri": it["uri"],
                                       "artist": (it.get("artists") or [{}])[0].get("name", "")})
        # Spotify's ranking is good, so accept looser name matches than on Plex
        hit = _pick(candidates, query, kind, artist, threshold=0.6)
        if not hit:
            raise MusicError(f"'{query}' not found on Spotify")
        if hit["type"] == "track":
            await self._start(False, uris=[hit["uri"]])  # autoplay on the device continues with similar songs
        else:
            await self._start(hit["type"] in ("artist", "playlist"), context_uri=hit["uri"])
        return f"Playing {_describe(hit)} on Spotify."

    async def play_default(self) -> str:
        """Liked songs, shuffled. The Web API cannot play the collection itself, so queue a random slice."""
        total = (await self._api("GET", "/me/tracks", params={"limit": 1})).json()["total"]
        if not total:
            raise MusicError("No liked songs on Spotify")
        offset = random.randrange(max(1, total - 49))
        items = (await self._api("GET", "/me/tracks", params={"limit": 50, "offset": offset})).json()["items"]
        uris = [i["track"]["uri"] for i in items if i.get("track")]
        random.shuffle(uris)
        await self._start(False, uris=uris)
        return "Playing liked songs (shuffled) on Spotify."

    async def control(self, action: str) -> str:
        device = await self._device_id()
        method, path = {"pause": ("PUT", "/me/player/pause"), "stop": ("PUT", "/me/player/pause"),
                        "resume": ("PUT", "/me/player/play"), "next": ("POST", "/me/player/next"),
                        "previous": ("POST", "/me/player/previous")}[action]
        await self._api(method, path, params={"device_id": device})
        return f"Spotify: {action}."

    async def get_volume(self) -> int:
        r = await self._api("GET", "/me/player")
        return int(((r.json() if r.status_code == 200 else {}).get("device") or {}).get("volume_percent") or 0)

    async def set_volume(self, level: int):
        await self._api("PUT", "/me/player/volume", params={"volume_percent": level, "device_id": await self._device_id()})

    async def now_playing(self) -> dict | None:
        r = await self._api("GET", "/me/player")
        if r.status_code == 204:
            return None
        p = r.json()
        if (p.get("device") or {}).get("name", "").lower() != settings.spotify_device.lower() or not p.get("item"):
            return None
        it = p["item"]
        return {"service": "spotify", "state": "playing" if p.get("is_playing") else "paused", "title": it.get("name"),
                "artist": ", ".join(a["name"] for a in it.get("artists", [])), "album": (it.get("album") or {}).get("name")}


# ------------------------------------------------------------------- AudioControl

class AudioControl:
    """HiFiBerryOS AudioControl: control and status only, for sources like Bluetooth and AirPlay.

    Plexamp is not an AudioControl player, and its Spotify player (librespot) is left to
    the Spotify backend.
    """
    name = "audiocontrol"

    @property
    def enabled(self) -> bool:
        return bool(settings.audiocontrol_url)

    async def _call(self, tool: str, **args) -> dict:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(f"{settings.audiocontrol_url.rstrip('/')}/api/acr-webmcp/mcp",
                             json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": tool, "arguments": args}})
        result = r.json().get("result") or {}
        text = "".join(c.get("text", "") for c in result.get("content", []))
        if result.get("isError"):
            raise MusicError(f"AudioControl: {text[:200]}")
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}

    async def now_playing(self) -> dict | None:
        np = await self._call("now_playing")
        player = np.get("player") or {}
        # "unknown" (e.g. Bluetooth) keeps a stale song, so only trust real states
        if player.get("id") == "librespot" or np.get("state") not in ("playing", "paused"):
            return None
        song = np.get("song") or {}
        return {"service": player.get("name", "audiocontrol"), "state": np["state"], "title": song.get("title"),
                "artist": song.get("artist"), "album": song.get("album")}

    async def control(self, action: str) -> str:
        active = await self._call("player_active")
        if active.get("id") == "librespot":
            raise MusicError("the active AudioControl player is Spotify")
        cmd = {"resume": "play"}.get(action, action)
        await self._call("playback_command", player="active", command=cmd)
        return f"{active.get('name', 'AudioControl')}: {action}."

    async def get_volume(self) -> int:
        raise MusicError("volume of Bluetooth/AirPlay is set on the phone")

    async def set_volume(self, level: int):
        raise MusicError("volume of Bluetooth/AirPlay is set on the phone")


PLEX, SPOTIFY, AUDIOCONTROL = Plex(), Spotify(), AudioControl()
BACKENDS = {b.name: b for b in (PLEX, SPOTIFY)}


def _enabled_order() -> list:
    return [BACKENDS[n] for n in (s.strip() for s in settings.music_order.split(",")) if n in BACKENDS and BACKENDS[n].enabled]


def _control_backends() -> list:
    """Backends music_control looks at: the playable ones plus AudioControl."""
    return _enabled_order() + ([AUDIOCONTROL] if AUDIOCONTROL.enabled else [])


async def _silence_others(active):
    """All players share the sound card: pause whichever backend we are not starting."""
    for b in _control_backends():
        if b is active:
            continue
        try:
            np = await b.now_playing()
            if np and np["state"] == "playing":
                await b.control("pause")
        except Exception as e:
            logger.info("Could not pause %s: %s", b.name, e)


@lifespan
async def music_lifespan(server):
    """Record when Plexamp was last playing, for the resume window of music_play()."""
    async def watch():
        while True:
            try:
                if PLEX.enabled and (await PLEX.timeline()).get("state") == "playing":
                    PLEX.last_playing = time.time()
            except Exception:
                pass
            await asyncio.sleep(20)

    task = asyncio.create_task(watch())
    logger.info("Music backends: %s", ", ".join(b.name for b in _enabled_order()) or "none configured")
    try:
        yield {}
    finally:
        task.cancel()


# -------------------------------------------------------------------------- Tools

async def music_play(query: str = "", kind: str = "auto", artist: str = "", service: str = "auto") -> str:
    """Play music on the home speaker. Tries Plex (own library) first and falls back to Spotify.

    Args:
        query: What to play: an artist, album, song, playlist or Plex station name
            (e.g. 'Billie Eilish', 'Abbey Road', 'Library Radio'). ALWAYS put the
            requested music here, also an artist name.
            Leave EMPTY only for plain "play music" without anything specific: resumes
            with the next track if music was paused recently, otherwise starts the
            default station.
        kind: 'artist', 'album', 'track', 'playlist', 'station' or 'auto' (default).
            Set it whenever the request makes it clear; it avoids wrong matches.
        artist: Optional, ONLY to narrow an album or track search by its artist
            (query='Bad Guy', kind='track', artist='Billie Eilish').
        service: 'auto' (default: Plex, then Spotify), 'plex', or 'spotify' when the
            user explicitly asks for Spotify. To switch services ("switch to Plexamp"),
            pass that service with an empty query: the other player is paused first.

    Returns:
        A short status line, including whether the fallback was used.
    """
    kind = kind if kind in KINDS else "auto"
    if not query.strip() and artist.strip():
        # Models often put an artist request only into `artist`; that is a search, not "play music"
        query, artist = artist, ""
        if kind == "auto":
            kind = "artist"
    backends =_enabled_order() if service == "auto" else [b for b in _enabled_order() if b.name == service]
    if not backends:
        return f"Error: music service '{service}' is not configured."
    errors = []
    for b in backends:
        try:
            await _silence_others(b)
            msg = await (b.play(query, kind, artist) if query.strip() else b.play_default())
            return f"{'; '.join(errors)}. {msg}" if errors else msg
        except MusicError as e:
            errors.append(str(e))
        except Exception as e:
            logger.exception("music_play via %s failed", b.name)
            errors.append(f"{b.name} unavailable ({type(e).__name__})")
    return "Error: " + "; ".join(errors)


async def music_control(action: str, level: int | None = None) -> str:
    """Control or query the music on the home speaker (Plex, Spotify, or a phone
    streaming via Bluetooth/AirPlay). Use this for ALL pause/resume/skip/volume
    requests about music, not Home Assistant media players.

    Args:
        action: 'pause' (pauses everything playing), 'resume', 'next', 'previous',
            'stop', 'status' (what is playing), 'volume_up', 'volume_down' (10 steps),
            or 'volume' (set to `level`).
        level: Volume 0-100, only for action='volume'.

    Returns:
        A short status line.
    """
    states = []
    for b in _control_backends():
        try:
            np = await b.now_playing()
        except Exception as e:
            logger.info("now_playing via %s failed: %s", b.name, e)
            continue
        if np:
            states.append((b, np))
    if action == "status":
        if not states:
            return "Nothing is playing."
        return " | ".join(f"{np['service']} {np['state']}: '{np['title']}' by {np['artist']} ({np['album']})" for _, np in states)
    if action not in ("pause", "resume", "next", "previous", "stop", "volume_up", "volume_down", "volume"):
        return f"Error: unknown action '{action}'."
    playing = [b for b, np in states if np["state"] == "playing"]
    try:
        if action in ("pause", "stop") and playing:
            # Pause everything, so two players never keep sounding at once
            return " ".join([await b.control(action) for b in playing])
        if action.startswith("volume"):
            target = (playing or [b for b, _ in states] or [b for b in _enabled_order()] or [None])[0]
            if not target:
                return "Error: no music player configured."
            current = await target.get_volume()
            new = {"volume_up": current + 10, "volume_down": current - 10}.get(action, level if level is not None else current)
            new = max(0, min(100, int(new)))
            await target.set_volume(new)
            return f"{target.name} volume {current} -> {new}."
        # Prefer what is playing; for resume, what is paused
        want = "paused" if action == "resume" else "playing"
        target = next((b for b, np in states if np["state"] == want), None) or (states[0][0] if states else None)
        if not target and AUDIOCONTROL.enabled:
            # Bluetooth reports no reliable state; send the command to the active source anyway
            target = AUDIOCONTROL
        if not target:
            return "Nothing is playing."
        if action == "resume":
            await _silence_others(target)
        return await target.control(action)
    except Exception as e:
        return f"Error: {e}"
