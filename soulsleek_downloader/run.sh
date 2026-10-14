#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Soulsleek Downloader"

SPOTIFY_PLAYLIST_URL=$(bashio::config 'spotify_playlist_url')
OUTPUT_DIRECTORY=$(bashio::config 'output_directory')
SOULSEEK_USER=$(bashio::config 'soulseek_user')
SOULSEEK_PASS=$(bashio::config 'soulseek_pass')
PREFERRED_FORMAT=$(bashio::config 'preferred_format')

# Existing installations may not have the new option saved yet.
YOUTUBE_ARGS=(--youtube-fallback)
if bashio::config.has_value 'youtube_fallback' && bashio::config.false 'youtube_fallback'; then
    YOUTUBE_ARGS=(--no-youtube-fallback)
fi

bashio::log.info "Spotify Playlist URL: ${SPOTIFY_PLAYLIST_URL}"
bashio::log.info "Output Directory: ${OUTPUT_DIRECTORY}"

python3 /app/main.py \
    --playlist-url "$SPOTIFY_PLAYLIST_URL" \
    --output-dir "$OUTPUT_DIRECTORY" \
    --user "$SOULSEEK_USER" \
    --pass "$SOULSEEK_PASS" \
    --pref-format "$PREFERRED_FORMAT" \
    "${YOUTUBE_ARGS[@]}"
