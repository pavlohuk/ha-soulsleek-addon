# Changelog

## 0.7.0

- Incremental sync: only tracks that are not in the library yet are downloaded. State is
  kept per playlist in `/data/state`; files from 0.6.x with matching tags are adopted.
- Fix: m4a, opus, aac and alac downloads were deleted without being converted.
- Tag files from the Spotify playlist (artists, album, album artist, track/disc number,
  year, cover art) instead of Beets, which never autotagged and scanned the whole
  output folder. Beets is removed.
- Name files `Artist - Title.mp3`; colliding names get a suffix instead of overwriting.
- Remove each download right after its own conversion; failed files are kept for retry.
- The add-on now runs once and no longer starts with Home Assistant (`startup: once`,
  `boot: manual`). `full_access` and the `ssl` mapping are removed.
- New options: `concurrent_downloads`, `target_loudness`, `notify` (notification and
  `soulsleek_downloader_finished` event), `update_yt_dlp`.
- `preferred_format` accepts only `mp3` or `flac`.
- The Soulseek password is no longer visible in the process list.
- Exit with an error when the downloader or a conversion fails.
- Supported architectures: aarch64 and amd64 (32-bit builds never worked).
- Smaller image: slsk-batchdl is compiled in a separate build stage.
- Install prebuilt images from GHCR instead of building on the device.

## 0.6.2

- Raise the soft open-file limit to 16384 where allowed by the container and limit
  Soulseek to two concurrent downloads to reduce descriptor exhaustion.
- Reconcile interrupted downloads against the complete playlist after a crash,
  recovering unfinished tracks even when the native index is missing or truncated.
- Use the structured recovery list for failure totals, including exhausted retries,
  and explain signal termination such as SIGABRT (-6).

## 0.6.1

- Resolve public Spotify playlists with SpotAPI before sending complete track
  metadata to Soulseek as CSV. This avoids the old downloader's failing Spotify API lookup.
- Paginate and validate the playlist before starting downloads; reject incomplete imports.
- Show downloader errors directly in the Home Assistant log and report startup failure
  with a nonzero exit status instead of a misleading successful completion.
- Skip YouTube recovery cleanly when the downloader never produced track results.

## 0.6.0

- Add optional YouTube recovery for tracks missing or unsuccessfully downloaded
  on Soulseek; enabled by default with the `youtube_fallback` setting.
- Match search results by duration and preserve Spotify artist/title/album tags.
- Bound retries and timeouts, isolate incomplete downloads, and report remaining failures.
- Keep original downloads when normalization fails.
- Include yt-dlp/EJS and Node.js; pin the compatible Soulseek downloader source
  and build it using .NET 8 to avoid upstream project renaming breaking builds.
