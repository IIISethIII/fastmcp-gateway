"""Tests for app/tools/music.py with fake backends (no network).

Run inside the gateway container (the image only contains app/):

    docker cp tests fastmcp-gateway:/tmp/gwtests
    docker exec -w /app fastmcp-gateway python -m unittest discover -s /tmp/gwtests -v
"""
import asyncio
import time
import unittest
from unittest import mock

from app.tools import music
from app.tools.music import MusicError, _pick, _similar


class FakeBackend:
    def __init__(self, name, state=None, volume=30, play_error=None):
        self.name = name
        self.enabled = True
        self.state = state  # None, "playing" or "paused"
        self.volume = volume
        self.play_error = play_error
        self.calls = []

    async def now_playing(self):
        if not self.state:
            return None
        return {"service": self.name, "state": self.state, "title": "t", "artist": "a", "album": "b"}

    async def control(self, action):
        self.calls.append(("control", action))
        if action in ("pause", "stop"):
            self.state = "paused"
        elif action == "resume":
            self.state = "playing"
        return f"{self.name}: {action}."

    async def play(self, query, kind, artist):
        self.calls.append(("play", query, kind, artist))
        if self.play_error:
            raise MusicError(self.play_error)
        self.state = "playing"
        return f"Playing {query} on {self.name}."

    async def play_default(self):
        self.calls.append(("play_default",))
        if self.play_error:
            raise MusicError(self.play_error)
        self.state = "playing"
        return f"Default on {self.name}."

    async def get_volume(self):
        return self.volume

    async def set_volume(self, level):
        self.calls.append(("set_volume", level))
        self.volume = level


def run(coro):
    return asyncio.run(coro)


