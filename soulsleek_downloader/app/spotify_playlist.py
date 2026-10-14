"""Resolve public Spotify metadata to the CSV supported by slsk-batchdl."""

import csv
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit


def playlist_id(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r"/(?:intl-[a-z-]+/)?playlist/([A-Za-z0-9]{22})/?", parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "open.spotify.com" or not match:
        raise ValueError("Expected an https://open.spotify.com/playlist/... URL")
    return match.group(1)


def export_playlist(url, destination, client_factory=None):
    identifier = playlist_id(url)
    if client_factory is None:
        from spotapi import PublicPlaylist
        client_factory = PublicPlaylist
    client = client_factory(identifier)
    rows = []
    offset = 0
    expected_total = None
    skipped = 0
    while True:
        response = client.get_playlist_info(limit=100, offset=offset)
        playlist = response.get("data", {}).get("playlistV2") or {}
        content = playlist.get("content")
        if not isinstance(content, dict):
            raise ValueError("Spotify playlist is unavailable. Check that it is public and the URL is correct.")
        total = content.get("totalCount")
        items = content.get("items")
        if not isinstance(total, int) or total < 0 or not isinstance(items, list):
            raise ValueError("Unexpected Spotify playlist response")
        if expected_total is None:
            expected_total = total
            name = playlist.get("name", identifier)
        elif total != expected_total:
            raise ValueError("Playlist changed during import; please run the add-on again")
        if len(items) > expected_total - offset or (not items and offset < expected_total):
            raise ValueError("Spotify returned an incomplete or inconsistent playlist page")
        for item in items:
            track = (item.get("itemV2") or {}).get("data") or {}
            if track.get("__typename") != "Track":
                skipped += 1  # Episodes, removed/local tracks are not searchable songs.
                continue
            title = track.get("name")
            artists = (track.get("artists") or {}).get("items") or []
            artist = ((artists[0].get("profile") or {}).get("name") if artists else None)
            milliseconds = (track.get("trackDuration") or {}).get("totalMilliseconds")
            if not title or not artist or not isinstance(milliseconds, (int, float)) or milliseconds <= 0:
                raise ValueError("Spotify returned a song without title, artist, or duration; refusing a partial import")
            rows.append({
                "artist": artist, "title": title,
                "album": (track.get("albumOfTrack") or {}).get("name", ""),
                "length": int(milliseconds / 1000),
            })
        offset += len(items)
        if offset == expected_total:
            break
    if not rows:
        raise ValueError("Spotify playlist contains no searchable music tracks")
    target = Path(destination)
    temporary = target.with_suffix(".csv.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["artist", "title", "album", "length"])
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Spotify playlist: {name} — {len(rows)} tracks ({skipped} non-track/unavailable entries skipped)", flush=True)
    return len(rows)


def prepare_spotify_playlist(url, directory):
    """Bound the entire metadata lookup, including retries inside the library."""
    playlist_id(url)
    destination = os.path.join(directory, "playlist.csv")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), url, destination],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", timeout=180, check=False,
    )
    if result.stdout:
        print(result.stdout.strip(), flush=True)
    if result.returncode or not os.path.isfile(destination):
        raise RuntimeError("Could not load Spotify tracks; Soulseek and YouTube downloads have not started")
    return destination


if __name__ == "__main__":
    try:
        export_playlist(sys.argv[1], sys.argv[2])
    except Exception as error:
        # Third-party exceptions may contain request headers/tokens. Keep those private.
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"Spotify import failed: {detail}", flush=True)
        sys.exit(1)
