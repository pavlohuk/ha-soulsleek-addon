# Soulsleek Downloader Add-on

This Home Assistant add-on downloads music from Soulseek using a Spotify playlist link.
The Spotify playlist must be public. Version 0.6.1 resolves its metadata using
SpotAPI and passes the complete track list to Soulseek as CSV, avoiding the old
slsk-batchdl Spotify API reader. The complete metadata lookup is limited to three
minutes. Incomplete/changing playlists stop with a visible error instead of
silently downloading a partial list. Episodes and unavailable non-track entries
are counted and skipped.
It then processes the downloaded music to:
- Update metadata and add cover art using Beets.
- Normalize volume.
- Convert to a bitrate compatible with Sonos.
- Check for file integrity.
- Save the files to a specified directory in Home Assistant OS.

## YouTube fallback (0.6.0)

Soulseek remains the primary source. When `youtube_fallback: true` (the default),
the add-on reads the current run's structured Soulseek index and searches YouTube
only for tracks that were not found or exhausted their download attempts.
Downloaded/already-existing tracks, login errors, and playlist metadata errors
do not trigger YouTube downloads. Turn the option off to use Soulseek only.

```yaml
youtube_fallback: true
```

The search uses the Spotify artist and title and checks up to five results.
When the playlist provides a duration, the allowed difference is 10 seconds or
5%, whichever is greater. Live streams and upcoming videos are skipped. Matching
is automatic: a different edit, cover, or recording can still be selected.

Recovered audio keeps the playlist's artist, title, and album tags, with the
YouTube URL in the comment. It passes through the existing -14 LUFS normalization
and 320 kbps / 44.1 kHz MP3 conversion. A temporary FLAC avoids an extra lossy
encode; it does not increase the quality of the YouTube source. Files use a
`[yt-...]` suffix to avoid overwriting Soulseek files.

Searches have a two-minute timeout; each candidate download has a five-minute
timeout. Failed/partial attempts are removed, and remaining tracks continue.
If normalization fails, the downloads folder is retained for retry.

The Home Assistant log shows each recovered track and the remaining failure
count. Detailed YouTube diagnostics are appended to `download_log.txt` in
`output_directory`. Access restrictions or unavailable videos can prevent a
download; a failure does not stop processing successfully downloaded music.

CLI: use `--no-youtube-fallback` to disable recovery. Local `--process-dir`
processing never searches or downloads anything.

## Development checks

The image includes FFmpeg, Node.js, yt-dlp (with EJS), Beets, and Mutagen.
`slsk-batchdl` is pinned to 2.6.0 to retain the existing CLI and CSV index format;
its two projects are built against .NET 8. Upstream 3.x uses a different project
layout and CLI, so following its default branch would break this add-on's build.

Run tests with Python 3.10+, Mutagen and FFmpeg installed:

```sh
python3 -m unittest discover -s tests -v
bash -n soulsleek_downloader/run.sh
```

Tests use synthetic audio and mocked network downloads; they need no accounts.

If startup fails, read the add-on's Home Assistant **Log** tab. Soulseek's full
output is also saved to `<output_directory>/download_log.txt` (the Home Assistant
`/media` mount, not `/config/media`). A metadata failure happens before that file
is created and is reported directly in the Log tab. YouTube cannot search until
the Spotify track list has been read successfully.