class Backends:
    """Patch the module to use fake Plex/Spotify and an optional fake AudioControl."""

    def __init__(self, plex, spotify, audiocontrol=None):
        ac = audiocontrol or FakeBackend("audiocontrol")
        ac.enabled = audiocontrol is not None
        self.patches = [
            mock.patch.object(music, "BACKENDS", {"plex": plex, "spotify": spotify}),
            mock.patch.object(music, "AUDIOCONTROL", ac),
            mock.patch.object(music.settings, "music_order", "plex,spotify"),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


class Matching(unittest.TestCase):
    def test_spaces_and_case_are_ignored(self):
        self.assertEqual(_similar("annen may kantereit", "AnnenMayKantereit"), 1.0)
        self.assertGreaterEqual(_similar("beatles", "The Beatles"), 0.9)

    def test_kind_filter_rejects_a_track_named_like_the_artist(self):
        # Plex returns a track titled "Taylor Swift" by another artist
        candidates = [{"type": "track", "title": "Taylor Swift", "artist": "Someone"}]
        self.assertIsNone(_pick(candidates, "Taylor Swift", "artist", ""))

    def test_auto_prefers_artist_over_album_with_same_name(self):
        candidates = [{"type": "album", "title": "The Beatles"}, {"type": "artist", "title": "The Beatles"}]
        self.assertEqual(_pick(candidates, "beatles", "auto", "")["type"], "artist")

    def test_artist_filter_for_tracks(self):
        candidates = [{"type": "track", "title": "Bad Guy", "artist": "Other"},
                      {"type": "track", "title": "Bad Guy", "artist": "Billie Eilish"}]
        self.assertEqual(_pick(candidates, "Bad Guy", "track", "Billie Eilish")["artist"], "Billie Eilish")


class MusicPlay(unittest.TestCase):
    def test_artist_only_is_a_search_not_play_music(self):
        # Bug 2026-10-30: music_play(artist='Billie Eilish') resumed the old queue
        plex, spotify = FakeBackend("plex"), FakeBackend("spotify")
        with Backends(plex, spotify):
            run(music.music_play(artist="Billie Eilish", kind="artist"))
        self.assertEqual(plex.calls, [("play", "Billie Eilish", "artist", "")])

    def test_artist_only_with_auto_kind_becomes_artist(self):
        plex, spotify = FakeBackend("plex"), FakeBackend("spotify")
        with Backends(plex, spotify):
            run(music.music_play(artist="Billie Eilish"))
        self.assertEqual(plex.calls[0][2], "artist")

    def test_empty_query_plays_default(self):
        plex, spotify = FakeBackend("plex"), FakeBackend("spotify")
        with Backends(plex, spotify):
            run(music.music_play())
        self.assertEqual(plex.calls, [("play_default",)])

    def test_falls_back_to_spotify_and_says_so(self):
        plex, spotify = FakeBackend("plex", play_error="'X' not found on Plex"), FakeBackend("spotify")
        with Backends(plex, spotify):
            msg = run(music.music_play("X", "artist"))
        self.assertIn("not found on Plex", msg)
        self.assertIn("on spotify", msg)

    def test_explicit_service_skips_the_others(self):
        plex, spotify = FakeBackend("plex"), FakeBackend("spotify")
        with Backends(plex, spotify):
            run(music.music_play("X", service="spotify"))
        self.assertFalse([c for c in plex.calls if c[0] == "play"])
        self.assertEqual(spotify.calls[0][0], "play")

    def test_all_failing_returns_error(self):
        plex = FakeBackend("plex", play_error="nope plex")
        spotify = FakeBackend("spotify", play_error="nope spotify")
        with Backends(plex, spotify):
            msg = run(music.music_play("X"))
        self.assertTrue(msg.startswith("Error:"))

    def test_unknown_service_is_an_error(self):
        with Backends(FakeBackend("plex"), FakeBackend("spotify")):
            self.assertTrue(run(music.music_play("X", service="tidal")).startswith("Error:"))

    def test_starting_plex_pauses_playing_spotify(self):
        # Bug 2026-10-30: switching to Plexamp left Spotify playing
        plex, spotify = FakeBackend("plex", state="paused"), FakeBackend("spotify", state="playing")
        with Backends(plex, spotify):
            run(music.music_play(service="plex"))
        self.assertIn(("control", "pause"), spotify.calls)
        self.assertEqual(plex.state, "playing")

    def test_starting_music_pauses_bluetooth(self):
        plex, spotify = FakeBackend("plex"), FakeBackend("spotify")
        bt = FakeBackend("bluetooth", state="playing")
        with Backends(plex, spotify, bt):
            run(music.music_play("X"))
        self.assertIn(("control", "pause"), bt.calls)


class MusicControl(unittest.TestCase):
    def test_pause_pauses_every_playing_player(self):
        plex, spotify = FakeBackend("plex", state="playing"), FakeBackend("spotify", state="playing")
        with Backends(plex, spotify):
            run(music.music_control("pause"))
        self.assertEqual((plex.state, spotify.state), ("paused", "paused"))

    def test_resume_pauses_the_others_first(self):
        plex, spotify = FakeBackend("plex", state="paused"), FakeBackend("spotify", state="playing")
        with Backends(plex, spotify):
            run(music.music_control("resume"))
        self.assertEqual((plex.state, spotify.state), ("playing", "paused"))

    def test_volume_targets_the_playing_player(self):
        plex, spotify = FakeBackend("plex", state="paused"), FakeBackend("spotify", state="playing", volume=50)
        with Backends(plex, spotify):
            msg = run(music.music_control("volume_up"))
        self.assertEqual(spotify.volume, 60)
        self.assertEqual(plex.calls, [])
        self.assertIn("50 -> 60", msg)

    def test_volume_is_clamped(self):
        plex = FakeBackend("plex", state="playing", volume=95)
        with Backends(plex, FakeBackend("spotify")):
            run(music.music_control("volume_up"))
            self.assertEqual(plex.volume, 100)
            run(music.music_control("volume", level=-5))
            self.assertEqual(plex.volume, 0)

    def test_volume_with_nothing_playing_uses_first_backend(self):
        plex = FakeBackend("plex")
        with Backends(plex, FakeBackend("spotify")):
            run(music.music_control("volume", level=25))
        self.assertEqual(plex.volume, 25)

    def test_status_lists_all_players(self):
        with Backends(FakeBackend("plex", state="playing"), FakeBackend("spotify", state="paused")):
            msg = run(music.music_control("status"))
        self.assertIn("plex playing", msg)
        self.assertIn("spotify paused", msg)

    def test_nothing_playing(self):
        with Backends(FakeBackend("plex"), FakeBackend("spotify")):
            self.assertEqual(run(music.music_control("next")), "Nothing is playing.")

    def test_bluetooth_gets_commands_when_nothing_else_plays(self):
        bt = FakeBackend("bluetooth")
        with Backends(FakeBackend("plex"), FakeBackend("spotify"), bt):
            run(music.music_control("pause"))
        self.assertEqual(bt.calls, [("control", "pause")])

    def test_unknown_action(self):
        with Backends(FakeBackend("plex"), FakeBackend("spotify")):
            self.assertTrue(run(music.music_control("louder")).startswith("Error:"))


class PlexDefault(unittest.TestCase):
    """Plex.play_default: resume within the window, otherwise the default station."""

    def setUp(self):
        self.plex = music.Plex()
        self.player_calls = []
        self.played = []

        async def player(path, **params):
            self.player_calls.append(path)
            return ""

        async def play(query, kind, artist):
            self.played.append((query, kind))
            return "station"

        self.plex._player = player
        self.plex.play = play

    def with_state(self, state):
        async def timeline():
            return {"state": state}
        self.plex.timeline = timeline

    def test_already_playing_changes_nothing_and_says_so(self):
        self.with_state("playing")
        msg = run(self.plex.play_default())
        self.assertIn("nothing changed", msg)
        self.assertEqual((self.player_calls, self.played), ([], []))

    def test_recent_pause_skips_to_next_track(self):
        self.with_state("paused")
        self.plex.last_playing = time.time() - 60
        run(self.plex.play_default())
        self.assertEqual(self.player_calls, ["/player/playback/skipNext"])

    def test_old_pause_starts_default_station(self):
        self.with_state("paused")
        self.plex.last_playing = time.time() - (music.settings.music_resume_minutes + 1) * 60
        run(self.plex.play_default())
        self.assertEqual(self.played, [(music.settings.music_default_station, "station")])

    def test_stopped_starts_default_station(self):
        self.with_state("stopped")
        self.plex.last_playing = time.time()
        run(self.plex.play_default())
        self.assertEqual(len(self.played), 1)


if __name__ == "__main__":
    unittest.main()
