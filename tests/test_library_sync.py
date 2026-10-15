import contextlib
import csv
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soulsleek_downloader" / "app"))
import download_recovery as recovery
import library
import main
import spotify_playlist as spotify
from mutagen.id3 import ID3

URL = "https://open.spotify.com/playlist/3trlrkWOU7GdTOF3ml2txg"
HEADER = ["filepath", "artist", "album", "title", "length", "tracktype", "state", "failurereason"]


def tone(path, codec, seconds=2):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:a", codec, str(path)], check=True)


def track(title, artist="Artist", length=2, **extra):
    return dict({"artist": artist, "title": title, "album": "Album", "length": length,
                 "uri": f"spotify:track:{title}"}, **extra)


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "media"
        self.downloads = self.output / "downloads"
        self.downloads.mkdir(parents=True)
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()
        self.addCleanup(self.silence.__exit__, None, None, None)

    def test_every_default_soulseek_format_is_converted_never_silently_deleted(self):
        (self.downloads / "user").mkdir()
        tone(self.downloads / "user" / "a.m4a", "aac")
        tone(self.downloads / "b.opus", "libopus")
        (self.downloads / "notes.txt").write_text("not audio")
        (self.downloads / "c.mp3.incomplete").write_bytes(b"partial")
        summary = main.process_music(str(self.downloads), str(self.output))
        self.assertEqual(sorted(summary["converted"]), ["a.mp3", "b.mp3"])
        self.assertEqual(sorted(p.name for p in self.output.glob("*.mp3")), ["a.mp3", "b.mp3"])
        # Converted sources, the empty folder and dead partial files go; unknown files stay.
        self.assertEqual([p.name for p in self.downloads.iterdir()], ["notes.txt"])

    def test_same_file_names_from_different_peers_never_overwrite(self):
        for peer in ("one", "two"):
            (self.downloads / peer).mkdir()
            tone(self.downloads / peer / "Intro.flac", "flac")
        (self.output / "Intro.mp3").write_bytes(b"user's own file")
        summary = main.process_music(str(self.downloads), str(self.output))
        self.assertEqual(sorted(summary["converted"]), ["Intro (2).mp3", "Intro.mp3"])
        self.assertEqual(len(list(self.output.glob("*.mp3"))), 2)
        # Without playlist metadata the old basename behaviour is kept.
        self.assertFalse(self.downloads.exists())

    def test_playlist_tags_and_cover_replace_peer_tags(self):
        source = self.downloads / "peer.flac"
        tone(source, "flac")
        meta = track("Real Title", artists=["Artist", "Guest"], album_artist="Artist",
                     track_number=3, disc_number=1, year="2024", cover_url="https://i.scdn.co/image/x")
        state = library.SyncState(self.root / "state.json", self.output)
        with patch.object(library, "fetch_cover", return_value=("image/jpeg", b"\xff\xd8jpeg")):
            summary = main.process_music(str(self.downloads), str(self.output),
                                         {os.path.realpath(source): meta}, state)
        self.assertEqual(summary["converted"], ["Artist - Real Title.mp3"])
        tags = ID3(self.output / "Artist - Real Title.mp3")
        self.assertEqual(tags.version[:2], (2, 3))
        self.assertEqual(str(tags["TIT2"]), "Real Title")
        self.assertEqual(str(tags["TPE1"]), "Artist, Guest")
        self.assertEqual(str(tags["TPE2"]), "Artist")
        self.assertEqual(str(tags["TRCK"]), "3")
        self.assertEqual(str(tags["TXXX:SPOTIFY_URI"]), "spotify:track:Real Title")
        self.assertEqual(tags.getall("APIC")[0].data, b"\xff\xd8jpeg")
        saved = json.loads((self.root / "state.json").read_text())
        self.assertEqual(saved["tracks"]["spotify:track:Real Title"]["file"], "Artist - Real Title.mp3")

    def test_failed_conversion_keeps_only_that_source(self):
        tone(self.downloads / "good.flac", "flac")
        (self.downloads / "broken.flac").write_bytes(b"not audio")
        summary = main.process_music(str(self.downloads), str(self.output))
        self.assertEqual(summary["converted"], ["good.mp3"])
        self.assertEqual([p.name for p in self.downloads.iterdir()], ["broken.flac"])
        self.assertEqual([p.name for p in self.output.iterdir() if p.is_file()], ["good.mp3"])


