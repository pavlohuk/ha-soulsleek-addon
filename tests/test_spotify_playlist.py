import csv
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soulsleek_downloader" / "app"))
import main
import spotify_playlist as spotify

URL = "https://open.spotify.com/playlist/3trlrkWOU7GdTOF3ml2txg?si=test"


def song(title='Назва, "тест"'):
    return {"itemV2": {"data": {
        "__typename": "Track", "name": title,
        "artists": {"items": [{"profile": {"name": "Виконавець"}}]},
        "albumOfTrack": {"name": "Альбом"},
        "trackDuration": {"totalMilliseconds": 180500},
    }}}


def page(items, total):
    return {"data": {"playlistV2": {"name": "Playlist", "content": {"items": items, "totalCount": total}}}}


class SpotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / "playlist.csv"

    def export(self, pages):
        client = Mock()
        client.get_playlist_info.side_effect = pages
        count = spotify.export_playlist(URL, self.csv, client_factory=lambda _: client)
        return count, client

    def test_complete_pagination_and_csv_quoting(self):
        count, client = self.export([page([song()] * 100, 101), page([song("Last")], 101)])
        self.assertEqual(count, 101)
        self.assertEqual(client.get_playlist_info.call_args_list[1].kwargs["offset"], 100)
        with self.csv.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 101)
        self.assertEqual(rows[0]["title"], 'Назва, "тест"')
        self.assertEqual(rows[0]["length"], "180")
        self.assertEqual(rows[-1]["title"], "Last")

    def test_partial_or_changed_playlist_never_creates_csv(self):
        for pages in ([page([song()], 2), page([], 2)], [page([song()], 2), page([song()], 3)]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                self.export(pages)
            self.assertFalse(self.csv.exists())

    def test_private_empty_or_invalid_track_stops_import(self):
        invalid = song()
        del invalid["itemV2"]["data"]["name"]
        for response in ({"data": {"playlistV2": {"__typename": "NotFound"}}}, page([], 0), page([invalid], 1)):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.export([response])
            self.assertFalse(self.csv.exists())

    def test_non_track_is_counted_but_not_sent_to_soulseek(self):
        count, _ = self.export([page([song(), {"itemV2": {"data": {"__typename": "Episode"}}}], 2)])
        self.assertEqual(count, 1)

    def test_url_validation(self):
        self.assertEqual(spotify.playlist_id(URL), "3trlrkWOU7GdTOF3ml2txg")
        for url in ("https://evil.example/playlist/3trlrkWOU7GdTOF3ml2txg", "https://open.spotify.com/track/3trlrkWOU7GdTOF3ml2txg"):
            with self.assertRaises(ValueError):
                spotify.playlist_id(url)

    def test_worker_failure_does_not_return_a_stale_csv(self):
        self.csv.write_text("stale")
        with patch.object(spotify.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "lookup failed")):
            with self.assertRaises(RuntimeError):
                spotify.prepare_spotify_playlist(URL, str(self.root))

    def test_soulseek_startup_error_is_visible_and_password_redacted(self):
        process = Mock(stdout=io.StringIO("Error: Login failed for secret-password\n"), returncode=1)
        log = self.root / "download_log.txt"
        output = io.StringIO()
        with patch.object(main.os.path, "exists", return_value=True), \
                patch.object(main.subprocess, "Popen", return_value=process), patch("sys.stdout", output):
            success, _ = main.download_music("playlist.csv", str(self.root), str(log), "user", "secret-password", "mp3")
        self.assertFalse(success)
        self.assertIn("Login failed", output.getvalue())
        self.assertNotIn("secret-password", output.getvalue())
        self.assertNotIn("secret-password", log.read_text())

    def test_startup_failure_returns_failure_and_never_calls_youtube(self):
        args = ["main.py", "--playlist-url", URL, "--output-dir", str(self.root),
                "--user", "test", "--pass", "test", "--pref-format", "mp3"]
        with patch.object(sys, "argv", args), \
                patch.object(main, "prepare_spotify_playlist", return_value="playlist.csv"), \
                patch.object(main, "download_music", return_value=(False, [])), \
                patch.object(main, "download_missing_tracks") as youtube, \
                patch.object(main, "process_music") as process, patch("sys.stdout", io.StringIO()) as output:
            self.assertEqual(main.main(), 1)
            youtube.assert_not_called()
            process.assert_not_called()
            self.assertNotIn("Workflow complete", output.getvalue())

    def test_metadata_failure_never_starts_downloads(self):
        args = ["main.py", "--playlist-url", URL, "--output-dir", str(self.root),
                "--user", "test", "--pass", "test", "--pref-format", "mp3"]
        with patch.object(sys, "argv", args), \
                patch.object(main, "prepare_spotify_playlist", side_effect=RuntimeError("unavailable")), \
                patch.object(main, "download_music") as download:
            self.assertEqual(main.main(), 1)
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
