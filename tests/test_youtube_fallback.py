import contextlib
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "soulsleek_downloader" / "app"))
import main
import youtube_fallback as fallback
from mutagen.flac import FLAC


HEADER = ["filepath", "artist", "album", "title", "length", "tracktype", "state", "failurereason"]


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "downloads"
        self.output.mkdir()
        self.index = self.root / "index.csv"
        self.log = self.root / "download_log.txt"
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()
        self.addCleanup(self.silence.__exit__, None, None, None)

    def write_index(self, rows):
        with self.index.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(HEADER)
            writer.writerows(rows)

    def failed(self, title="Song", artist="Artist", reason="3"):
        return ["", artist, "Album", title, "180", "0", "2", reason]

    def run_fallback(self):
        return fallback.download_missing_tracks(self.index, self.output, self.log)

    def test_only_final_track_failures_are_retried_and_duplicates_deduplicated(self):
        failed = self.failed('Song, "quoted"', "Український виконавець")
        self.write_index([
            failed, failed, self.failed("Retries", reason="2"), self.failed("Transfers", reason="4"),
            ["x.mp3", "A", "", "Downloaded", "180", "0", "1", "0"],
            ["x.mp3", "A", "", "Existing", "180", "0", "3", "0"],
            ["", "A", "", "Pending", "180", "0", "0", "0"],
            ["", "A", "", "Album", "180", "1", "2", "3"],
            self.failed("Other error", reason="5"),
        ])
        tracks = fallback.missing_tracks(self.index)
        self.assertEqual([track["title"] for track in tracks], ['Song, "quoted"', "Retries", "Transfers"])

    def test_search_filters_duration_live_missing_and_invalid_ids(self):
        entries = [
            None, {"id": "bad", "duration": 180},
            {"id": "longvideo01", "duration": 700},
            {"id": "livevideo01", "duration": 180, "is_live": True},
            {"id": "unknown0001", "duration": None},
            {"id": "upcoming001", "duration": 180, "live_status": "is_upcoming"},
            {"id": "validvideo1", "duration": 188},
        ]
        self.assertEqual(list(fallback.matching_candidates(entries, 180)), ["validvideo1"])

    def test_no_failures_or_missing_index_never_call_youtube(self):
        with patch.object(fallback.subprocess, "run") as run:
            self.assertEqual(self.run_fallback(), (0, 0))
            self.write_index([["x.mp3", "A", "", "OK", "180", "0", "1", "0"]])
            self.assertEqual(self.run_fallback(), (0, 0))
            run.assert_not_called()

    def test_search_timeout_and_invalid_json_do_not_stop_remaining_tracks(self):
        self.write_index([self.failed("One"), self.failed("Two")])
        with patch.object(fallback.subprocess, "run", side_effect=[
            subprocess.TimeoutExpired("yt-dlp", 120),
            subprocess.CompletedProcess([], 0, "not JSON", ""),
        ]) as run:
            self.assertEqual(self.run_fallback(), (0, 2))
            self.assertEqual(run.call_count, 2)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_recovers_valid_candidate_after_failure_and_preserves_tags(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("FFmpeg required for synthetic FLAC fixture")
        fixture = self.root / "fixture.flac"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:a", "flac", str(fixture),
        ], check=True)
        title = 'Пісня / "назва"; $(touch forbidden) ' + "ї" * 180
        self.write_index([self.failed(title)])
        existing = self.output / "existing.mp3"
        existing.write_bytes(b"keep Soulseek file")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            self.assertIsInstance(command, list)
            if "--dump-single-json" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps({"entries": [
                    {"id": "firstvideo1", "duration": 180},
                    {"id": "validvideo1", "duration": 180},
                ]}), "")
            target = Path(command[command.index("--output") + 1].replace("%(ext)s", "flac"))
            if command[-1].endswith("firstvideo1"):
                target.write_bytes(b"partial")
                return subprocess.CompletedProcess(command, 1, "failed candidate", "")
            shutil.copyfile(fixture, target)
            return subprocess.CompletedProcess(command, 0, "downloaded", "")

        with patch.object(fallback.subprocess, "run", side_effect=fake_run):
            self.assertEqual(self.run_fallback(), (1, 0))
        files = list(self.output.glob("*.flac"))
        self.assertEqual(len(files), 1)
        self.assertLess(len(files[0].name.encode()), 255)
        tags = FLAC(files[0])
        self.assertEqual(tags["title"], [title])
        self.assertEqual(tags["artist"], ["Artist"])
        self.assertEqual(tags["album"], ["Album"])
        self.assertIn("validvideo1", tags["comment"][0])
        self.assertEqual(existing.read_bytes(), b"keep Soulseek file")
        self.assertFalse(any(path.is_dir() for path in self.output.iterdir()))
        self.assertIn("YouTube recovered", self.log.read_text())

        # Verify that a recovered FLAC really passes through the existing MP3 pipeline.
        script = Path(main.__file__).with_name("normalize.sh")
        converted = self.root / "converted"
        converted.mkdir()
        converted_result = main.normalize_single_file(str(files[0]), str(script), str(converted))
        self.assertEqual(converted_result["status"], "success", converted_result)
        mp3 = next(converted.glob("*.mp3"))
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate",
            "-of", "json", str(mp3),
        ], capture_output=True, text=True, check=True)
        stream = json.loads(probe.stdout)["streams"][0]
        self.assertEqual(stream["codec_name"], "mp3")
        self.assertEqual(stream["sample_rate"], "44100")

    def test_zero_exit_without_audio_is_still_failure(self):
        self.write_index([self.failed()])
        search = json.dumps({"entries": [{"id": "validvideo1", "duration": 180}]})
        with patch.object(fallback.subprocess, "run", side_effect=[
            subprocess.CompletedProcess([], 0, search, ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]):
            self.assertEqual(self.run_fallback(), (0, 1))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_normalization_failure_keeps_original_downloads(self):
        source = self.output / "recovered.flac"
        source.write_bytes(b"keep for retry")
        with patch.object(main, "normalize_single_file", return_value={
            "status": "failed", "file": str(source), "error": "conversion failed",
        }):
            summary = main.process_music(str(self.output))
        self.assertEqual(source.read_bytes(), b"keep for retry")
        self.assertEqual(len(summary["failed"]), 1)

    def test_cli_switch_disables_fallback_and_default_enables_it(self):
        for flags, expected in (([], True), (["--no-youtube-fallback"], False)):
            argv = ["main.py", "--playlist-url", "https://open.spotify.com/playlist/test",
                    "--output-dir", str(self.root), "--user", "test", "--pass", "test", "--pref-format", "mp3"] + flags
            with self.subTest(flags=flags), patch.object(sys, "argv", argv), \
                    patch.object(main, "prepare_spotify_playlist", return_value="playlist.csv"), \
                    patch.object(main, "download_music", return_value=(True, [])), \
                    patch.object(main, "download_missing_tracks") as recover, \
                    patch.object(main, "process_music") as process:
                main.main()
                self.assertEqual(recover.called, expected)
                process.assert_called_once()

    def test_soulseek_failure_with_recovered_file_still_runs_processing(self):
        argv = ["main.py", "--playlist-url", "https://open.spotify.com/playlist/test",
                "--output-dir", str(self.root), "--user", "test", "--pass", "test", "--pref-format", "mp3"]

        def recover(index, directory, log, recovered_files):
            Path(directory, "recovered.flac").write_bytes(b"audio")
            return 1, 0

        def download(*args, index_file, concurrent_downloads):
            Path(index_file).write_text("test index")
            return False, ["missing"]

        with patch.object(sys, "argv", argv), \
                patch.object(main, "prepare_spotify_playlist", return_value="playlist.csv"), \
                patch.object(main, "download_music", side_effect=download), \
                patch.object(main, "download_missing_tracks", side_effect=recover), \
                patch.object(main, "process_music") as process:
            self.assertEqual(main.main(), 1)  # The Soulseek failure is still reported.
            self.assertEqual(process.call_args.args[0], str(self.output))


if __name__ == "__main__":
    unittest.main()
