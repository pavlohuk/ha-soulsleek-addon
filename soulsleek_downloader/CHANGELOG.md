# Changelog

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