class SyncTests(unittest.TestCase):
    """End-to-end playlist runs with the network and Soulseek mocked."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "media"
        self.output.mkdir()
        self.state_dir = self.root / "data"
        self.tracks = [track("One"), track("Two")]
        self.requested = []

    def prepare(self, url, directory):
        destination = Path(directory, "playlist.csv")
        Path(directory, "playlist.json").write_text(json.dumps({"tracks": self.tracks}))
        library.write_csv(destination, self.tracks)
        return str(destination)

    def download(self, playlist, download_dir, log, user, password, fmt, index_file, concurrent_downloads):
        with open(playlist, newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.requested.append([row["title"] for row in rows])
        with open(index_file, "w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            for row in rows:
                path = Path(download_dir, f"peer-{row['title']}.flac")
                path.write_bytes(b"audio")
                writer.writerow([str(path), row["artist"], row["album"], row["title"], row["length"], 0, 1, 0])
        return True, []

    def fake_normalize(self, file_path, script, converted_dir, output_name=None, track=None, target_lufs=-14):
        Path(converted_dir, output_name).write_bytes(b"mp3")
        return {"status": "success", "file": file_path, "output": output_name}

    def run_sync(self):
        argv = ["main.py", "--playlist-url", URL, "--output-dir", str(self.output), "--user", "u",
                "--pref-format", "mp3", "--state-dir", str(self.state_dir), "--no-youtube-fallback"]
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {"SOULSEEK_PASS": "secret"}), \
                patch.object(main, "prepare_spotify_playlist", side_effect=self.prepare), \
                patch.object(main, "download_music", side_effect=self.download), \
                patch.object(main, "normalize_single_file", side_effect=self.fake_normalize), \
                patch.object(main, "write_tags"), contextlib.redirect_stdout(io.StringIO()):
            return main.main()

    def test_second_run_downloads_only_new_or_deleted_tracks(self):
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.requested, [["One", "Two"]])
        self.assertEqual(sorted(p.name for p in self.output.glob("*.mp3")), ["Artist - One.mp3", "Artist - Two.mp3"])

        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(len(self.requested), 1, "nothing new: Soulseek must not run")

        self.tracks.append(track("Three"))
        (self.output / "Artist - One.mp3").unlink()
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.requested[-1], ["One", "Three"])
        self.assertEqual(sorted(p.name for p in self.output.glob("*.mp3")),
                         ["Artist - One.mp3", "Artist - Three.mp3", "Artist - Two.mp3"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_upgrade_adopts_matching_files_from_earlier_versions(self):
        old = self.output / "01 - one (peer name).mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2",
                        "-metadata", "artist=ARTIST", "-metadata", "title=one", str(old)], check=True)
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.requested, [["Two"]])
        self.assertTrue(old.exists())


class CredentialTests(unittest.TestCase):
    def test_password_is_passed_in_a_private_config_not_argv(self):
        captured = {}

        def popen(command, **kwargs):
            config = command[command.index("-c") + 1]
            captured["command"] = command
            captured["config"] = Path(config).read_text()
            captured["mode"] = stat.S_IMODE(os.stat(config).st_mode)
            return Mock(stdout=io.StringIO(""), returncode=0)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(main.os.path, "exists", return_value=True), \
                patch.object(main.subprocess, "Popen", side_effect=popen), \
                patch.object(main, "configure_file_limit"), contextlib.redirect_stdout(io.StringIO()):
            main.download_music("playlist.csv", directory, str(Path(directory, "log")), "user", 'p"a=ss ', "mp3")
        self.assertNotIn('p"a=ss ', " ".join(captured["command"]))
        self.assertNotIn("--pass", captured["command"])
        self.assertIn('pass = "p"a=ss "', captured["config"])
        self.assertEqual(captured["mode"], 0o600)


class MetadataTests(unittest.TestCase):
    def test_spotify_metadata_includes_tags_and_largest_cover(self):
        item = {"itemV2": {"data": {
            "__typename": "Track", "name": "Song", "uri": "spotify:track:1", "trackNumber": 4, "discNumber": 1,
            "artists": {"items": [{"profile": {"name": "Main"}}, {"profile": {"name": "Feat"}}]},
            "albumOfTrack": {
                "name": "Record", "date": {"isoString": "2019-05-01T00:00:00Z"},
                "artists": {"items": [{"profile": {"name": "Main"}}]},
                "coverArt": {"sources": [{"url": "https://i.scdn.co/small", "width": 64},
                                         {"url": "https://i.scdn.co/large", "width": 640}]},
            },
            "trackDuration": {"totalMilliseconds": 200000},
        }}}
        client = Mock()
        client.get_playlist_info.return_value = {"data": {"playlistV2": {
            "name": "P", "content": {"items": [item], "totalCount": 1}}}}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            spotify.export_playlist(URL, Path(directory, "playlist.csv"), client_factory=lambda _: client)
            metadata = library.load_metadata(Path(directory, "playlist.json"))
            header = Path(directory, "playlist.csv").read_text().splitlines()[0]
        self.assertEqual(header, "artist,title,album,length")
        meta = metadata[("Main", "Song", "Record", "200")]
        self.assertEqual(meta["artists"], ["Main", "Feat"])
        self.assertEqual((meta["year"], meta["track_number"], meta["album_artist"]), ("2019", 4, "Main"))
        self.assertEqual(meta["cover_url"], "https://i.scdn.co/large")

    def test_crash_recovery_keeps_paths_for_tagging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playlist, index = root / "playlist.csv", root / "index.csv"
            playlist.write_text("artist,title,album,length\nA,Done,Al,180\nA,Tagged,Al,180\n")
            index.write_text(",".join(HEADER) + "\n/m/done.mp3,A,Al,Done,180,0,1,0\n")
            (root / "tagged.flac").touch()
            audio = Mock(wraps={"artist": ["A"], "title": ["Tagged"], "album": ["Al"]},
                         tags=True, info=Mock(length=180))
            with patch.object(recovery, "File", return_value=audio), contextlib.redirect_stdout(io.StringIO()):
                recovery.rebuild_crashed_index(playlist, index, root)
            paths = main.index_downloads(index, {})
        self.assertEqual(sorted(Path(p).name for p in paths), ["done.mp3", "tagged.flac"])


if __name__ == "__main__":
    unittest.main()
