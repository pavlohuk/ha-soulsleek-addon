"""Playlist metadata, persistent sync state, output naming and tagging."""

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

from mutagen import File, MutagenError
from mutagen.id3 import APIC, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX

STATE_VERSION = 1
# Every format slsk-batchdl 2.6.0 accepts by default (alac arrives as .m4a), plus yt-dlp FLAC.
AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wav", ".aif", ".aiff", ".alac"}
COVER_HOSTS = {"i.scdn.co", "image-cdn-ak.spotifycdn.com", "image-cdn-fa.spotifycdn.com"}


def track_key(row):
    """Identity shared by the Soulseek CSV, its index and the playlist metadata."""
    return tuple(str(row.get(key) or "").strip() for key in ("artist", "title", "album", "length"))


def state_id(track):
    return track.get("uri") or "\x1f".join(track_key(track))


def load_metadata(path):
    """Return {track_key: metadata}; a missing file means no Spotify metadata."""
    try:
        with open(path, encoding="utf-8") as stream:
            document = json.load(stream)
    except FileNotFoundError:
        return {}
    return {track_key(track): track for track in document.get("tracks", [])}


def write_csv(path, rows, fieldnames=("artist", "title", "album", "length")):
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def safe_filename(text, limit=180):
    name = re.sub(r'[\x00-\x1f/\\:*?"<>|]', "_", text).strip(" .")
    return name.encode("utf-8")[:limit].decode("utf-8", errors="ignore").strip(" .") or "track"


class SyncState:
    """Tracks already converted into the library, persisted in the add-on /data."""

    def __init__(self, path, output_dir):
        self.path = Path(path) if path else None
        self.output_dir = Path(output_dir)
        self.tracks = {}
        if self.path and self.path.is_file():
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
                if document.get("version") == STATE_VERSION:
                    self.tracks = document.get("tracks", {})
            except (OSError, ValueError) as error:
                print(f"⚠️ Ignoring unreadable sync state: {error}", flush=True)

    def owner(self, filename):
        for key, entry in self.tracks.items():
            if entry.get("file") == filename:
                return key
        return None

    def is_synced(self, track):
        entry = self.tracks.get(state_id(track))
        return bool(entry and (self.output_dir / entry["file"]).is_file())

    def mark(self, track, filename, source):
        self.tracks[state_id(track)] = {
            "file": filename, "source": source,
            "artist": track.get("artist", ""), "title": track.get("title", ""),
            "synced": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=self.path.parent, delete=False, encoding="utf-8") as stream:
            json.dump({"version": STATE_VERSION, "tracks": self.tracks}, stream, ensure_ascii=False, indent=1)
        os.replace(stream.name, self.path)


def adopt_existing(state, tracks, output_dir):
    """Claim library files from earlier versions so upgrades do not re-download them."""
    wanted = {}
    for track in tracks:
        if not state.is_synced(track):
            wanted.setdefault((track["artist"].casefold(), track["title"].casefold()), []).append(track)
    if not wanted:
        return 0
    adopted = 0
    for path in sorted(Path(output_dir).glob("*.mp3")):
        if state.owner(path.name):
            continue
        try:
            audio = File(path, easy=True)
            if audio is None or not audio.tags:
                continue
            tags = tuple(str((audio.get(key) or [""])[0]).strip().casefold() for key in ("artist", "title"))
            length = audio.info.length
        except (OSError, ValueError, MutagenError):
            continue
        for track in wanted.get(tags, []):
            if not state.is_synced(track) and abs(length - float(track["length"])) <= 3:
                state.mark(track, path.name, "existing")
                adopted += 1
                break
    return adopted


class OutputNames:
    """Deterministic, unique MP3 names; never reuse a file owned by another track."""

    def __init__(self, output_dir, state):
        self.output_dir = Path(output_dir)
        self.state = state
        self.reserved = set()

    def reserve(self, base, track=None):
        own = state_id(track) if track else None
        stem = safe_filename(base)
        for number in range(1, 1000):
            name = f"{stem}.mp3" if number == 1 else f"{stem} ({number}).mp3"
            if name in self.reserved:
                continue
            owner = self.state.owner(name)
            if owner is not None and owner != own:
                continue
            if owner is None and track is not None and (self.output_dir / name).exists():
                continue  # An unrelated or untracked file; keep it.
            self.reserved.add(name)
            return name
        raise ValueError(f"No free output name for {base}")


def track_label(track):
    return " - ".join(value for value in (track.get("artist", ""), track.get("title", "")) if value)


_covers = {}


def fetch_cover(url):
    if not url:
        return None
    if url in _covers:
        return _covers[url]
    data = None
    if url.startswith("https://") and urllib.parse.urlsplit(url).hostname in COVER_HOSTS:
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                if response.headers.get_content_type() in {"image/jpeg", "image/png"}:
                    data = (response.headers.get_content_type(), response.read(5_000_000))
        except OSError as error:
            print(f"   ⚠️ Cover download failed: {error}", flush=True)
    _covers[url] = data
    return data


def write_tags(path, track):
    """Replace the peer's tags with the playlist's identity (ID3v2.3 for Sonos)."""
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    artists = track.get("artists") or [track["artist"]]
    for junk in ("major_brand", "minor_version", "compatible_brands"):  # MP4 container leftovers
        tags.delall(f"TXXX:{junk}")
    tags.setall("TIT2", [TIT2(encoding=3, text=track["title"])])
    tags.setall("TPE1", [TPE1(encoding=3, text=", ".join(artists))])
    tags.setall("TALB", [TALB(encoding=3, text=track.get("album", ""))])
    if track.get("album_artist"):
        tags.setall("TPE2", [TPE2(encoding=3, text=track["album_artist"])])
    if track.get("track_number"):
        tags.setall("TRCK", [TRCK(encoding=3, text=str(track["track_number"]))])
    if track.get("disc_number"):
        tags.setall("TPOS", [TPOS(encoding=3, text=str(track["disc_number"]))])
    if track.get("year"):
        tags.setall("TDRC", [TDRC(encoding=3, text=str(track["year"]))])
    if track.get("uri"):
        tags.setall("TXXX:SPOTIFY_URI", [TXXX(encoding=3, desc="SPOTIFY_URI", text=track["uri"])])
    cover = fetch_cover(track.get("cover_url"))
    if cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=cover[0], type=3, desc="Cover", data=cover[1]))
    tags.save(path, v2_version=3)

