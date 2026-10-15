# Soulsleek Add-ons Repository

Home Assistant add-ons repository for music management.

## Add-ons

### Soulsleek Downloader

Downloads music from Soulseek using Spotify playlist links and processes it for optimal quality.

**Features:**
- Incremental sync of a public Spotify playlist: only new tracks are downloaded
- Download from Soulseek, recover missing tracks from YouTube (optional)
- Two-pass loudness normalization (default -14 LUFS)
- 320kbps MP3, 44.1kHz (Sonos compatible)
- Tags and cover art from Spotify
- Home Assistant notification and event when finished

## Installation

1. Add this repository to Home Assistant:
   ```
   https://github.com/pavlohuk/ha-soulsleek-addon
   ```

2. Install the "Soulsleek Downloader" add-on

3. Configure your Soulseek credentials in the add-on settings

4. Provide a Spotify playlist URL and start downloading!

## Configuration

- **spotify_playlist_url**: URL of your public Spotify playlist
- **output_directory**: Where to save processed music, inside `/media` or `/share` (default: `/media/`)
- **soulseek_user** / **soulseek_pass**: Your Soulseek account
- **preferred_format**: Preferred Soulseek format (`mp3` or `flac`); output is always MP3
- **youtube_fallback**: Search YouTube for tracks missing on Soulseek (default: `true`)
- **concurrent_downloads**: Parallel Soulseek transfers, 1–4 (default: `2`)
- **target_loudness**: Loudness target in LUFS (default: `-14`)
- **notify**: Notification and event when finished (default: `true`)
- **update_yt_dlp**: Update yt-dlp on start (default: `true`)

See the [add-on documentation](soulsleek_downloader/DOCS.md) for incremental sync,
scheduling and troubleshooting.

## Requirements

- Home Assistant OS or Supervised on aarch64 or amd64
- Soulseek account
- Access to `/media/` directory
