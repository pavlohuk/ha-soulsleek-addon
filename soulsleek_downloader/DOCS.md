# Soulsleek Downloader

Syncs a public Spotify playlist into your Home Assistant media folder:

1. Reads the playlist from Spotify (no Spotify account needed; the playlist must be public).
2. Downloads tracks that are not in your library yet from Soulseek.
3. Optionally recovers tracks Soulseek could not provide from YouTube.
4. Normalizes loudness (two-pass, default −14 LUFS) and saves 320 kbps / 44.1 kHz MP3
   (Sonos compatible).
5. Tags every file with the playlist's metadata: title, all artists, album, album artist,
   track/disc number, year and the Spotify cover art.

The add-on is a batch job: it runs once and stops. It does not start with Home Assistant.

## Configuration

| Option | Default | Description |
| --- | --- | --- |
| `spotify_playlist_url` | | `https://open.spotify.com/playlist/...` |
| `output_directory` | `/media/` | Must be inside `/media` or `/share`. |
| `soulseek_user`, `soulseek_pass` | | Your Soulseek account. |
| `preferred_format` | `mp3` | `mp3` or `flac`: a Soulseek search preference. Output is always MP3. |
| `youtube_fallback` | `true` | Search YouTube for tracks missing on Soulseek. |
| `concurrent_downloads` | `2` | 1–4 parallel Soulseek transfers. More can exhaust file descriptors. |
| `target_loudness` | `-14` | Integrated loudness target in LUFS (−24…−8). |
| `notify` | `true` | Create a Home Assistant notification and fire an event when finished. |
| `update_yt_dlp` | `true` | Update yt-dlp on every start; YouTube changes often. |

## Incremental sync

Each run downloads only tracks that are not in the library yet. The add-on remembers
converted tracks per playlist in its private storage (`/data/state`, included in
add-on backups). Delete an MP3 from the output folder and the next run downloads it again.

On the first run after upgrading from 0.6.x, existing MP3 files in the output folder
(top level only) whose artist/title tags and duration match a playlist track are adopted
instead of downloaded again.

## Running on a schedule

Start the add-on from an automation:

```yaml
automation:
  - alias: Sync Spotify playlist nightly
    triggers:
      - trigger: time
        at: "03:00:00"
    actions:
      - action: hassio.addon_start
        data:
          addon: <repository-hash>_soulsleek_downloader
```

The add-on's full slug is shown in the add-on page URL.

When `notify` is on, every run ends with a persistent notification and the event
`soulsleek_downloader_finished`:

```yaml
playlist_url: https://open.spotify.com/playlist/...
added: 12             # tracks converted in this run
missing: ["Artist - Title", ...]
conversion_failures: 0
success: true
```

## Output files

Files are named `Artist - Title.mp3` in `output_directory`. A name already used by
another track or by a file the add-on did not create gets a ` (2)` suffix; existing
files are never overwritten by a different track.

Downloads are staged in `<output_directory>/downloads`. Each source file is removed
right after its own conversion succeeds. Files that fail to convert stay there and are
retried on the next run. Soulseek's full output and YouTube diagnostics are written to
`<output_directory>/download_log.txt`.

## YouTube fallback

Soulseek remains the primary source. With `youtube_fallback: true`, the add-on searches
YouTube only for tracks that were not found or exhausted their download attempts; login
and playlist errors never trigger it.

The search uses the Spotify artist and title and checks up to five results. When the
playlist provides a duration, the allowed difference is 10 seconds or 5%, whichever is
greater. Live streams and upcoming videos are skipped. Matching is automatic: a different
edit, cover, or recording can still be selected. The YouTube URL is kept in the comment tag.

Searches have a two-minute timeout; each candidate download has a five-minute timeout.
Failed or partial attempts are removed and the remaining tracks continue.

## Crash recovery

The downloader raises its soft open-file limit to 16384 (capped by the container's hard
limit). After a signal termination or descriptor exhaustion, recovery compares the
requested tracks with completed index entries and with exact artist/title/album tags plus
duration (within two seconds) of downloaded audio. Unconfirmed tracks become eligible for
YouTube recovery. Partial files are ignored.

## Troubleshooting

- Read the add-on's **Log** tab first. A Spotify failure happens before any download and
  is reported there.
- The Spotify playlist must be public. Episodes and unavailable entries are skipped.
- The add-on exits with an error when the Soulseek downloader fails or a conversion
  fails; already converted tracks are kept.

## Development

The image contains FFmpeg, Node.js, yt-dlp (with EJS), Mutagen and SpotAPI.
`slsk-batchdl` is pinned to 2.6.0 to keep its CLI and CSV index format and is compiled
against .NET 8 in a separate build stage; only the self-contained binary is copied into
the image.

Run the tests with Python 3.10+, Mutagen and FFmpeg (with libopus) installed:

```sh
python3 -m unittest discover -s tests -v
bash -n soulsleek_downloader/run.sh
```

Tests use synthetic audio and mocked network downloads; they need no accounts.
