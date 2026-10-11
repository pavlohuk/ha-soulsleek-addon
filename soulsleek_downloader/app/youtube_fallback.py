"""Recover failed Soulseek tracks using YouTube, before audio normalization."""

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from mutagen import MutagenError
from mutagen.flac import FLAC


def missing_tracks(index_path):
    """Read the structured index written by the pinned slsk-batchdl 2.6.0.

    Only retry exhausted downloads / no suitable file, not authentication or
    metadata failures. A fresh index is supplied for every invocation.
    """
    with open(index_path, encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"artist", "title", "length", "tracktype", "state", "failurereason"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Unrecognized Soulseek index format")
        tracks = []
        seen = set()
        for row in reader:
            if row["tracktype"] != "0" or row["state"] != "2":
                continue
            if row["failurereason"] not in {"2", "3", "4"}:
                continue
            artist, title = ((row.get(key) or "").strip() for key in ("artist", "title"))
            key = (artist, title, row.get("album", ""), row["length"])
            if not title or key in seen:
                continue
            seen.add(key)
            try:
                duration = float(row["length"])
            except (TypeError, ValueError):
                duration = -1
            tracks.append({"artist": artist, "title": title, "album": row.get("album") or "", "duration": duration})
        return tracks


def matching_candidates(entries, duration):
    """Keep ordinary YouTube videos close to the playlist track's duration."""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = entry.get("id", "")
        if not isinstance(video_id, str) or not re.fullmatch(r"[\w-]{11}", video_id, re.ASCII):
            continue
        if entry.get("is_live") or entry.get("live_status") == "is_upcoming":
            continue
        actual = entry.get("duration")
        if not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual <= 0:
            continue
        if math.isfinite(duration) and duration > 0 and abs(actual - duration) > max(10, duration * 0.05):
            continue
        yield video_id


def download_missing_tracks(index_path, output_dir, log_file):
    """Return (recovered, unresolved) counts. Errors do not discard Soulseek files."""
    try:
        tracks = missing_tracks(index_path)
    except (OSError, ValueError, csv.Error) as error:
        print(f"⚠️ YouTube fallback skipped: {error}", flush=True)
        return 0, 0
    if not tracks:
        return 0, 0

    print(f"▶️ Searching YouTube for {len(tracks)} missing tracks...", flush=True)
    base_command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config",
        "--js-runtimes", "node", "--no-playlist", "--socket-timeout", "20",
        "--retries", "2", "--fragment-retries", "2", "--no-progress",
    ]
    recovered = 0
    with open(log_file, "a", encoding="utf-8") as log:
        for track in tracks:
            label = " - ".join(value for value in (track["artist"], track["title"]) if value)
            print(f"   YouTube search: {label}", flush=True)
            log.write(f"\nYouTube search: {label}\n")
            try:
                search = subprocess.run(
                    base_command + ["--dump-single-json", "--skip-download", "--ignore-errors", f"ytsearch5:{label} audio"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
                )
                log.write(search.stderr or "")
                if search.returncode:
                    raise RuntimeError(f"YouTube search exited with {search.returncode}")
                result = json.loads(search.stdout)
                if not isinstance(result, dict):
                    raise ValueError("Unexpected YouTube search response")
                candidates = list(matching_candidates(result.get("entries") or [], track["duration"]))
                if not candidates:
                    raise RuntimeError("No YouTube result matches the track duration")

                downloaded = False
                for video_id in candidates:
                    # Isolate each attempt: partial/failed files never reach normalization.
                    with tempfile.TemporaryDirectory(prefix="youtube-", dir=output_dir) as staging:
                        try:
                            result = subprocess.run(
                                base_command + [
                                    "--format", "bestaudio/best", "--extract-audio", "--audio-format", "flac",
                                    "--output", os.path.join(staging, "audio.%(ext)s"),
                                    f"https://www.youtube.com/watch?v={video_id}",
                                ],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
                            )
                        except subprocess.TimeoutExpired:
                            log.write(f"YouTube download timed out: {video_id}\n")
                            continue
                        log.write(result.stdout or "")
                        audio = Path(staging, "audio.flac")
                        if result.returncode or not audio.is_file() or audio.stat().st_size == 0:
                            continue
                        # Keep the Spotify identity; FLAC is only a lossless intermediate
                        # before the existing single MP3 encode / loudness normalization.
                        try:
                            tags = FLAC(audio)
                            tags["artist"] = track["artist"]
                            tags["title"] = track["title"]
                            tags["album"] = track["album"]
                            tags["comment"] = f"YouTube fallback: https://www.youtube.com/watch?v={video_id}"
                            tags.save()
                        except MutagenError as error:
                            log.write(f"Invalid YouTube audio: {video_id} — {error}\n")
                            continue
                        filename = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", label).strip(" .")
                        filename = filename.encode("utf-8")[:180].decode("utf-8", errors="ignore")
                        identity = hashlib.sha256(json.dumps(track, sort_keys=True).encode("utf-8")).hexdigest()[:10]
                        destination = Path(output_dir, f"{filename} [yt-{identity}].flac")
                        os.replace(audio, destination)
                        recovered += 1
                        downloaded = True
                        print(f"   ✅ YouTube recovered: {label}", flush=True)
                        log.write(f"YouTube recovered: {label} ({video_id})\n")
                        break
                if not downloaded:
                    raise RuntimeError("All matching YouTube downloads failed")
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, ImportError) as error:
                print(f"   ⚠️ Still missing: {label} — {error}", flush=True)
                log.write(f"Still missing: {label} — {error}\n")
            finally:
                log.flush()

    unresolved = len(tracks) - recovered
    print(f"📋 YouTube: recovered {recovered}; still missing {unresolved}.", flush=True)
    return recovered, unresolved
