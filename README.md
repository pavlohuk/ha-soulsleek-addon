# Soulsleek Add-ons Repository

Home Assistant add-ons repository for music management.

## Add-ons

### Soulsleek Downloader

Downloads music from Soulseek using Spotify playlist links and processes it for optimal quality.

**Features:**
- Download from Soulseek using Spotify playlist URLs
- Two-pass loudness normalization (-14 LUFS)
- Convert to 320kbps MP3, 44.1kHz (Sonos compatible)
- Local directory processing support
- Detailed logging and error handling

## Installation

1. Add this repository to Home Assistant:
   ```
   https://github.com/pavlohuk/ha-soulsleek-addon
   ```

2. Install the "Soulsleek Downloader" add-on

3. Configure your Soulseek credentials in the add-on settings

4. Provide a Spotify playlist URL and start downloading!

## Configuration

- **spotify_playlist_url**: URL of your Spotify playlist
- **output_directory**: Where to save processed music (default: `/media/`)
- **soulseek_user**: Your Soulseek username
- **soulseek_pass**: Your Soulseek password
- **preferred_format**: Preferred download format (`mp3` or `flac`)

## Requirements

- Home Assistant OS or Supervised
- Soulseek account
- Access to `/media/` directory